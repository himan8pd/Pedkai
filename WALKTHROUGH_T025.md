# Divergence Report and Topology Explorer Implementation

## Objective
Implement an intelligent divergence reporting tool that dynamically compares the organization intent (CMDB) against ground truth telemetry. Also, enhance the topology view to use a targeted, seed-based explorer approach instead of attempting to render the entire network map at once.

## Implemented Backend Features

### 1. The Reconciliation Engine
We created a robust new service layer class, [ReconciliationEngine](file:///Users/himanshu/Projects/Pedkai/backend/app/services/reconciliation_engine.py#51-712) ([reconciliation_engine.py](file:///Users/himanshu/Projects/Pedkai/backend/app/services/reconciliation_engine.py)), which performs dynamic algorithm-based discovery to detect CMDB drift:
*   **Dark Nodes:** Ground truth entities missing from CMDB.
*   **Phantom Nodes:** CMDB entities missing from ground truth.
*   **Identity Mutations:** Mismatched `external_id` between systems.
*   **Dark Attributes:** Drifted configuration (e.g. [vendor](file:///Users/himanshu/Projects/Pedkai/backend/app/scripts/load_telco2_tenant.py#1561-1623), `band`, `status`) inside JSON properties.
*   **Dark Edges:** Unknown network relationships present in reality but disconnected in the CMDB.
*   **Phantom Edges:** Expected paths that are actually dismantled or unplugged in reality.

The engine performs high-performance SQL set-differences to generate highly accurate structural insight dynamically, ensuring the application does not rely on pre-seeded "use cases".
We implemented a scoring algorithm that compares the engine's dynamically discovered discrepancies against a seeded [divergence_manifest](file:///Users/himanshu/Projects/Pedkai/backend/app/scripts/load_telco2_tenant.py#1187-1263), grading the platform's detection capabilities with Precision, Recall, and F1 scores natively.

### 2. New Divergence API Endpoints ([reports.py](file:///Users/himanshu/Projects/Pedkai/backend/app/api/reports.py))
We replaced the previous stub implementation with five fully-functional API endpoints:
1.  **`POST /divergence/run`**: Triggers a full, asynchronous reconciliation scan of the environment and logs metrics to `reconciliation_runs`.
2.  **`GET /divergence/summary`**: Aggregates counts and accuracy metrics from the latest successfully completed run.
3.  **`GET /divergence/records`**: Serves paginated, filterable records to the frontend data table.
4.  **`GET /divergence/report/{tenant_id}`**: Wraps all data up for export.
5.  **`GET /divergence/score/{tenant_id}`**: Retrieves the dynamic scoring card (F1 metrics matching findings to the ground truth manifest).

### 3. Seed-Based Topology API ([topology.py](file:///Users/himanshu/Projects/Pedkai/backend/app/api/topology.py))
We migrated the topology endpoint from "boil the ocean" logic to targeted exploration:
*   **`GET /topology/{tenant_id}/search`**: Search endpoint to find specific nodes by name or ID.
*   **`GET /topology/{tenant_id}/neighborhood/{seed_id}`**: Extracts the N-hop subset graph spanning outward from a given entity or ID.

These functions handle dynamically constructing a graph spanning [network_entities](file:///Users/himanshu/Projects/Pedkai/backend/app/scripts/load_telco2_tenant.py#170-312) and [topology_relationships](file:///Users/himanshu/Projects/Pedkai/backend/app/scripts/load_telco2_tenant.py#453-564), with specific patches to ensure raw SQL syntax remains valid across both Postgres and SQLite databases.


## Implemented Frontend Features

### 1. Divergence Dashboard (`/divergence`)
We laid out an analytical command-center UI consisting of:
*   A **Status Header** indicating when the last reconciliation was run, paired with an actionable 'Run Reconciliation' button to trigger the API.
*   **Divergence Metric Cards** color-coding occurrences by severity and type (Phantom Nodes, Dark Attributes, Identity Mutations).
*   **Accuracy Grid & Engine Scorecard**, surfacing Data Accuracy (%) per domain and the F1 Score calculated natively against the ground truth reference manifest.
*   An **Interactive Results Table**, supporting column filtering, pagination, and sorting for quick diagnosis, connected directly to our new backend APIs.

### 2. Seed-Based Topology Network Map (`/topology`)
We fundamentally rewrote the topology visualization structure to handle large-scale networks gracefully:
*   **Left-Side Search Panel**: Allows querying a specific domain or host out of millions to serve as the initial graph seed.
*   Interactive **Force-Directed Physics Engine** rendering the neighborhood directly around the requested seed.
*   Right-Side **Node Inspection Panel**, allowing engineers to analyze a node, then click 'Set as new seed' to re-center the universe around a connected node and seamlessly traverse the network.

## Testing and Database Support

We added an extensive integration test suite ([tests/integration/test_divergence.py](file:///Users/himanshu/Projects/Pedkai/tests/integration/test_divergence.py)) which spins up an embedded PyTest SQLite database, seeds CMDB and Telemetry data, then triggers the reconciliation engine.

**Fixes Applied during Testing Validation:**
*   Ensured custom queries originally relying on Postgres-specific operators (like `->>`, [::text](file:///Users/himanshu/Projects/Pedkai/backend/app/core/database.py#88-100), `ANY()`, and `ILIKE`) had equivalent cross-dialect ORM wrappers (`LIKE`, `bindparam(expanding=True)`) or SQLite-validated syntax (using built-in `JSON` data typing, `CAST`, and string literals).
*   Corrected the `CREATE TABLE` defaults across tests (`DEFAULT CURRENT_TIMESTAMP` instead of `DEFAULT now()`).
*   Restored domain columns missing in ground truth tables needed for multi-tenant isolation routing.
*   Fixed `setRelationships({})` → `setRelationships([])` in the topology page Clear button handler (array state was being incorrectly reset to an object).

**Test Outputs:**
```text
============================= test session starts ==============================
...
tests/integration/test_divergence.py::test_reconciliation_run PASSED     [ 25%]
tests/integration/test_divergence.py::test_scoring_endpoint PASSED       [ 50%]
tests/integration/test_divergence.py::test_topology_search PASSED        [ 75%]
tests/integration/test_divergence.py::test_topology_neighborhood PASSED  [100%]
============================== 4 passed in 0.47s ===============================
```

## Next Steps
We are now fully feature complete against T-025 and ready to move towards real integration scaling.
