"""CI guard: every ORM-mapped table (except system tables) must have tenant_id.

If this test breaks it means a new ORM model was added without a tenant_id column.
Either add the column, or add the table name to SYSTEM_TABLES_ALLOWLIST in
backend/app/core/database.py with a design-review justification.
"""

from backend.app.core.database import Base, SYSTEM_TABLES_ALLOWLIST

# Import every model module so SQLAlchemy registers them with Base.metadata.
# Add new model files here as they are created.
import backend.app.models.abeyance_orm  # noqa: F401
import backend.app.models.abeyance_v3_orm  # noqa: F401
import backend.app.models.action_execution_orm  # noqa: F401
import backend.app.models.audit_orm  # noqa: F401
import backend.app.models.bss_orm  # noqa: F401
import backend.app.models.customer_orm  # noqa: F401
import backend.app.models.decision_trace  # noqa: F401
import backend.app.models.decision_trace_orm  # noqa: F401
import backend.app.models.incident_orm  # noqa: F401
import backend.app.models.investment_planning  # noqa: F401
import backend.app.models.kpi_orm  # noqa: F401
import backend.app.models.kpi_sample_orm  # noqa: F401
import backend.app.models.network_entity_orm  # noqa: F401
import backend.app.models.policy_orm  # noqa: F401
import backend.app.models.reconciliation_result_orm  # noqa: F401
import backend.app.models.tenant_orm  # noqa: F401
import backend.app.models.tmf628_models  # noqa: F401
import backend.app.models.tmf642_models  # noqa: F401
import backend.app.models.topology_models  # noqa: F401
import backend.app.models.user_orm  # noqa: F401
import backend.app.models.user_tenant_access_orm  # noqa: F401


def test_all_tables_have_tenant_id() -> None:
    """Assert that every mapped table outside the allowlist has a non-nullable tenant_id."""
    missing: list[str] = []
    nullable: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name in SYSTEM_TABLES_ALLOWLIST:
            continue
        col_names = {col.name for col in table.columns}
        if "tenant_id" not in col_names:
            missing.append(table_name)
            continue
        tenant_col = table.columns["tenant_id"]
        if tenant_col.nullable is not False:
            nullable.append(table_name)

    errors: list[str] = []
    if missing:
        errors.append(
            "Tables missing tenant_id:\n"
            + "\n".join(f"  - {t}" for t in sorted(missing))
        )
    if nullable:
        errors.append(
            "Tables with nullable tenant_id (must be nullable=False):\n"
            + "\n".join(f"  - {t}" for t in sorted(nullable))
        )
    assert not errors, (
        "\n\n".join(errors)
        + "\n\nAdd 'tenant_id = Column(String(100), nullable=False, index=True)' to each "
        "model, or add the table to SYSTEM_TABLES_ALLOWLIST in backend/app/core/database.py."
    )


def test_tenant_id_column_width_is_100() -> None:
    """Assert that every tenant_id column uses String(100) to match TenantORM.id."""
    wrong_width: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name in SYSTEM_TABLES_ALLOWLIST:
            continue
        if "tenant_id" not in {col.name for col in table.columns}:
            continue
        col = table.columns["tenant_id"]
        # Check the length attribute of the String type
        if hasattr(col.type, "length") and col.type.length != 100:
            wrong_width.append(f"{table_name}: String({col.type.length})")

    assert not wrong_width, (
        "Tables with non-100 tenant_id width:\n"
        + "\n".join(f"  - {t}" for t in sorted(wrong_width))
        + "\n\nAll tenant_id columns must be String(100) to match TenantORM.id."
    )


# Answer tables that must NEVER exist in the ORM metadata — Pedkai operates blindly.
_ANSWER_TABLES = frozenset({
    "gt_network_entities",
    "gt_entity_relationships",
    "divergence_manifest",
    "scenario_manifest",
    "scenario_kpi_overrides",
})


def test_no_answer_tables_in_orm() -> None:
    """Assert that ground-truth / scenario answer tables are excluded from ORM metadata.

    Pedkai must not have access to the 'answers' from the synthetic data generator.
    Evaluation is done externally by comparing Pedkai's findings against Parquet files.
    """
    present = _ANSWER_TABLES & set(Base.metadata.tables.keys())
    assert not present, (
        "Answer tables found in ORM metadata (must be excluded):\n"
        + "\n".join(f"  - {t}" for t in sorted(present))
        + "\n\nPedkai must operate blindly. Remove the ORM model for these tables."
    )
