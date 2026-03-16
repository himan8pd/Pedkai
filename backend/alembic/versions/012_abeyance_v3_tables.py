"""Abeyance Memory v3.0 tables and columns

Revision ID: 012_abeyance_v3_tables
Revises: 011_abeyance_provenance_tables
Create Date: 2026-03-16 15:00:00.000000

Adds:
- 44 new tables for discovery mechanisms (Layers 2-5)
- v3 four-column embedding columns on abeyance_fragment
- v3 per-dimension score columns on snap_decision_record
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '012_abeyance_v3_tables'
down_revision: Union[str, Sequence[str], None] = '011_abeyance_provenance_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- v3 columns on abeyance_fragment -----------------------------------
    for col, typ in [
        ("emb_semantic", "vector(1536)"),
        ("emb_topological", "vector(1536)"),
        ("emb_temporal", "vector(256)"),
        ("emb_operational", "vector(1536)"),
    ]:
        op.execute(f"""
            ALTER TABLE abeyance_fragment
            ADD COLUMN IF NOT EXISTS {col} {typ}
        """)

    for col, default in [
        ("mask_semantic", "FALSE"),
        ("mask_topological", "FALSE"),
        ("mask_operational", "FALSE"),
    ]:
        op.execute(f"""
            ALTER TABLE abeyance_fragment
            ADD COLUMN IF NOT EXISTS {col} BOOLEAN NOT NULL DEFAULT {default}
        """)

    op.execute("""
        ALTER TABLE abeyance_fragment
        ADD COLUMN IF NOT EXISTS polarity VARCHAR(10)
    """)
    op.execute("""
        ALTER TABLE abeyance_fragment
        ADD COLUMN IF NOT EXISTS embedding_schema_version INTEGER NOT NULL DEFAULT 3
    """)

    # CHECK constraints for mask/embedding coherence (INV-13)
    for dim in ("semantic", "topological", "operational"):
        op.execute(f"""
            DO $$ BEGIN
                ALTER TABLE abeyance_fragment
                ADD CONSTRAINT ck_frag_mask_{dim}
                CHECK (emb_{dim} IS NOT NULL OR mask_{dim} = FALSE);
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """)

    # -- v3 columns on snap_decision_record --------------------------------
    for col in ("score_semantic", "score_topological", "score_temporal", "score_operational"):
        op.execute(f"""
            ALTER TABLE snap_decision_record
            ADD COLUMN IF NOT EXISTS {col} FLOAT
        """)
    op.execute("""
        ALTER TABLE snap_decision_record
        ADD COLUMN IF NOT EXISTS score_entity_overlap FLOAT NOT NULL DEFAULT 0.0
    """)
    op.execute("""
        ALTER TABLE snap_decision_record
        ADD COLUMN IF NOT EXISTS masks_active JSONB NOT NULL DEFAULT '{}'::jsonb
    """)
    op.execute("""
        ALTER TABLE snap_decision_record
        ADD COLUMN IF NOT EXISTS weights_base JSONB
    """)

    # -- Layer 2: Surprise Engine ------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS surprise_event (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            snap_decision_record_id UUID NOT NULL,
            failure_mode_profile    VARCHAR(50) NOT NULL,
            surprise_value          FLOAT NOT NULL,
            threshold_at_time       FLOAT NOT NULL,
            escalation_type         VARCHAR(30) NOT NULL,
            dimensions_contributing JSONB NOT NULL,
            bin_index               INTEGER NOT NULL,
            bin_probability         FLOAT NOT NULL,
            created_at              TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_surprise_event_tenant ON surprise_event (tenant_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_surprise_event_sdr ON surprise_event (snap_decision_record_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS surprise_distribution_state (
            tenant_id                       VARCHAR(100) NOT NULL,
            failure_mode_profile            VARCHAR(50) NOT NULL,
            histogram_bins                  JSONB NOT NULL,
            observation_count               FLOAT NOT NULL DEFAULT 0.0,
            threshold_value                 FLOAT NOT NULL DEFAULT 6.64,
            threshold_monotonic_decrease_count INTEGER NOT NULL DEFAULT 0,
            last_updated_at                 TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (tenant_id, failure_mode_profile)
        )
    """)

    # -- Layer 2: Ignorance Mapping ----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS ignorance_extraction_stat (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            source_type     VARCHAR(50) NOT NULL,
            entity_domain   VARCHAR(50),
            extraction_method VARCHAR(20) NOT NULL,
            success_count   INTEGER NOT NULL DEFAULT 0,
            total_count     INTEGER NOT NULL DEFAULT 0,
            success_rate    FLOAT NOT NULL DEFAULT 0.0,
            period_start    TIMESTAMP WITH TIME ZONE NOT NULL,
            period_end      TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ign_ext_tenant ON ignorance_extraction_stat (tenant_id, period_start)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ignorance_mask_distribution (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            mask_pattern        VARCHAR(10) NOT NULL,
            fragment_count      INTEGER NOT NULL DEFAULT 0,
            fraction            FLOAT NOT NULL DEFAULT 0.0,
            period_start        TIMESTAMP WITH TIME ZONE NOT NULL,
            period_end          TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ign_mask_tenant ON ignorance_mask_distribution (tenant_id, period_start)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ignorance_silent_decay_record (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            fragment_id     UUID NOT NULL,
            source_type     VARCHAR(50),
            entity_count    INTEGER NOT NULL DEFAULT 0,
            mask_pattern    VARCHAR(10),
            max_snap_score  FLOAT,
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ign_silent_tenant ON ignorance_silent_decay_record (tenant_id, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ignorance_silent_decay_stat (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            source_type     VARCHAR(50),
            silent_count    INTEGER NOT NULL DEFAULT 0,
            total_expired   INTEGER NOT NULL DEFAULT 0,
            silent_rate     FLOAT NOT NULL DEFAULT 0.0,
            period_start    TIMESTAMP WITH TIME ZONE NOT NULL,
            period_end      TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ign_silent_stat_tenant ON ignorance_silent_decay_stat (tenant_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ignorance_map_entry (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            entity_domain   VARCHAR(50) NOT NULL,
            metric_type     VARCHAR(50) NOT NULL,
            ignorance_score FLOAT NOT NULL,
            detail          JSONB,
            computed_at     TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ign_map_tenant ON ignorance_map_entry (tenant_id, entity_domain)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS exploration_directive (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            entity_domain   VARCHAR(50) NOT NULL,
            directive_type  VARCHAR(50) NOT NULL,
            priority        FLOAT NOT NULL DEFAULT 0.0,
            rationale       TEXT,
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            consumed_at     TIMESTAMP WITH TIME ZONE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_expl_dir_tenant ON exploration_directive (tenant_id, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ignorance_job_run (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            started_at          TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at        TIMESTAMP WITH TIME ZONE,
            fragments_scanned   INTEGER NOT NULL DEFAULT 0,
            silent_decays_found INTEGER NOT NULL DEFAULT 0,
            directives_generated INTEGER NOT NULL DEFAULT 0,
            outcome             VARCHAR(20) NOT NULL DEFAULT 'RUNNING'
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ign_job_tenant ON ignorance_job_run (tenant_id, started_at)")

    # -- Layer 2: Negative Evidence ----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS disconfirmation_events (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            initiated_by        VARCHAR(255) NOT NULL,
            reason              TEXT,
            pathway             VARCHAR(20) NOT NULL,
            acceleration_factor FLOAT NOT NULL DEFAULT 5.0,
            fragment_count      INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_disconf_event_tenant ON disconfirmation_events (tenant_id, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS disconfirmation_fragments (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            disconfirmation_event_id UUID NOT NULL,
            fragment_id             UUID NOT NULL,
            pre_decay_score         FLOAT NOT NULL,
            post_decay_score        FLOAT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_disconf_frag_event ON disconfirmation_fragments (disconfirmation_event_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS disconfirmation_patterns (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   VARCHAR(100) NOT NULL,
            disconfirmation_event_id    UUID NOT NULL,
            centroid_embedding_semantic vector(1536),
            centroid_embedding_topological vector(1536),
            centroid_embedding_operational vector(1536),
            pattern_weight              FLOAT NOT NULL DEFAULT 1.0,
            fragments_in_centroid       INTEGER NOT NULL DEFAULT 0,
            created_at                  TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            expires_at                  TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_disconf_pattern_tenant ON disconfirmation_patterns (tenant_id, expires_at)")

    # -- Layer 2: Bridge Detection -----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS bridge_discovery (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            fragment_id             UUID NOT NULL,
            betweenness_centrality  FLOAT NOT NULL,
            domain_span             INTEGER NOT NULL,
            severity                VARCHAR(20) NOT NULL,
            component_fingerprint   VARCHAR(64) NOT NULL,
            created_at              TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT uq_bridge_fingerprint UNIQUE (tenant_id, component_fingerprint)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bridge_tenant ON bridge_discovery (tenant_id, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS bridge_discovery_provenance (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            bridge_discovery_id         UUID NOT NULL,
            sub_component_fragment_ids  JSONB NOT NULL,
            relationship_type           VARCHAR(50)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bridge_prov_disc ON bridge_discovery_provenance (bridge_discovery_id)")

    # -- Layer 2: Outcome Calibration --------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS snap_outcome_feedback (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            snap_decision_record_id UUID NOT NULL,
            operator_verdict        VARCHAR(20) NOT NULL,
            resolution_action       VARCHAR(100),
            resolved_at             TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            notes                   TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_snap_feedback_tenant ON snap_outcome_feedback (tenant_id, resolved_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS calibration_history (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            weights_before      JSONB NOT NULL,
            weights_after       JSONB NOT NULL,
            auc_before          FLOAT,
            auc_after           FLOAT,
            sample_count        INTEGER NOT NULL,
            calibrated_at       TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cal_hist_tenant ON calibration_history (tenant_id, calibrated_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS weight_profile_active (
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            weights             JSONB NOT NULL,
            calibration_status  VARCHAR(30) NOT NULL DEFAULT 'INITIAL_ESTIMATE',
            last_calibrated_at  TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (tenant_id, failure_mode_profile)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_wpa_tenant ON weight_profile_active (tenant_id)")

    # -- Layer 2: Pattern Conflict -----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS conflict_record (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            decision_id_a       UUID NOT NULL,
            decision_id_b       UUID NOT NULL,
            entity_overlap_ratio FLOAT NOT NULL,
            polarity_a          VARCHAR(10) NOT NULL,
            polarity_b          VARCHAR(10) NOT NULL,
            detected_at         TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_conflict_tenant ON conflict_record (tenant_id, detected_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS conflict_detection_log (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            scan_type           VARCHAR(20) NOT NULL,
            decisions_scanned   INTEGER NOT NULL DEFAULT 0,
            conflicts_found     INTEGER NOT NULL DEFAULT 0,
            duration_ms         INTEGER NOT NULL DEFAULT 0,
            completed_at        TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_conflict_log_tenant ON conflict_detection_log (tenant_id, completed_at)")

    # -- Layer 2: Temporal Sequence ----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS entity_sequence_log (
            id              BIGSERIAL PRIMARY KEY,
            tenant_id       VARCHAR(100) NOT NULL,
            entity_id       UUID NOT NULL,
            entity_domain   VARCHAR(50),
            from_state      VARCHAR(100),
            to_state        VARCHAR(100) NOT NULL,
            fragment_id     UUID NOT NULL,
            event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_esl_tenant_entity ON entity_sequence_log (tenant_id, entity_id, event_timestamp)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS transition_matrix (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            entity_domain   VARCHAR(50) NOT NULL,
            from_state      VARCHAR(100) NOT NULL,
            to_state        VARCHAR(100) NOT NULL,
            count           INTEGER NOT NULL DEFAULT 0,
            last_observed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_tm_tenant_domain ON transition_matrix (tenant_id, entity_domain, from_state, to_state)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS transition_matrix_version (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            entity_domain           VARCHAR(50) NOT NULL,
            recompute_started_at    TIMESTAMP WITH TIME ZONE NOT NULL,
            recompute_completed_at  TIMESTAMP WITH TIME ZONE,
            total_transitions       INTEGER NOT NULL DEFAULT 0,
            unique_states           INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tmv_tenant ON transition_matrix_version (tenant_id, entity_domain)")

    # -- Layer 3: Hypothesis -----------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS hypothesis (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            statement       TEXT NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'PROPOSED',
            confidence      FLOAT,
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            expires_at      TIMESTAMP WITH TIME ZONE NOT NULL,
            confirmed_at    TIMESTAMP WITH TIME ZONE,
            refuted_at      TIMESTAMP WITH TIME ZONE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hyp_tenant_status ON hypothesis (tenant_id, status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS hypothesis_evidence (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            hypothesis_id   UUID NOT NULL,
            source_table    VARCHAR(100) NOT NULL,
            source_id       UUID NOT NULL,
            evidence_type   VARCHAR(50) NOT NULL,
            contribution    FLOAT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hyp_ev_hyp ON hypothesis_evidence (hypothesis_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS hypothesis_generation_queue (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            trigger_type    VARCHAR(50) NOT NULL,
            trigger_id      UUID NOT NULL,
            raw_context     JSONB,
            status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            attempt_count   INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_hyp_queue_tenant ON hypothesis_generation_queue (tenant_id, status)")

    # -- Layer 3: Expectation Violation ------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS expectation_violation (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   VARCHAR(100) NOT NULL,
            entity_id                   UUID NOT NULL,
            entity_domain               VARCHAR(50),
            from_state                  VARCHAR(100) NOT NULL,
            to_state                    VARCHAR(100) NOT NULL,
            violation_severity          FLOAT NOT NULL,
            threshold_applied           FLOAT NOT NULL,
            violation_class             VARCHAR(20) NOT NULL,
            correlated_surprise_event_id UUID,
            fragment_id                 UUID NOT NULL,
            created_at                  TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ev_tenant ON expectation_violation (tenant_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ev_entity ON expectation_violation (tenant_id, entity_id)")

    # -- Layer 3: Causal Direction -----------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS causal_candidate (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            entity_a_id         UUID NOT NULL,
            entity_b_id         UUID NOT NULL,
            direction           VARCHAR(10) NOT NULL,
            directional_fraction FLOAT NOT NULL,
            confidence          FLOAT NOT NULL,
            sample_count        INTEGER NOT NULL,
            created_at          TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at          TIMESTAMP WITH TIME ZONE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_causal_tenant ON causal_candidate (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_causal_entities ON causal_candidate (tenant_id, entity_a_id, entity_b_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS causal_evidence_pair (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            causal_candidate_id UUID NOT NULL,
            fragment_a_id       UUID NOT NULL,
            fragment_b_id       UUID NOT NULL,
            time_delta_seconds  FLOAT NOT NULL,
            direction           VARCHAR(10) NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_causal_ev_cand ON causal_evidence_pair (causal_candidate_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS causal_analysis_run (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            started_at          TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at        TIMESTAMP WITH TIME ZONE,
            candidates_evaluated INTEGER NOT NULL DEFAULT 0,
            candidates_promoted INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_causal_run_tenant ON causal_analysis_run (tenant_id)")

    # -- Layer 4: Pattern Compression --------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS compression_discovery_event (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            rules               JSONB NOT NULL,
            compression_gain    FLOAT NOT NULL,
            coverage_ratio      FLOAT NOT NULL,
            dominant_rule       VARCHAR(20),
            population_size     INTEGER NOT NULL,
            created_at          TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_comp_disc_tenant ON compression_discovery_event (tenant_id, created_at)")

    # -- Layer 4: Counterfactual Simulation --------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS counterfactual_simulation_result (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               VARCHAR(100) NOT NULL,
            candidate_fragment_id   UUID NOT NULL,
            causal_impact_score     FLOAT NOT NULL,
            decision_flip_count     INTEGER NOT NULL DEFAULT 0,
            decision_flip_rate      FLOAT NOT NULL DEFAULT 0.0,
            pairs_evaluated         INTEGER NOT NULL DEFAULT 0,
            created_at              TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cf_result_tenant ON counterfactual_simulation_result (tenant_id, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS counterfactual_pair_delta (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            simulation_result_id    UUID NOT NULL,
            original_score          FLOAT NOT NULL,
            counterfactual_score    FLOAT NOT NULL,
            delta                   FLOAT NOT NULL,
            decision_changed        BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cf_delta_result ON counterfactual_pair_delta (simulation_result_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS counterfactual_candidate_queue (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            fragment_id     UUID NOT NULL,
            priority_score  FLOAT NOT NULL DEFAULT 0.0,
            status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cf_queue_tenant ON counterfactual_candidate_queue (tenant_id, status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS counterfactual_job_run (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            started_at          TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at        TIMESTAMP WITH TIME ZONE,
            candidates_processed INTEGER NOT NULL DEFAULT 0,
            total_pairs_replayed INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_cf_job_tenant ON counterfactual_job_run (tenant_id)")

    # -- Layer 5: Meta-Memory ----------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_memory_area (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            dimension       VARCHAR(50) NOT NULL,
            area_key        VARCHAR(200) NOT NULL,
            description     TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_mma_tenant ON meta_memory_area (tenant_id, dimension, area_key)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_memory_productivity (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            area_id             UUID NOT NULL,
            n_tp                INTEGER NOT NULL DEFAULT 0,
            n_fp                INTEGER NOT NULL DEFAULT 0,
            n_fn                INTEGER NOT NULL DEFAULT 0,
            n_total             INTEGER NOT NULL DEFAULT 0,
            raw_productivity    FLOAT NOT NULL DEFAULT 0.0,
            smoothed_productivity FLOAT NOT NULL DEFAULT 0.0,
            last_outcome_at     TIMESTAMP WITH TIME ZONE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mmp_area ON meta_memory_productivity (area_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_memory_bias (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            area_id         UUID NOT NULL,
            bias_allocation FLOAT NOT NULL,
            computed_at     TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mmb_tenant ON meta_memory_bias (tenant_id, computed_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_memory_topological_region (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            region_key          VARCHAR(200) NOT NULL,
            entity_ids          JSONB NOT NULL,
            centroid_embedding  vector(1536)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mmtr_tenant ON meta_memory_topological_region (tenant_id, region_key)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_memory_tenant_state (
            tenant_id                   VARCHAR(100) PRIMARY KEY,
            activation_status           VARCHAR(20) NOT NULL DEFAULT 'INACTIVE',
            total_labeled_outcomes      INTEGER NOT NULL DEFAULT 0,
            failure_modes_with_50_plus  INTEGER NOT NULL DEFAULT 0,
            last_activated_at           TIMESTAMP WITH TIME ZONE
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS meta_memory_job_run (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       VARCHAR(100) NOT NULL,
            started_at      TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at    TIMESTAMP WITH TIME ZONE,
            areas_evaluated INTEGER NOT NULL DEFAULT 0,
            bias_changed    BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mmjr_tenant ON meta_memory_job_run (tenant_id)")

    # -- Layer 5: Evolutionary Patterns ------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS pattern_individual (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            pattern_string      VARCHAR(10) NOT NULL,
            fitness             FLOAT NOT NULL DEFAULT 0.0,
            predictive_power    FLOAT NOT NULL DEFAULT 0.0,
            novelty             FLOAT NOT NULL DEFAULT 0.0,
            compression_gain    FLOAT NOT NULL DEFAULT 0.0,
            generation          INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pi_tenant_fm ON pattern_individual (tenant_id, failure_mode_profile)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS pattern_individual_archive (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            pattern_string      VARCHAR(10) NOT NULL,
            fitness             FLOAT NOT NULL DEFAULT 0.0,
            predictive_power    FLOAT NOT NULL DEFAULT 0.0,
            novelty             FLOAT NOT NULL DEFAULT 0.0,
            compression_gain    FLOAT NOT NULL DEFAULT 0.0,
            generation          INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pia_tenant_fm ON pattern_individual_archive (tenant_id, failure_mode_profile)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS evolution_generation_log (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            generation          INTEGER NOT NULL,
            population_size     INTEGER NOT NULL,
            mean_fitness        FLOAT NOT NULL,
            max_fitness         FLOAT NOT NULL,
            mutations           INTEGER NOT NULL DEFAULT 0,
            recombinations      INTEGER NOT NULL DEFAULT 0,
            selections          INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_egl_tenant_fm ON evolution_generation_log (tenant_id, failure_mode_profile)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS evolution_partition_state (
            tenant_id           VARCHAR(100) NOT NULL,
            failure_mode_profile VARCHAR(50) NOT NULL,
            current_generation  INTEGER NOT NULL DEFAULT 0,
            last_evolved_at     TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (tenant_id, failure_mode_profile)
        )
    """)

    # -- Maintenance Job History -------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_job_history (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           VARCHAR(100) NOT NULL,
            job_type            VARCHAR(50) NOT NULL,
            started_at          TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at        TIMESTAMP WITH TIME ZONE,
            fragments_processed INTEGER NOT NULL DEFAULT 0,
            edges_pruned        INTEGER NOT NULL DEFAULT 0,
            outcome             VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
            error_message       TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_maint_job_tenant ON maintenance_job_history (tenant_id, started_at)")


def downgrade() -> None:
    tables = [
        "maintenance_job_history",
        "evolution_partition_state", "evolution_generation_log",
        "pattern_individual_archive", "pattern_individual",
        "meta_memory_job_run", "meta_memory_tenant_state",
        "meta_memory_topological_region", "meta_memory_bias",
        "meta_memory_productivity", "meta_memory_area",
        "counterfactual_job_run", "counterfactual_candidate_queue",
        "counterfactual_pair_delta", "counterfactual_simulation_result",
        "compression_discovery_event",
        "causal_analysis_run", "causal_evidence_pair", "causal_candidate",
        "expectation_violation",
        "hypothesis_generation_queue", "hypothesis_evidence", "hypothesis",
        "transition_matrix_version", "transition_matrix", "entity_sequence_log",
        "conflict_detection_log", "conflict_record",
        "weight_profile_active", "calibration_history", "snap_outcome_feedback",
        "bridge_discovery_provenance", "bridge_discovery",
        "disconfirmation_patterns", "disconfirmation_fragments", "disconfirmation_events",
        "ignorance_job_run", "exploration_directive", "ignorance_map_entry",
        "ignorance_silent_decay_stat", "ignorance_silent_decay_record",
        "ignorance_mask_distribution", "ignorance_extraction_stat",
        "surprise_distribution_state", "surprise_event",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    # Remove v3 columns from snap_decision_record
    for col in ("score_semantic", "score_topological", "score_temporal",
                "score_operational", "score_entity_overlap", "masks_active", "weights_base"):
        op.execute(f"ALTER TABLE snap_decision_record DROP COLUMN IF EXISTS {col}")

    # Remove v3 columns from abeyance_fragment
    for dim in ("semantic", "topological", "operational"):
        op.execute(f"""
            ALTER TABLE abeyance_fragment DROP CONSTRAINT IF EXISTS ck_frag_mask_{dim}
        """)
    for col in ("emb_semantic", "emb_topological", "emb_temporal", "emb_operational",
                "mask_semantic", "mask_topological", "mask_operational",
                "polarity", "embedding_schema_version"):
        op.execute(f"ALTER TABLE abeyance_fragment DROP COLUMN IF EXISTS {col}")
