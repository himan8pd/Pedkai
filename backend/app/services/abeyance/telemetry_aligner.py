"""Telemetry-to-text alignment for Abeyance Memory multi-modal matching.

Converts structured anomaly events into natural language descriptions,
then embeds them using the same embedding model as text fragments.
This allows cross-modal similarity search (telemetry ↔ text).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4
import numpy as np

from .cold_storage import AbeyanceFragment

logger = logging.getLogger(__name__)


@dataclass
class AnomalyFinding:
    """Structured anomaly event for telemetry alignment."""
    entity_id: str
    tenant_id: str
    domain: str
    kpi_name: str
    value: float
    z_score: float
    timestamp: datetime
    affected_metrics: list[str] = field(default_factory=list)
    neighbour_count: int = 0
    neighbour_summary: str = ""
    metadata: dict = field(default_factory=dict)


# Telemetry-to-text template from spec §4:
_TELEMETRY_TEMPLATE = (
    "On {timestamp}, cell {entity_id} in {domain} showed {kpi_name} at {value:.2f} "
    "({z_score:.1f} standard deviations from baseline). "
    "Affected metrics: {affected_metrics}. "
    "Similar to {neighbour_count} neighbours: {neighbour_summary}."
)


class TelemetryAligner:
    """Converts anomaly events to Abeyance Memory fragments via text embedding."""

    def __init__(self, embedding_service=None):
        """
        Args:
            embedding_service: Optional embedding service. If None, uses a
                               random embedding (test/offline mode).
        """
        self._embedding_service = embedding_service

    def anomaly_to_text(self, anomaly: AnomalyFinding) -> str:
        """Generate natural language description from anomaly event."""
        affected = ", ".join(anomaly.affected_metrics) if anomaly.affected_metrics else anomaly.kpi_name
        ts_str = anomaly.timestamp.strftime("%Y-%m-%d %H:%M UTC") if anomaly.timestamp else "unknown time"
        return _TELEMETRY_TEMPLATE.format(
            timestamp=ts_str,
            entity_id=anomaly.entity_id,
            domain=anomaly.domain,
            kpi_name=anomaly.kpi_name,
            value=anomaly.value,
            z_score=anomaly.z_score,
            affected_metrics=affected,
            neighbour_count=anomaly.neighbour_count,
            neighbour_summary=anomaly.neighbour_summary or "none",
        )

    def embed_anomaly(self, anomaly: AnomalyFinding) -> np.ndarray:
        """Convert anomaly to embedding.

        If embedding_service is available, uses it.
        Falls back to a deterministic hash-based vector (for offline/test mode).
        """
        text = self.anomaly_to_text(anomaly)

        if self._embedding_service is not None:
            try:
                # Embedding service may be async; handle both cases
                import asyncio
                if asyncio.iscoroutinefunction(self._embedding_service.generate_embedding):
                    # Run in event loop if available
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Can't block; return fallback
                        logger.warning("async embedding service can't block; using fallback embedding")
                        return self._hash_embedding(text)
                    else:
                        result = loop.run_until_complete(
                            self._embedding_service.generate_embedding(text)
                        )
                        if result is not None:
                            return np.array(result, dtype=float)
                else:
                    result = self._embedding_service.generate_embedding(text)
                    if result is not None:
                        return np.array(result, dtype=float)
            except Exception as e:
                logger.warning(f"Embedding service error: {e}; using fallback")

        return self._hash_embedding(text)

    def _hash_embedding(self, text: str, dim: int = 64) -> np.ndarray:
        """Deterministic hash-based embedding for offline/test mode (dim=64)."""
        import hashlib
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(dim)
        return vec / (np.linalg.norm(vec) + 1e-10)

    def store_anomaly_fragment(self, anomaly: AnomalyFinding, storage=None) -> AbeyanceFragment:
        """Create and optionally store a telemetry AbeyanceFragment.

        Args:
            anomaly: The anomaly finding to store
            storage: Optional AbeyanceColdStorage instance. If None, just creates fragment.

        Returns AbeyanceFragment with modality='telemetry'.
        """
        embedding = self.embed_anomaly(anomaly)
        fragment = AbeyanceFragment(
            fragment_id=str(uuid4()),
            tenant_id=anomaly.tenant_id,
            embedding=embedding.tolist(),
            created_at=anomaly.timestamp.isoformat() if anomaly.timestamp else datetime.now(timezone.utc).isoformat(),
            decay_score=1.0,
            status="ACTIVE",
            corroboration_count=0,
            metadata={
                "modality": "telemetry",
                "entity_id": anomaly.entity_id,
                "kpi_name": anomaly.kpi_name,
                "z_score": anomaly.z_score,
                "domain": anomaly.domain,
                "text_description": self.anomaly_to_text(anomaly),
            }
        )

        if storage is not None:
            storage.archive_fragment(fragment)

        return fragment
