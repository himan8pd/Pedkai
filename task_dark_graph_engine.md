# Task: Build New Dark Graph Engine

## Objective
Design and implement a new Dark Graph Engine for Pedkai that identifies and reports dark nodes, phantom nodes, identity mutations, dark edges, and phantom edges using only CMDB and telemetry data (no ground truth tables).

## Algorithm Outline

1. **Input Data**
   - CMDB inventory (network_entities, topology_relationships)
   - Telemetry data (timeseries, logs, events, device messages)
   - Incident, Change, Knowledge Management, and Problem ticket data (structured and unstructured)
   - Abeyance memory (persistent memory of unresolved or ambiguous entities, relationships, and events)

2. **Dark Node Detection**
   - For each telemetry source/entity, check if it exists in CMDB.
   - If not present in CMDB, classify as a dark node.

3. **Phantom Node Detection**
   - For each CMDB entity, check if it generates any telemetry.
   - If no telemetry is observed, classify as a phantom node.

4. **Identity Mutation Detection**
   - For entities present in both CMDB and telemetry, compare key attributes (MAC address, chassis number, device ID, etc.).
   - If attributes differ but identifier (e.g., IP address) matches, classify as identity mutation.

5. **Dark Edge Detection**
   - Analyze telemetry for evidence of relationships (e.g., link events, routing tables, connection logs).
   - If a relationship is observed in telemetry but missing from CMDB, classify as a dark edge.

6. **Phantom Edge Detection**
   - For each CMDB relationship, check if there is any telemetry evidence supporting it.
   - If no evidence is found, classify as a phantom edge.

7. **Dark Attribute Detection**
   - For matched entities, compare operational attributes between CMDB and telemetry.
   - If attributes differ, report as dark attribute (output to flat file, not UI).

8. **Abeyance Memory Integration**
   - When evidence (telemetry, tickets, logs) cannot be mapped to known entities or relationships, store it in abeyance memory.
   - Periodically sweep abeyance memory after each new entity or event ingestion, attempting to resolve items using updated context.
   - Attach resolved evidence to the dark graph, promoting hypotheses and updating discovered nodes/edges.
   - Use abeyance memory to enable delayed, cross-domain, and long-duration discovery, connecting fragmented evidence over time.
   - Track statistics and progress from abeyance memory resolutions to improve the engine's effectiveness.

9. **Reporting**
   - Generate structured reports for each divergence type.
   - UI should focus on nodes and edges; dark attributes reported separately.
   - Provide summary statistics and actionable insights.
   - Track progress and improvements in dark graph discovery using abeyance memory.

## Steps
1. Design data ingestion and normalization for CMDB and telemetry.
2. Implement entity and relationship matching logic.
3. Develop detection algorithms for each divergence type.
4. Build reporting and export modules (UI, flat file, summary).
5. Test with real and simulated data; validate accuracy and business value.
6. Document the engine and provide user guidance.

---

This task will deliver a robust, business-focused Dark Graph Engine for Pedkai, fully independent of ground truth tables.