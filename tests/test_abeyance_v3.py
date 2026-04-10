"""Tests for Abeyance Memory v3.0 integration.

Covers:
- v3 weight profiles validation
- v3 service factory wiring
- v3 ORM model table names
- SnapEngineV3 mask-aware weight redistribution
- EnrichmentChainV3 sinusoidal temporal vector
- v3 schemas
"""

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# v3 Weight Profiles
# ---------------------------------------------------------------------------

class TestV3WeightProfiles:
    """All v3 weight profiles must sum to 1.0 and have 5 dimensions."""

    def test_all_v3_profiles_sum_to_one(self):
        from backend.app.services.abeyance.snap_engine_v3 import WEIGHT_PROFILES_V3
        for mode, weights in WEIGHT_PROFILES_V3.items():
            total = sum(weights.values())
            assert total == pytest.approx(1.0, abs=1e-9), (
                f"v3 weight profile {mode} sums to {total}"
            )

    def test_all_v3_profiles_have_five_dimensions(self):
        from backend.app.services.abeyance.snap_engine_v3 import WEIGHT_PROFILES_V3
        expected_keys = {"w_sem", "w_topo", "w_temp", "w_oper", "w_ent"}
        for mode, weights in WEIGHT_PROFILES_V3.items():
            assert set(weights.keys()) == expected_keys, f"{mode} missing keys"

    def test_all_v3_weights_positive(self):
        from backend.app.services.abeyance.snap_engine_v3 import WEIGHT_PROFILES_V3
        for mode, weights in WEIGHT_PROFILES_V3.items():
            for key, val in weights.items():
                assert val > 0, f"{mode}.{key} = {val} must be positive"


# ---------------------------------------------------------------------------
# Service Factory v3
# ---------------------------------------------------------------------------

class TestServiceFactoryV3:
    """Verify create_abeyance_services returns v3 services."""

    def test_factory_returns_v3_services(self):
        from backend.app.services.abeyance import create_abeyance_services
        services = create_abeyance_services()
        v3_keys = {
            "tvec", "tslam", "enrichment_v3", "snap_engine_v3",
            "discovery_loop",
        }
        for key in v3_keys:
            assert key in services, f"Missing v3 service: {key}"

    def test_factory_returns_v2_services(self):
        """v2 backward compat services still present."""
        from backend.app.services.abeyance import create_abeyance_services
        services = create_abeyance_services()
        # Note: "enrichment" and "snap_engine" were replaced by v3 variants
        # ("enrichment_v3" and "snap_engine_v3") and "notifier" was removed.
        v2_keys = {
            "provenance", "accumulation_graph", "decay_engine",
            "shadow_topology", "value_attribution",
            "incident_reconstruction", "maintenance",
        }
        for key in v2_keys:
            assert key in services, f"Missing v2 service: {key}"

    def test_factory_returns_discovery_mechanisms(self):
        from backend.app.services.abeyance import create_abeyance_services
        services = create_abeyance_services()
        mechanism_keys = [
            "surprise_engine", "ignorance_mapper", "negative_evidence",
            "bridge_detector", "outcome_calibration", "pattern_conflict",
            "temporal_sequence", "hypothesis_generator", "expectation_violation",
            "causal_direction", "pattern_compressor", "counterfactual_sim",
            "meta_memory", "evolutionary_patterns",
        ]
        for key in mechanism_keys:
            assert key in services, f"Missing discovery mechanism: {key}"

    def test_v3_services_share_provenance(self):
        from backend.app.services.abeyance import create_abeyance_services
        services = create_abeyance_services()
        prov = services["provenance"]
        assert services["snap_engine_v3"]._provenance is prov
        assert services["enrichment_v3"]._provenance is prov


# ---------------------------------------------------------------------------
# v3 ORM Models
# ---------------------------------------------------------------------------

class TestV3ORMModels:
    """v3 ORM tables import and have correct __tablename__."""

    def test_all_v3_models_importable(self):
        from backend.app.models.abeyance_v3_orm import (
            SurpriseEventORM, SurpriseDistributionStateORM,
            IgnoranceExtractionStatORM, IgnoranceMaskDistributionORM,
            IgnoranceSilentDecayRecordORM, IgnoranceSilentDecayStatORM,
            IgnoranceMapEntryORM, ExplorationDirectiveORM, IgnoranceJobRunORM,
            DisconfirmationEventORM, DisconfirmationFragmentORM, DisconfirmationPatternORM,
            BridgeDiscoveryORM, BridgeDiscoveryProvenanceORM,
            SnapOutcomeFeedbackORM, CalibrationHistoryORM, WeightProfileActiveORM,
            ConflictRecordORM, ConflictDetectionLogORM,
            EntitySequenceLogORM, TransitionMatrixORM, TransitionMatrixVersionORM,
            HypothesisORM, HypothesisEvidenceORM, HypothesisGenerationQueueORM,
            ExpectationViolationORM,
            CausalCandidateORM, CausalEvidencePairORM, CausalAnalysisRunORM,
            CompressionDiscoveryEventORM,
            CounterfactualSimulationResultORM, CounterfactualPairDeltaORM,
            CounterfactualCandidateQueueORM, CounterfactualJobRunORM,
            MetaMemoryAreaORM, MetaMemoryProductivityORM, MetaMemoryBiasORM,
            MetaMemoryTopologicalRegionORM, MetaMemoryTenantStateORM, MetaMemoryJobRunORM,
            PatternIndividualORM, PatternIndividualArchiveORM,
            EvolutionGenerationLogORM, EvolutionPartitionStateORM,
            MaintenanceJobHistoryORM,
        )
        # Count = 44 (matches LLD)
        model_classes = [
            SurpriseEventORM, SurpriseDistributionStateORM,
            IgnoranceExtractionStatORM, IgnoranceMaskDistributionORM,
            IgnoranceSilentDecayRecordORM, IgnoranceSilentDecayStatORM,
            IgnoranceMapEntryORM, ExplorationDirectiveORM, IgnoranceJobRunORM,
            DisconfirmationEventORM, DisconfirmationFragmentORM, DisconfirmationPatternORM,
            BridgeDiscoveryORM, BridgeDiscoveryProvenanceORM,
            SnapOutcomeFeedbackORM, CalibrationHistoryORM, WeightProfileActiveORM,
            ConflictRecordORM, ConflictDetectionLogORM,
            EntitySequenceLogORM, TransitionMatrixORM, TransitionMatrixVersionORM,
            HypothesisORM, HypothesisEvidenceORM, HypothesisGenerationQueueORM,
            ExpectationViolationORM,
            CausalCandidateORM, CausalEvidencePairORM, CausalAnalysisRunORM,
            CompressionDiscoveryEventORM,
            CounterfactualSimulationResultORM, CounterfactualPairDeltaORM,
            CounterfactualCandidateQueueORM, CounterfactualJobRunORM,
            MetaMemoryAreaORM, MetaMemoryProductivityORM, MetaMemoryBiasORM,
            MetaMemoryTopologicalRegionORM, MetaMemoryTenantStateORM, MetaMemoryJobRunORM,
            PatternIndividualORM, PatternIndividualArchiveORM,
            EvolutionGenerationLogORM, EvolutionPartitionStateORM,
            MaintenanceJobHistoryORM,
        ]
        table_names = {m.__tablename__ for m in model_classes}
        assert len(table_names) == 45  # 44 + maintenance_job_history

    def test_all_v3_models_have_tenant_id(self):
        """INV-7: tenant_id on every table."""
        from backend.app.models.abeyance_v3_orm import (
            SurpriseEventORM, IgnoranceExtractionStatORM,
            DisconfirmationEventORM, BridgeDiscoveryORM,
            SnapOutcomeFeedbackORM, ConflictRecordORM,
            EntitySequenceLogORM, HypothesisORM,
            ExpectationViolationORM, CausalCandidateORM,
            CompressionDiscoveryEventORM, CounterfactualSimulationResultORM,
            MetaMemoryAreaORM, PatternIndividualORM, MaintenanceJobHistoryORM,
        )
        for model_cls in [
            SurpriseEventORM, IgnoranceExtractionStatORM,
            DisconfirmationEventORM, BridgeDiscoveryORM,
            SnapOutcomeFeedbackORM, ConflictRecordORM,
            EntitySequenceLogORM, HypothesisORM,
            ExpectationViolationORM, CausalCandidateORM,
            CompressionDiscoveryEventORM, CounterfactualSimulationResultORM,
            MetaMemoryAreaORM, PatternIndividualORM, MaintenanceJobHistoryORM,
        ]:
            assert "tenant_id" in model_cls.__table__.c, (
                f"{model_cls.__tablename__} missing tenant_id (INV-7)"
            )


# ---------------------------------------------------------------------------
# SnapEngineV3: Mask-Aware Weight Redistribution
# ---------------------------------------------------------------------------

class TestSnapEngineV3:
    """Test SnapEngineV3 mask-aware scoring mechanics."""

    def test_redistribute_all_available(self):
        """When all dimensions available, weights unchanged."""
        from backend.app.services.abeyance.snap_engine_v3 import SnapEngineV3, WEIGHT_PROFILES_V3
        from backend.app.services.abeyance.events import ProvenanceLogger
        engine = SnapEngineV3(provenance=ProvenanceLogger())

        base_w = WEIGHT_PROFILES_V3["DARK_EDGE"]
        avail = {
            "semantic": True, "topological": True, "temporal": True,
            "operational": True, "entity_overlap": True,
        }
        result = engine._redistribute_weights(base_w, avail)
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-9)
        for k in base_w:
            assert result[k] == pytest.approx(base_w[k], abs=1e-9)

    def test_redistribute_semantic_missing(self):
        """When semantic unavailable, remaining dimensions renormalize."""
        from backend.app.services.abeyance.snap_engine_v3 import SnapEngineV3, WEIGHT_PROFILES_V3
        from backend.app.services.abeyance.events import ProvenanceLogger
        engine = SnapEngineV3(provenance=ProvenanceLogger())

        base_w = WEIGHT_PROFILES_V3["DARK_EDGE"]
        avail = {
            "semantic": False, "topological": True, "temporal": True,
            "operational": True, "entity_overlap": True,
        }
        result = engine._redistribute_weights(base_w, avail)
        assert result["w_sem"] == 0.0
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-9)

    def test_sidak_v3(self):
        from backend.app.services.abeyance.snap_engine_v3 import _sidak_threshold
        assert _sidak_threshold(0.75, 1) == 0.75
        t5 = _sidak_threshold(0.75, 5)
        assert t5 < 0.75
        assert t5 > 0


# ---------------------------------------------------------------------------
# EnrichmentChainV3: Temporal Vector
# ---------------------------------------------------------------------------

class TestEnrichmentChainV3:
    """Test v3 enrichment chain mechanics."""

    def test_sinusoidal_temporal_vector_length(self):
        from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3, TEMPORAL_DIM
        from backend.app.services.abeyance.events import ProvenanceLogger
        chain = EnrichmentChainV3(provenance=ProvenanceLogger())
        ts = datetime(2026, 3, 16, 14, 30, 0, tzinfo=timezone.utc)
        fp = {
            "change_proximity": {"nearest_change_hours": 12},
            "vendor_upgrade": {"days_since_upgrade": 5},
            "traffic_cycle": {"load_ratio_vs_baseline": 0.8},
        }
        vec = chain._build_temporal_vector(ts, fp)
        assert len(vec) == TEMPORAL_DIM
        assert isinstance(vec, list)

    def test_sinusoidal_values_bounded(self):
        """Sinusoidal features must be in [-1, 1]."""
        from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3
        from backend.app.services.abeyance.events import ProvenanceLogger
        chain = EnrichmentChainV3(provenance=ProvenanceLogger())
        ts = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        fp = {"change_proximity": {}, "vendor_upgrade": {}, "traffic_cycle": {}}
        vec = chain._build_temporal_vector(ts, fp)
        for v in vec[:10]:  # First 10 features are the semantic ones
            assert -1.0 <= v <= 1.0, f"Feature value {v} out of range"

    def test_polarity_detection(self):
        from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3
        assert EnrichmentChainV3._detect_polarity("Traffic spike detected, users up") == "UP"
        assert EnrichmentChainV3._detect_polarity("Signal loss, failure degraded") == "DOWN"
        assert EnrichmentChainV3._detect_polarity("Normal operations") == "NEUTRAL"

    def test_dedup_key_v3(self):
        from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3
        from backend.app.services.abeyance.events import ProvenanceLogger
        chain = EnrichmentChainV3(provenance=ProvenanceLogger())
        ts = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
        key = chain._compute_dedup_key("t1", "ALARM", "REF-1", ts)
        assert key is not None
        assert len(key) == 64

    def test_dedup_key_none_without_source_ref(self):
        from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3
        from backend.app.services.abeyance.events import ProvenanceLogger
        chain = EnrichmentChainV3(provenance=ProvenanceLogger())
        ts = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
        key = chain._compute_dedup_key("t1", "ALARM", None, ts)
        assert key is None


# ---------------------------------------------------------------------------
# v3 Schemas
# ---------------------------------------------------------------------------

class TestV3Schemas:
    def test_discovery_loop_response_schema(self):
        from backend.app.schemas.abeyance import DiscoveryLoopResponse
        r = DiscoveryLoopResponse(tenant_id="t1", fragment_id="f1", stages={"enrich": {"status": "ok"}})
        assert r.tenant_id == "t1"

    def test_discovery_background_response_schema(self):
        from backend.app.schemas.abeyance import DiscoveryBackgroundResponse
        r = DiscoveryBackgroundResponse(tenant_id="t1", results={"bridges": 2})
        assert r.tenant_id == "t1"

    def test_discovery_status_response_schema(self):
        from backend.app.schemas.abeyance import DiscoveryStatusResponse
        r = DiscoveryStatusResponse(
            tenant_id="t1",
            tvec_status={"status": "ready"},
            tslam_status={"status": "ready"},
            mechanisms={"surprise_engine": "available"},
        )
        assert r.mechanisms["surprise_engine"] == "available"


# ---------------------------------------------------------------------------
# Fragment v3 Columns
# ---------------------------------------------------------------------------

class TestFragmentV3Columns:
    """Verify v3 columns on AbeyanceFragmentORM."""

    def test_v3_embedding_columns_exist(self):
        from backend.app.models.abeyance_orm import AbeyanceFragmentORM
        cols = AbeyanceFragmentORM.__table__.c
        for col in ("emb_semantic", "emb_topological", "emb_temporal", "emb_operational"):
            assert col in cols, f"Missing v3 column: {col}"

    def test_v3_mask_columns_exist(self):
        from backend.app.models.abeyance_orm import AbeyanceFragmentORM
        cols = AbeyanceFragmentORM.__table__.c
        for col in ("mask_semantic", "mask_topological", "mask_operational"):
            assert col in cols, f"Missing v3 mask column: {col}"

    def test_polarity_column_exists(self):
        from backend.app.models.abeyance_orm import AbeyanceFragmentORM
        assert "polarity" in AbeyanceFragmentORM.__table__.c

    def test_embedding_schema_version_column(self):
        from backend.app.models.abeyance_orm import AbeyanceFragmentORM
        col = AbeyanceFragmentORM.__table__.c.embedding_schema_version
        assert col.default.arg == 3
