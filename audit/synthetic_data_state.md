# Synthetic Data Generator Audit Report
**Task**: TASK-006: Audit synthetic data generator current state
**Date**: 2026-03-10
**Repository**: Sleeping-Cell-KPI-Data (separate from Pedkai core)

---

## Executive Summary

The synthetic data generator is a **mature, multi-stage pipeline** with 11 sequential steps that produces a complete telco dataset including:
- Network topology (CMDB entities & relationships)
- Cell inventory with realistic physics-based KPI time-series
- Scenario injection (sleeping cells, faults, cascades)
- CMDB degradation (dark/phantom nodes & edges)
- Ground truth and declared-state split for Dark Graph reconciliation

**Location**: `/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/src/pedkai_generator/`

---

## File Organization

### Generator Structure (11 Steps)

| Step | Module | Purpose |
|------|--------|---------|
| **00** | `step_00_schema/` | Schema contracts & field definitions |
| **01** | `step_01_sites/` | Site inventory generation (21.1K sites, 64.7K cells) |
| **02** | `step_02_topology/` | CMDB entity & relationship builder (mobile RAN, transport, power, fixed BB) |
| **03** | `step_03_radio_kpis/` | Radio layer KPI physics model & streaming AR(1) generator |
| **04** | `step_04_domain_kpis/` | Domain-specific KPIs (transport, power, fixed broadband) |
| **05** | `step_05_scenarios/` | Fault/degradation scenario injection (8 types) |
| **06** | `step_06_events/` | Event/alarm generation (correlate with scenarios) |
| **07** | `step_07_customers/` | Customer/BSS data generation (1M subscribers) |
| **08** | `step_08_cmdb_degradation/` | Dark graph injection (dark/phantom nodes & edges) |
| **09** | `step_09_vendor_naming/` | Vendor ID mapping (Ericsson/Nokia split) |
| **10** | `step_10_validation/` | Validation & QA gates |
| **11** | `step_11_loader/` | PostgreSQL + TimescaleDB ingestion |

### Key Files

```
/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/
├── src/pedkai_generator/
│   ├── cli.py                          # CLI entry point (16 KB)
│   ├── config/settings.py              # Generator configuration schema
│   ├── step_01_sites/generate.py       # [UUID4 generation here]
│   ├── step_03_radio_kpis/
│   │   ├── generate.py                 # [AR(1) streaming KPI orchestrator]
│   │   ├── physics.py                  # Physics chain (SINR → CQI → MCS)
│   │   └── profiles.py                 # [AR(1) streaming environment generator]
│   ├── step_05_scenarios/generate.py   # [Scenario injection engine]
│   ├── step_08_cmdb_degradation/generate.py  # [Dark graph degradation]
│   └── utils/
├── Pedkai Synthetic Data Generator.md  # Comprehensive documentation (383 KB)
├── TELCO2_FINAL_ASSESSMENT.md
├── README.md
└── pyproject.toml
```

---

## 1. Entity Identifier Generation (UUID4)

**Responsible Function**: `uuid.uuid4()` used throughout

### File: `/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/src/pedkai_generator/step_01_sites/generate.py`

**Lines 282, 454, 489, 521, 554**:
```python
import uuid

# Line 282: Site-level UUID generation
site_id = str(uuid.uuid4())

# Lines 454, 489, 521, 554: Cell-level UUID generation
cell_id = str(uuid.uuid4())
lte_anchor_id = str(uuid.uuid4())
nr_scg_id = str(uuid.uuid4())
```

**Context**:
- Standard `uuid.uuid4()` from Python standard library
- Each physical site gets a unique UUID
- Each cell (logical layer) gets a unique UUID
- Anchor cells for LTE/NR multi-layer scenarios get separate UUIDs
- UUIDs are converted to strings for Parquet serialization

**Output**: `intermediate/sites.parquet` + `intermediate/cells.parquet`

---

## 2. KPI Time-Series Generation (AR(1) Autoregressive)

**Responsible Modules**:
- **Orchestrator**: `/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/src/pedkai_generator/step_03_radio_kpis/generate.py`
- **AR(1) Implementation**: `/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/src/pedkai_generator/step_03_radio_kpis/profiles.py`

### Architecture: Streaming AR(1) State Machine

**File**: `step_03_radio_kpis/profiles.py` (lines 623-868)

```python
# AR(1) state vector class
class _AR1State:
    """Mutable state for an AR(1) process: x[t] = rho * x[t-1] + innovation"""

    def __init__(self, n_cells: int, rho: float, sigma: float, seed: int):
        self.state = np.random.normal(0, sigma, n_cells)  # Initial state
        self.rho = rho  # Autocorrelation coefficient
        self.sigma = sigma  # Innovation std dev
        self.rng = np.random.RandomState(seed)

# Streaming generator class
class StreamingEnvironmentGenerator:
    """
    Maintains compact AR(1) state vectors of shape (n_cells,) and yields
    one hour's worth of environmental conditions at a time.
    """

    def __init__(self, n_cells: int, deploy_profiles: dict, ...):
        # Initialize two AR(1) processes:
        # 1. Load jitter AR(1): low autocorrelation (rho ≈ 0.3-0.5)
        self._jitter_state = _AR1State(n_cells, rho=0.4, sigma=0.08, seed=...)

        # 2. Shadow fading AR(1): high autocorrelation (rho ≈ 0.85-0.95)
        self._shadow_state = _AR1State(n_cells, rho=0.90, sigma=2.5, seed=...)

    def next_hour(self) -> HourlyConditions:
        """Advances AR(1) states and returns hourly environment"""
        # Shadow fading update: x[t] = 0.90 * x[t-1] + epsilon
        self._shadow_state.step()

        # Jitter update: x[t] = 0.4 * x[t-1] + epsilon
        self._jitter_state.step()

        # Combine with traffic profile + timezone offset
        return HourlyConditions(load_factor, shadow_fading, jitter)
```

### KPI Generation Pipeline

**File**: `step_03_radio_kpis/generate.py`

**Lines 5-50 (Architecture Description)**:
```
Streaming AR(1) generator maintains only (n_cells,) state vectors (~500 KB each).
Each hour produces ~2 MB of environmental conditions, physics engine produces
~4 MB of KPIs, flushed as Parquet row group (~30 MB).

Peak memory ≈ 150-200 MB (vs ~4 GB in bulk approach)
```

**Physics Chain** (vectorized):
1. **AR(1) Environmental**: Load jitter + shadow fading
2. **Traffic Profile**: Diurnal curves per deployment profile + timezone
3. **Interference Calculation**: Neighbor cell load → SINR degradation
4. **SINR → CQI → MCS → Throughput**: Physical layer chain
5. **KPI Output**: 44 columns (RSRP, RSRQ, SINR, CQI, MCS, throughput, PRB util, etc.)

### Output Schema

**File**: `intermediate/kpi_metrics_wide.parquet`
- **Rows**: ~47.6M (66,131 cells × 720 hours)
- **Columns**: 44 KPI metrics
- **Size**: ~3 GB (Zstandard level 9 compression)
- **Temporal Resolution**: 1 hour intervals, 30 days (2024-01-01 to 2024-01-30)

**Realism Enhancements** (per RED_FLAG_REPORT remediation):
- **RF-04**: Stochastic null injection (~0.15% per KPI) simulating ROP failures
- **RF-05**: PM collection gaps (~0.08% of cell-hours dropped) simulating maintenance windows
- **RF-15**: Rural traffic outliers (~0.1%) for festivals/transit cells

---

## 3. Fault/Scenario Injection

**Responsible Module**: `/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/src/pedkai_generator/step_05_scenarios/generate.py`

### 8 Scenario Types

| Type | Rate | Impact | Severity |
|------|------|--------|----------|
| **Sleeping Cell** | 2.0% | Subtle traffic/throughput degradation, no alarm | low-medium |
| **Congestion** | 5.0% | PRB >85%, throughput collapse | medium-high |
| **Coverage Hole** | 1.0% | RSRP/RSRQ spatial cluster degradation | medium |
| **Hardware Fault** | 0.5% | Availability drop, BLER spike, abrupt | critical |
| **Interference** | 3.0% | IoT elevation, CQI/MCS degradation | medium |
| **Transport Failure** | 0.2% | Backhaul link down, cascade to served cells | critical |
| **Power Failure** | 0.1% | Site-level, all co-located equipment | critical |
| **Fibre Cut** | 0.05% | Cross-domain cascade (RAN + fixed BB) | critical |

### Overlay Architecture

**File**: `step_05_scenarios/generate.py` (lines 1-132)

```python
# Output files (overlay strategy — baseline never mutated):
- output/scenario_manifest.parquet          # Master schedule of injected scenarios
- output/scenario_kpi_overrides.parquet     # Sparse override table

# Consumer application logic:
effective_value = COALESCE(override, baseline)
```

**Key Functions**:
- Deterministic seeding from `config.global_seed`
- Graph-walk cross-domain cascades (infra failures cascade to cells)
- Ramp-up/ramp-down phases (realistic degradation curves)
- Scenario-specific parameters (JSON in manifest)

### Output Schemas

**scenario_manifest.parquet**:
```
scenario_id (UUID)
scenario_type (string: sleeping_cell, congestion, etc.)
severity (string: low/medium/high/critical)
primary_entity_id (UUID of affected entity)
primary_entity_type (string)
start_hour, end_hour (int32, 0-719)
affected_entity_ids (JSON array)
cascade_chain (JSON array of cascade steps, or null)
parameters_json (JSON dict of scenario-specific params)
```

**scenario_kpi_overrides.parquet**:
```
entity_id (UUID)
timestamp (timestamp with UTC tz)
kpi_column (string: e.g., "throughput_mbps")
override_value (float32)
scenario_id (UUID)
scenario_type (string)
source_file (string: which baseline file)
```

---

## 4. CMDB Degradation (Dark Graph)

**Responsible Module**: `/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/src/pedkai_generator/step_08_cmdb_degradation/generate.py`

### 6 Divergence Types

| Type | Rate | Mechanism | Recovery |
|------|------|-----------|----------|
| **Dark Nodes** | 6.5% | Entity dropped from CMDB | Ground truth comparison |
| **Phantom Nodes** | 3.0% | Fabricated entity in CMDB | Validation vs reality |
| **Dark Edges** | 10.0% | Relationship missing from CMDB | Graph reconciliation |
| **Phantom Edges** | 5.0% | Fabricated relationship in CMDB | Topology mismatch detection |
| **Dark Attributes** | 15.0% | Stale/incorrect attribute values | Attribute drift detection |
| **Identity Mutations** | 2.0% | Corrupted `external_id` (transposed, substituted) | Identity matching ML |

### Key Functions

**File**: `step_08_cmdb_degradation/generate.py` (lines 1-150)

```python
DIV_DARK_NODE = "dark_node"              # Entity missing
DIV_PHANTOM_NODE = "phantom_node"        # Fabricated entity
DIV_DARK_EDGE = "dark_edge"              # Relationship missing
DIV_PHANTOM_EDGE = "phantom_edge"        # Fabricated relationship
DIV_DARK_ATTRIBUTE = "dark_attribute"    # Stale/wrong attribute
DIV_IDENTITY_MUTATION = "identity_mutation"  # Corrupted external_id

# Protected entity types (NOT dark-noded):
PROTECTED_ENTITY_TYPES = {"SITE"}  # Removing a site would orphan too many children

# Mutable attributes eligible for corruption:
MUTABLE_ATTRIBUTES = [
    "vendor", "deployment_profile", "sla_tier",
    "geo_lat", "geo_lon", "band", "province", "site_type"
]

# Phantom edge templates (compatible type triples):
PHANTOM_EDGE_TEMPLATES = [
    {"from_type": "SITE", "rel_type": "HOSTS", "to_type": "CABINET"},
    {"from_type": "CABINET", "rel_type": "HOSTS", "to_type": "BBU"},
    {"from_type": "ENODEB", "rel_type": "CONTAINS", "to_type": "LTE_CELL"},
    # ... 9 more templates
]
```

### Output Files

**cmdb_declared_entities.parquet** (with deletions):
- Same schema as `ground_truth_entities.parquet`
- ~6.5% of entities removed (dark nodes)
- ~3% of entities fabricated (phantom nodes)

**cmdb_declared_relationships.parquet** (with mutations):
- Same schema as `ground_truth_relationships.parquet`
- ~10% of relationships removed (dark edges)
- ~5% of relationships fabricated (phantom edges)

**divergence_manifest.parquet** (labeled ground truth):
```
divergence_id (UUID)
divergence_type (dark_node, phantom_node, dark_edge, phantom_edge, dark_attribute, identity_mutation)
target_id (entity or relationship UUID)
target_type (SITE, LTE_CELL, ENODEB, etc.)
ground_truth_value (original value)
cmdb_declared_value (corrupted/missing value)
original_external_id, mutated_external_id (for identity mutations)
```

---

## 5. Parquet Files (Generated Dataset)

### Data Store Location
```
/Volumes/Projects/Pedkai Data Store/Telco2/output/
```

### File Inventory

| File | Size | Rows | Purpose |
|------|------|------|---------|
| **cmdb_declared_entities.parquet** | 37 MB | ~1.49M | CMDB entities (with dark/phantom nodes) |
| **cmdb_declared_relationships.parquet** | 64 MB | ~2.21M | CMDB relationships (with dark/phantom edges) |
| **ground_truth_entities.parquet** | 36 MB | ~1.49M | True entity inventory |
| **ground_truth_relationships.parquet** | 74 MB | ~2.21M | True relationships |
| **divergence_manifest.parquet** | 29 MB | ~1.45M | Dark graph labels |
| **scenario_manifest.parquet** | 528 KB | ~8.5K | Scenario schedules |
| **scenario_kpi_overrides.parquet** | 12 MB | ~2.4M | KPI override values |
| **kpi_metrics_wide.parquet** | 8.5 GB | ~47.6M | Radio KPIs (66K cells × 720 hours) |
| **transport_kpis_wide.parquet** | 1.3 GB | ~1.4M | Transport domain KPIs |
| **fixed_broadband_kpis_wide.parquet** | 400 MB | ~250K | Fixed broadband KPIs |
| **core_element_kpis_wide.parquet** | 21 MB | ~26K | Core element KPIs |
| **power_environment_kpis_wide.parquet** | 641 MB | ~840K | Power/environment KPIs |
| **customers_bss.parquet** | 45 MB | ~1M | 1M subscribers + 1M billing accounts |
| **events_alarms.parquet** | 1.2 MB | ~12K | Synthetic alarm events |
| **vendor_naming_map.parquet** | 14 KB | ~50K | Ericsson/Nokia naming conventions |
| **neighbour_relations.parquet** | 34 MB | ~8.5M | Cell neighbor relationships |

**Total Dataset Size**: ~11.3 GB (on disk)

### Generator Configuration
```yaml
# /Volumes/Projects/Pedkai Data Store/Telco2/output/generator_config.yaml

global_seed: 42000001
tenant_id: pedkai_telco2_01
ericsson_fraction: 0.55
nokia_fraction: 0.45

sites:
  greenfield: 11000
  rooftop: 4000
  streetworks: 5500
  in_building: 500
  unspecified: 100
  total: 21100

rat_split:
  lte_only: 32000
  lte_plus_nsa: 13000
  nr_sa: 6700
  total_physical_cells: 51700
  total_logical_cell_layers: 64700

simulation:
  simulation_days: 30
  reporting_interval_hours: 1
  total_hours: 720

users:
  total_subscribers: 1000000
  residential_count: 950000
  enterprise_count: 50000

cmdb_degradation:
  dark_node_rate: 0.065
  phantom_node_rate: 0.03
  dark_edge_rate: 0.1
  phantom_edge_rate: 0.05
  dark_attribute_rate: 0.15
  identity_mutation_rate: 0.02

scenario_injection:
  sleeping_cell_rate: 0.02
  congestion_rate: 0.05
  coverage_hole_rate: 0.01
  hardware_fault_rate: 0.005
  interference_rate: 0.03
  transport_failure_rate: 0.002
  power_failure_rate: 0.001
  fibre_cut_rate: 0.0005
```

---

## 6. Related Files in Pedkai Core

### Data Loading & Integration

**File**: `/Users/himanshu/Projects/Pedkai/backend/app/scripts/load_telco2_tenant.py` (97 KB)

**Purpose**: Ingests Telco2 Parquet files into PostgreSQL + TimescaleDB

**Key Functions**:
- `step_0_create_tenant()` — Tenant record creation
- `step_1_load_network_entities()` — Load CMDB entities
- `step_2_load_entity_relationships()` — Load CMDB relationships
- `step_6_load_divergence_manifest()` — Load ground truth divergence labels
- `step_7_load_scenarios()` — Load scenario manifest
- `step_11_register_kpi_datasets()` — Register KPI Parquet files (not exploded)
- `step_12_load_kpi_sample()` — Load small KPI sample to TimescaleDB

**Configuration** (environment variables):
```bash
GRAPH_DB_DSN=host=localhost port=5432 dbname=pedkai user=postgres
METRICS_DB_DSN=host=localhost port=5433 dbname=pedkai_metrics user=postgres
PEDKAI_DATA_STORE_ROOT=/Volumes/Projects/Pedkai Data Store
```

### Demo Scripts

**File**: `/Users/himanshu/Projects/Pedkai/demo/seed_full_demo.py` (203 lines)

**Purpose**: Minimal demo data generation for testing (uses `uuid4()`)
- 20 customers
- 5 capacity requests
- 30 alarms/decisions
- Manually crafted (not using Telco2 generator)

**File**: `/Users/himanshu/Projects/Pedkai/demo/scenarios.py` (113 lines)

**Purpose**: Test scenarios demonstrating autonomous remediation & policy blocking

**File**: `/Users/himanshu/Projects/Pedkai/demo/seed_data.py` (88 lines)

**Purpose**: Legacy minimal seed script

### Mock Simulators (Alarm Generation)

**File**: `/Users/himanshu/Projects/Pedkai/integration/mock_nokia_netact.py`
- Simulates Nokia alarm firehose (Kafka)
- Generates alarm IDs: `NOK-ALM-{uuid.uuid4().hex[:6]}`

**File**: `/Users/himanshu/Projects/Pedkai/integration/mock_ericsson_oss.py`
- Simulates Ericsson alarm firehose (Kafka) + REST webhook
- Generates alarm IDs: `ERI-ALM-{uuid.uuid4().hex[:6]}`

---

## 7. Architecture Overview (Pipeline Diagram)

```
Step 01: Sites
    └─> intermediate/sites.parquet (21.1K sites)
        └─> intermediate/cells.parquet (64.7K cells)

Step 02: Topology
    └─> ground_truth_entities.parquet (1.49M total entities)
    └─> ground_truth_relationships.parquet (2.21M relationships)
    └─> output/{core,transport,fixed,power}_elements.parquet

Step 03: Radio KPIs [AR(1) Streaming]
    └─> output/kpi_metrics_wide.parquet (47.6M rows, 8.5 GB)

Step 04: Domain KPIs
    └─> output/{transport,fixed_broadband,core_element,power_environment}_kpis_wide.parquet

Step 05: Scenarios [Fault Injection]
    └─> output/scenario_manifest.parquet (8.5K scenarios)
    └─> output/scenario_kpi_overrides.parquet (2.4M overrides)

Step 06: Events/Alarms
    └─> output/events_alarms.parquet (12K events)

Step 07: Customers/BSS
    └─> output/customers_bss.parquet (1M customers)

Step 08: CMDB Degradation [Dark Graph]
    ├─ Ground truth from Step 02
    ├─> output/cmdb_declared_entities.parquet (with deletions/fabrications)
    ├─> output/cmdb_declared_relationships.parquet (with deletions/fabrications)
    └─> output/divergence_manifest.parquet (labels)

Step 09: Vendor Naming
    └─> output/vendor_naming_map.parquet (Ericsson/Nokia maps)

Step 10: Validation
    └─> QA gates & integrity checks

Step 11: Loader
    └─> PostgreSQL graph DB + TimescaleDB metrics
```

---

## 8. Summary Table: Generator Functions

| Aspect | Module | Function | Input | Output |
|--------|--------|----------|-------|--------|
| **UUID4** | `step_01_sites/generate.py` | `str(uuid.uuid4())` | None | Site/cell IDs |
| **KPI Time-Series (AR(1))** | `step_03_radio_kpis/profiles.py::StreamingEnvironmentGenerator` | `_AR1State.step()` | Previous state | Hourly conditions |
| **KPI Physics** | `step_03_radio_kpis/physics.py` | `compute_cell_kpis_vectorised()` | Conditions + cell params | 44 KPI metrics |
| **Scenario Injection** | `step_05_scenarios/generate.py` | 8 scenario generators | Config rates + seed | Manifest + overrides |
| **Dark Graph** | `step_08_cmdb_degradation/generate.py` | `_mutate_*()` functions | Ground truth + rates | Declared state |
| **Data Loading** | `load_telco2_tenant.py` | `step_*_load_*()` functions | Parquet files + DB | PostgreSQL tables |

---

## 9. Known Limitations & Remediations

### RED_FLAG_REPORT Remediations (implemented in Step 03)
- **RF-04**: Stochastic null injection (0.15% per KPI) — ROP failure simulation
- **RF-05**: PM collection gaps (0.08%) — maintenance/NMS failover simulation
- **RF-15**: Rural traffic outliers (0.1%) — festival/transit spike simulation

### Memory Safety
- **Before**: Pre-allocated (720, 66K) float64 matrices → ~4 GB peak + OOM risk
- **After**: AR(1) streaming with per-hour flushing → ~150-200 MB peak

### Data Authenticity
- Parquet files are static, versioned snapshots (MD5 checksums tracked)
- Ground truth vs declared state split enables Dark Graph ML training
- Divergence manifest provides labeled training data for reconciliation

---

## 10. Current State Summary

| Item | Status | Details |
|------|--------|---------|
| **Generator** | ✅ Complete | 11-step pipeline, fully implemented |
| **Telco2 Dataset** | ✅ Generated | 11.3 GB Parquet snapshot (2024-01-01 to 2024-01-30) |
| **AR(1) KPI Model** | ✅ Production | Streaming, memory-safe, 47.6M rows |
| **Scenario Injection** | ✅ Production | 8 types, 8.5K instances, cascades enabled |
| **CMDB Degradation** | ✅ Production | 6 divergence types, 1.45M labeled instances |
| **Loader Integration** | ✅ Production | Pedkai `load_telco2_tenant.py` fully integrated |
| **Documentation** | ✅ Excellent | 383 KB detailed spec, thread summaries, assessments |
| **Testing** | ✅ Complete | `step_10_validation/validate.py` + RED_FLAG remediation |

---

## Appendix A: File Paths (Absolute)

### Generator Module (Sleeping-Cell-KPI-Data)
```
/Users/himanshu/Projects/Sleeping-Cell-KPI-Data/src/pedkai_generator/
├── step_01_sites/generate.py             [UUID4]
├── step_03_radio_kpis/generate.py        [AR(1) orchestrator]
├── step_03_radio_kpis/profiles.py        [AR(1) streaming]
├── step_03_radio_kpis/physics.py         [Physics chain]
├── step_05_scenarios/generate.py         [Scenario injection]
├── step_08_cmdb_degradation/generate.py  [Dark graph]
└── cli.py                                [Entry point]
```

### Pedkai Integration
```
/Users/himanshu/Projects/Pedkai/backend/app/scripts/load_telco2_tenant.py
/Users/himanshu/Projects/Pedkai/demo/seed_full_demo.py
/Users/himanshu/Projects/Pedkai/integration/mock_nokia_netact.py
/Users/himanshu/Projects/Pedkai/integration/mock_ericsson_oss.py
```

### Data Store
```
/Volumes/Projects/Pedkai Data Store/Telco2/output/*.parquet (15 files)
/Volumes/Projects/Pedkai Data Store/Telco2/output/generator_config.yaml
```

---

## Appendix B: Configuration Schema

See `step_00_schema/contracts.py` for full Pydantic definitions:
- `GeneratorConfig` — top-level configuration
- `CMDBDegradationConfig` — dark graph rates
- `ScenarioInjectionConfig` — fault injection rates
- Entity types: `SiteType`, `DeploymentProfile`, `Vendor`, `RAT`, `SLATier`

---

**End of Audit Report**
