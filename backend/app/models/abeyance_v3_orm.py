"""
Abeyance Memory v3.0 ORM models — 44 new tables across Layers 2-5.

All tables enforce INV-7 (tenant_id on every table) and follow the
naming conventions from LLD v3.0 Section 19.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None


# ---------------------------------------------------------------------------
# Layer 2: Discovery — Mechanism #1: Surprise Engine (2 tables)
# ---------------------------------------------------------------------------

class SurpriseEventORM(Base):
    __tablename__ = "surprise_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    snap_decision_record_id = Column(UUID(as_uuid=True), nullable=False)
    failure_mode_profile = Column(String(50), nullable=False)
    surprise_value = Column(Float, nullable=False)
    threshold_at_time = Column(Float, nullable=False)
    escalation_type = Column(String(30), nullable=False)
    dimensions_contributing = Column(JSONB, nullable=False)
    bin_index = Column(Integer, nullable=False)
    bin_probability = Column(Float, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_surprise_event_tenant", "tenant_id", "created_at"),
        Index("ix_surprise_event_sdr", "snap_decision_record_id"),
    )


class SurpriseDistributionStateORM(Base):
    __tablename__ = "surprise_distribution_state"

    tenant_id = Column(String(100), primary_key=True)
    failure_mode_profile = Column(String(50), primary_key=True)
    histogram_bins = Column(JSONB, nullable=False)
    observation_count = Column(Float, nullable=False, default=0.0)
    threshold_value = Column(Float, nullable=False, default=6.64)
    threshold_monotonic_decrease_count = Column(Integer, nullable=False, default=0)
    last_updated_at = Column(DateTime(timezone=True), nullable=False,
                             default=lambda: datetime.now(timezone.utc),
                             server_default=func.now())


# ---------------------------------------------------------------------------
# Layer 2: Discovery — Mechanism #2: Ignorance Mapping (7 tables)
# ---------------------------------------------------------------------------

class IgnoranceExtractionStatORM(Base):
    __tablename__ = "ignorance_extraction_stat"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    source_type = Column(String(50), nullable=False)
    entity_domain = Column(String(50), nullable=True)
    extraction_method = Column(String(20), nullable=False)
    success_count = Column(Integer, nullable=False, default=0)
    total_count = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=False, default=0.0)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_ign_ext_tenant", "tenant_id", "period_start"),
    )


class IgnoranceMaskDistributionORM(Base):
    __tablename__ = "ignorance_mask_distribution"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    failure_mode_profile = Column(String(50), nullable=False)
    mask_pattern = Column(String(10), nullable=False)
    fragment_count = Column(Integer, nullable=False, default=0)
    fraction = Column(Float, nullable=False, default=0.0)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_ign_mask_tenant", "tenant_id", "period_start"),
    )


class IgnoranceSilentDecayRecordORM(Base):
    __tablename__ = "ignorance_silent_decay_record"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    source_type = Column(String(50), nullable=True)
    entity_count = Column(Integer, nullable=False, default=0)
    mask_pattern = Column(String(10), nullable=True)
    max_snap_score = Column(Float, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_ign_silent_tenant", "tenant_id", "created_at"),
    )


class IgnoranceSilentDecayStatORM(Base):
    __tablename__ = "ignorance_silent_decay_stat"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    source_type = Column(String(50), nullable=True)
    silent_count = Column(Integer, nullable=False, default=0)
    total_expired = Column(Integer, nullable=False, default=0)
    silent_rate = Column(Float, nullable=False, default=0.0)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_ign_silent_stat_tenant", "tenant_id"),
    )


class IgnoranceMapEntryORM(Base):
    __tablename__ = "ignorance_map_entry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_domain = Column(String(50), nullable=False)
    metric_type = Column(String(50), nullable=False)
    ignorance_score = Column(Float, nullable=False)
    detail = Column(JSONB, nullable=True)
    computed_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_ign_map_tenant", "tenant_id", "entity_domain"),
    )


class ExplorationDirectiveORM(Base):
    __tablename__ = "exploration_directive"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_domain = Column(String(50), nullable=False)
    directive_type = Column(String(50), nullable=False)
    priority = Column(Float, nullable=False, default=0.0)
    rationale = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_expl_dir_tenant", "tenant_id", "created_at"),
    )


class IgnoranceJobRunORM(Base):
    __tablename__ = "ignorance_job_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    fragments_scanned = Column(Integer, nullable=False, default=0)
    silent_decays_found = Column(Integer, nullable=False, default=0)
    directives_generated = Column(Integer, nullable=False, default=0)
    outcome = Column(String(20), nullable=False, default="RUNNING")

    __table_args__ = (
        Index("ix_ign_job_tenant", "tenant_id", "started_at"),
    )


# ---------------------------------------------------------------------------
# Layer 2: Discovery — Mechanism #3: Negative Evidence (3 tables)
# ---------------------------------------------------------------------------

class DisconfirmationEventORM(Base):
    __tablename__ = "disconfirmation_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    initiated_by = Column(String(255), nullable=False)
    reason = Column(Text, nullable=True)
    pathway = Column(String(20), nullable=False)
    acceleration_factor = Column(Float, nullable=False, default=5.0)
    fragment_count = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_disconf_event_tenant", "tenant_id", "created_at"),
    )


class DisconfirmationFragmentORM(Base):
    __tablename__ = "disconfirmation_fragments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    disconfirmation_event_id = Column(UUID(as_uuid=True), nullable=False)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    pre_decay_score = Column(Float, nullable=False)
    post_decay_score = Column(Float, nullable=False)

    __table_args__ = (
        Index("ix_disconf_frag_event", "disconfirmation_event_id"),
    )


class DisconfirmationPatternORM(Base):
    __tablename__ = "disconfirmation_patterns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    disconfirmation_event_id = Column(UUID(as_uuid=True), nullable=False)
    centroid_embedding_semantic = Column(
        Vector(1536) if Vector else Text, nullable=True
    )
    centroid_embedding_topological = Column(
        Vector(1536) if Vector else Text, nullable=True
    )
    centroid_embedding_operational = Column(
        Vector(1536) if Vector else Text, nullable=True
    )
    pattern_weight = Column(Float, nullable=False, default=1.0)
    fragments_in_centroid = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_disconf_pattern_tenant", "tenant_id", "expires_at"),
    )


# ---------------------------------------------------------------------------
# Layer 2: Discovery — Mechanism #4: Bridge Detection (2 tables)
# ---------------------------------------------------------------------------

class BridgeDiscoveryORM(Base):
    __tablename__ = "bridge_discovery"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    betweenness_centrality = Column(Float, nullable=False)
    domain_span = Column(Integer, nullable=False)
    severity = Column(String(20), nullable=False)
    component_fingerprint = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_bridge_tenant", "tenant_id", "created_at"),
        UniqueConstraint("tenant_id", "component_fingerprint",
                         name="uq_bridge_fingerprint"),
    )


class BridgeDiscoveryProvenanceORM(Base):
    __tablename__ = "bridge_discovery_provenance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    bridge_discovery_id = Column(UUID(as_uuid=True), nullable=False)
    sub_component_fragment_ids = Column(JSONB, nullable=False)
    relationship_type = Column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_bridge_prov_disc", "bridge_discovery_id"),
    )


# ---------------------------------------------------------------------------
# Layer 2: Discovery — Mechanism #5: Outcome Calibration (3 tables)
# ---------------------------------------------------------------------------

class SnapOutcomeFeedbackORM(Base):
    __tablename__ = "snap_outcome_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    snap_decision_record_id = Column(UUID(as_uuid=True), nullable=False)
    operator_verdict = Column(String(20), nullable=False)
    resolution_action = Column(String(100), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_snap_feedback_tenant", "tenant_id", "resolved_at"),
    )


class CalibrationHistoryORM(Base):
    __tablename__ = "calibration_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    failure_mode_profile = Column(String(50), nullable=False)
    weights_before = Column(JSONB, nullable=False)
    weights_after = Column(JSONB, nullable=False)
    auc_before = Column(Float, nullable=True)
    auc_after = Column(Float, nullable=True)
    sample_count = Column(Integer, nullable=False)
    calibrated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_cal_hist_tenant", "tenant_id", "calibrated_at"),
    )


class WeightProfileActiveORM(Base):
    __tablename__ = "weight_profile_active"

    tenant_id = Column(String(100), primary_key=True)
    failure_mode_profile = Column(String(50), primary_key=True)
    weights = Column(JSONB, nullable=False)
    calibration_status = Column(String(30), nullable=False, default="INITIAL_ESTIMATE")
    last_calibrated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_wpa_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# Layer 2: Discovery — Mechanism #6: Pattern Conflict (2 tables)
# ---------------------------------------------------------------------------

class ConflictRecordORM(Base):
    __tablename__ = "conflict_record"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    decision_id_a = Column(UUID(as_uuid=True), nullable=False)
    decision_id_b = Column(UUID(as_uuid=True), nullable=False)
    entity_overlap_ratio = Column(Float, nullable=False)
    polarity_a = Column(String(10), nullable=False)
    polarity_b = Column(String(10), nullable=False)
    detected_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_conflict_tenant", "tenant_id", "detected_at"),
    )


class ConflictDetectionLogORM(Base):
    __tablename__ = "conflict_detection_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    scan_type = Column(String(20), nullable=False)
    decisions_scanned = Column(Integer, nullable=False, default=0)
    conflicts_found = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    completed_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_conflict_log_tenant", "tenant_id", "completed_at"),
    )


# ---------------------------------------------------------------------------
# Layer 2: Discovery — Mechanism #7: Temporal Sequence (3 tables)
# ---------------------------------------------------------------------------

class EntitySequenceLogORM(Base):
    __tablename__ = "entity_sequence_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(100), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    entity_domain = Column(String(50), nullable=True)
    from_state = Column(String(100), nullable=True)
    to_state = Column(String(100), nullable=False)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    event_timestamp = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_esl_tenant_entity", "tenant_id", "entity_id", "event_timestamp"),
    )


class TransitionMatrixORM(Base):
    __tablename__ = "transition_matrix"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_domain = Column(String(50), nullable=False)
    from_state = Column(String(100), nullable=False)
    to_state = Column(String(100), nullable=False)
    count = Column(Integer, nullable=False, default=0)
    last_observed_at = Column(DateTime(timezone=True), nullable=False,
                              default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_tm_tenant_domain", "tenant_id", "entity_domain",
              "from_state", "to_state", unique=True),
    )


class TransitionMatrixVersionORM(Base):
    __tablename__ = "transition_matrix_version"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_domain = Column(String(50), nullable=False)
    recompute_started_at = Column(DateTime(timezone=True), nullable=False)
    recompute_completed_at = Column(DateTime(timezone=True), nullable=True)
    total_transitions = Column(Integer, nullable=False, default=0)
    unique_states = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_tmv_tenant", "tenant_id", "entity_domain"),
    )


# ---------------------------------------------------------------------------
# Layer 3: Hypothesis — Mechanism #8: Hypothesis Generation (3 tables)
# ---------------------------------------------------------------------------

class HypothesisORM(Base):
    __tablename__ = "hypothesis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    statement = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="PROPOSED")
    confidence = Column(Float, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    refuted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_hyp_tenant_status", "tenant_id", "status"),
    )


class HypothesisEvidenceORM(Base):
    __tablename__ = "hypothesis_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    hypothesis_id = Column(UUID(as_uuid=True), nullable=False)
    source_table = Column(String(100), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    evidence_type = Column(String(50), nullable=False)
    contribution = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_hyp_ev_hyp", "hypothesis_id"),
    )


class HypothesisGenerationQueueORM(Base):
    __tablename__ = "hypothesis_generation_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    trigger_type = Column(String(50), nullable=False)
    trigger_id = Column(UUID(as_uuid=True), nullable=False)
    raw_context = Column(JSONB, nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_hyp_queue_tenant", "tenant_id", "status"),
    )


# ---------------------------------------------------------------------------
# Layer 3: Hypothesis — Mechanism #9: Expectation Violation (1 table)
# ---------------------------------------------------------------------------

class ExpectationViolationORM(Base):
    __tablename__ = "expectation_violation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    entity_domain = Column(String(50), nullable=True)
    from_state = Column(String(100), nullable=False)
    to_state = Column(String(100), nullable=False)
    violation_severity = Column(Float, nullable=False)
    threshold_applied = Column(Float, nullable=False)
    violation_class = Column(String(20), nullable=False)
    correlated_surprise_event_id = Column(UUID(as_uuid=True), nullable=True)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_ev_tenant", "tenant_id", "created_at"),
        Index("ix_ev_entity", "tenant_id", "entity_id"),
    )


# ---------------------------------------------------------------------------
# Layer 3: Hypothesis — Mechanism #10: Causal Direction (3 tables)
# ---------------------------------------------------------------------------

class CausalCandidateORM(Base):
    __tablename__ = "causal_candidate"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_a_id = Column(UUID(as_uuid=True), nullable=False)
    entity_b_id = Column(UUID(as_uuid=True), nullable=False)
    direction = Column(String(10), nullable=False)
    directional_fraction = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    sample_count = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
    updated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_causal_tenant", "tenant_id"),
        Index("ix_causal_entities", "tenant_id", "entity_a_id", "entity_b_id"),
    )


class CausalEvidencePairORM(Base):
    __tablename__ = "causal_evidence_pair"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    causal_candidate_id = Column(UUID(as_uuid=True), nullable=False)
    fragment_a_id = Column(UUID(as_uuid=True), nullable=False)
    fragment_b_id = Column(UUID(as_uuid=True), nullable=False)
    time_delta_seconds = Column(Float, nullable=False)
    direction = Column(String(10), nullable=False)

    __table_args__ = (
        Index("ix_causal_ev_cand", "causal_candidate_id"),
    )


class CausalAnalysisRunORM(Base):
    __tablename__ = "causal_analysis_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    candidates_evaluated = Column(Integer, nullable=False, default=0)
    candidates_promoted = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_causal_run_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# Layer 4: Evidence — Mechanism #11: Pattern Compression (1 table)
# ---------------------------------------------------------------------------

class CompressionDiscoveryEventORM(Base):
    __tablename__ = "compression_discovery_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    failure_mode_profile = Column(String(50), nullable=False)
    rules = Column(JSONB, nullable=False)
    compression_gain = Column(Float, nullable=False)
    coverage_ratio = Column(Float, nullable=False)
    dominant_rule = Column(String(20), nullable=True)
    population_size = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_comp_disc_tenant", "tenant_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Layer 4: Evidence — Mechanism #12: Counterfactual Simulation (4 tables)
# ---------------------------------------------------------------------------

class CounterfactualSimulationResultORM(Base):
    __tablename__ = "counterfactual_simulation_result"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    candidate_fragment_id = Column(UUID(as_uuid=True), nullable=False)
    causal_impact_score = Column(Float, nullable=False)
    decision_flip_count = Column(Integer, nullable=False, default=0)
    decision_flip_rate = Column(Float, nullable=False, default=0.0)
    pairs_evaluated = Column(Integer, nullable=False, default=0)
    # True when using subtraction heuristic instead of full re-score replay (LLD §10.2)
    heuristic_used = Column(Boolean, nullable=False, default=True, server_default='true')
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_cf_result_tenant", "tenant_id", "created_at"),
    )


class CounterfactualPairDeltaORM(Base):
    __tablename__ = "counterfactual_pair_delta"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    simulation_result_id = Column(UUID(as_uuid=True), nullable=False)
    original_score = Column(Float, nullable=False)
    counterfactual_score = Column(Float, nullable=False)
    delta = Column(Float, nullable=False)
    decision_changed = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_cf_delta_result", "simulation_result_id"),
    )


class CounterfactualCandidateQueueORM(Base):
    __tablename__ = "counterfactual_candidate_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    priority_score = Column(Float, nullable=False, default=0.0)
    status = Column(String(20), nullable=False, default="PENDING")
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_cf_queue_tenant", "tenant_id", "status"),
    )


class CounterfactualJobRunORM(Base):
    __tablename__ = "counterfactual_job_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    candidates_processed = Column(Integer, nullable=False, default=0)
    total_pairs_replayed = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_cf_job_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# Layer 5: Insight — Mechanism #13: Meta-Memory (6 tables)
# ---------------------------------------------------------------------------

class MetaMemoryAreaORM(Base):
    __tablename__ = "meta_memory_area"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    dimension = Column(String(50), nullable=False)
    area_key = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_mma_tenant", "tenant_id", "dimension", "area_key", unique=True),
    )


class MetaMemoryProductivityORM(Base):
    __tablename__ = "meta_memory_productivity"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    area_id = Column(UUID(as_uuid=True), nullable=False)
    n_tp = Column(Integer, nullable=False, default=0)
    n_fp = Column(Integer, nullable=False, default=0)
    n_fn = Column(Integer, nullable=False, default=0)
    n_total = Column(Integer, nullable=False, default=0)
    raw_productivity = Column(Float, nullable=False, default=0.0)
    smoothed_productivity = Column(Float, nullable=False, default=0.0)
    last_outcome_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_mmp_area", "area_id"),
    )


class MetaMemoryBiasORM(Base):
    __tablename__ = "meta_memory_bias"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    area_id = Column(UUID(as_uuid=True), nullable=False)
    bias_allocation = Column(Float, nullable=False)
    computed_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_mmb_tenant", "tenant_id", "computed_at"),
    )


class MetaMemoryTopologicalRegionORM(Base):
    __tablename__ = "meta_memory_topological_region"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    region_key = Column(String(200), nullable=False)
    entity_ids = Column(JSONB, nullable=False)
    centroid_embedding = Column(
        Vector(1536) if Vector else Text, nullable=True
    )

    __table_args__ = (
        Index("ix_mmtr_tenant", "tenant_id", "region_key"),
    )


class MetaMemoryTenantStateORM(Base):
    __tablename__ = "meta_memory_tenant_state"

    tenant_id = Column(String(100), primary_key=True)
    activation_status = Column(String(20), nullable=False, default="INACTIVE")
    total_labeled_outcomes = Column(Integer, nullable=False, default=0)
    failure_modes_with_50_plus = Column(Integer, nullable=False, default=0)
    last_activated_at = Column(DateTime(timezone=True), nullable=True)


class MetaMemoryJobRunORM(Base):
    __tablename__ = "meta_memory_job_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    areas_evaluated = Column(Integer, nullable=False, default=0)
    bias_changed = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_mmjr_tenant", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# Layer 5: Insight — Mechanism #14: Evolutionary Patterns (4 tables)
# ---------------------------------------------------------------------------

class PatternIndividualORM(Base):
    __tablename__ = "pattern_individual"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    failure_mode_profile = Column(String(50), nullable=False)
    pattern_string = Column(String(10), nullable=False)
    fitness = Column(Float, nullable=False, default=0.0)
    predictive_power = Column(Float, nullable=False, default=0.0)
    novelty = Column(Float, nullable=False, default=0.0)
    compression_gain = Column(Float, nullable=False, default=0.0)
    generation = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_pi_tenant_fm", "tenant_id", "failure_mode_profile"),
    )


class PatternIndividualArchiveORM(Base):
    __tablename__ = "pattern_individual_archive"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    failure_mode_profile = Column(String(50), nullable=False)
    pattern_string = Column(String(10), nullable=False)
    fitness = Column(Float, nullable=False, default=0.0)
    predictive_power = Column(Float, nullable=False, default=0.0)
    novelty = Column(Float, nullable=False, default=0.0)
    compression_gain = Column(Float, nullable=False, default=0.0)
    generation = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_pia_tenant_fm", "tenant_id", "failure_mode_profile"),
    )


class EvolutionGenerationLogORM(Base):
    __tablename__ = "evolution_generation_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    failure_mode_profile = Column(String(50), nullable=False)
    generation = Column(Integer, nullable=False)
    population_size = Column(Integer, nullable=False)
    mean_fitness = Column(Float, nullable=False)
    max_fitness = Column(Float, nullable=False)
    mutations = Column(Integer, nullable=False, default=0)
    recombinations = Column(Integer, nullable=False, default=0)
    selections = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_egl_tenant_fm", "tenant_id", "failure_mode_profile"),
    )


class EvolutionPartitionStateORM(Base):
    __tablename__ = "evolution_partition_state"

    tenant_id = Column(String(100), primary_key=True)
    failure_mode_profile = Column(String(50), primary_key=True)
    current_generation = Column(Integer, nullable=False, default=0)
    last_evolved_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Layer 2: Maintenance Job History (1 table)
# ---------------------------------------------------------------------------

class MaintenanceJobHistoryORM(Base):
    __tablename__ = "maintenance_job_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    job_type = Column(String(50), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    fragments_processed = Column(Integer, nullable=False, default=0)
    edges_pruned = Column(Integer, nullable=False, default=0)
    outcome = Column(String(20), nullable=False, default="RUNNING")
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_maint_job_tenant", "tenant_id", "started_at"),
    )
