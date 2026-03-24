"""
Canonical Kafka topic definitions for telemetry ingestion.

Domain-segmented topics designed for production telemetry streams.
The replay service and future live sources both produce to these same topics.

Topic naming: telemetry.<domain>.<stream_type>
"""


class TelemetryTopics:
    """
    Kafka topic registry for telemetry streams.

    Each topic corresponds to a network domain.  Downstream consumers
    bind to these topics — they never change regardless of whether the
    source is Parquet replay or a live network feed.
    """

    # Mobile RAN — cell-level radio KPIs (LTE, NR-SA, NR-NSA)
    RAN_KPI = "telemetry.ran.kpi"

    # Transport network — switches, routers, microwave, optical
    TRANSPORT_KPI = "telemetry.transport.kpi"

    # Fixed broadband — OLT, PON, ONT, DSL
    FIXED_BROADBAND_KPI = "telemetry.fixed_broadband.kpi"

    # Core network elements — AMF, SMF, UPF, MME, PGW, IMS, etc.
    CORE_KPI = "telemetry.core.kpi"

    # Enterprise circuits — Ethernet, VPN, SLA metrics
    ENTERPRISE_KPI = "telemetry.enterprise.kpi"

    # Power & environment — site-level power, battery, temperature
    POWER_KPI = "telemetry.power.kpi"

    # Alarm events — cross-domain (radio, transport, core, power, etc.)
    ALARMS = "telemetry.alarms"

    @classmethod
    def all_kpi_topics(cls) -> list[str]:
        """All KPI telemetry topics (excludes alarms)."""
        return [
            cls.RAN_KPI,
            cls.TRANSPORT_KPI,
            cls.FIXED_BROADBAND_KPI,
            cls.CORE_KPI,
            cls.ENTERPRISE_KPI,
            cls.POWER_KPI,
        ]

    @classmethod
    def all_topics(cls) -> list[str]:
        """All telemetry topics including alarms."""
        return cls.all_kpi_topics() + [cls.ALARMS]


# Mapping from Parquet filename stem → Kafka topic
PARQUET_TO_TOPIC: dict[str, str] = {
    "kpi_metrics_wide": TelemetryTopics.RAN_KPI,
    "transport_kpis_wide": TelemetryTopics.TRANSPORT_KPI,
    "fixed_broadband_kpis_wide": TelemetryTopics.FIXED_BROADBAND_KPI,
    "core_element_kpis_wide": TelemetryTopics.CORE_KPI,
    "enterprise_circuit_kpis_wide": TelemetryTopics.ENTERPRISE_KPI,
    "power_environment_kpis": TelemetryTopics.POWER_KPI,
    "events_alarms": TelemetryTopics.ALARMS,
}

# Mapping from topic → entity ID column name in the Parquet data
TOPIC_ENTITY_ID_COLUMN: dict[str, str] = {
    TelemetryTopics.RAN_KPI: "cell_id",
    TelemetryTopics.TRANSPORT_KPI: "entity_id",
    TelemetryTopics.FIXED_BROADBAND_KPI: "entity_id",
    TelemetryTopics.CORE_KPI: "entity_id",
    TelemetryTopics.ENTERPRISE_KPI: "entity_id",
    TelemetryTopics.POWER_KPI: "site_id",
    TelemetryTopics.ALARMS: "entity_id",
}

# Mapping from topic → timestamp column name
TOPIC_TIMESTAMP_COLUMN: dict[str, str] = {
    TelemetryTopics.RAN_KPI: "timestamp",
    TelemetryTopics.TRANSPORT_KPI: "timestamp",
    TelemetryTopics.FIXED_BROADBAND_KPI: "timestamp",
    TelemetryTopics.CORE_KPI: "timestamp",
    TelemetryTopics.ENTERPRISE_KPI: "timestamp",
    TelemetryTopics.POWER_KPI: "timestamp",
    TelemetryTopics.ALARMS: "raised_at",
}
