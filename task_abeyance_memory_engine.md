# Task: Build Abeyance Memory Engine

## Objective
Design and implement an Abeyance Memory Engine for Pedkai to persist, manage, and resolve ambiguous or incomplete evidence items, enabling delayed and enriched dark graph discovery.

## Algorithm Outline

1. **Input Evidence**
   - Evidence items from telemetry, incident/change/problem tickets, knowledge management, etc.
   - Each item may reference unresolved entities or relationships.

2. **Abeyance Item Structure**
   - item_id: unique identifier
   - evidence: evidence item (event, log, ticket, etc.)
   - unresolved_entity: entity or relationship not yet mapped
   - resolution_hints: partial info (IP, hostname, coordinates, role, etc.)
   - created_at: timestamp
   - ttl: time-to-live (duration to keep item)
   - resolution_attempts: count
   - dark_graph_type: determines TTL (Type 1-4)
   - resolved: boolean

3. **Add to Abeyance Memory**
   - When evidence cannot be mapped, create AbeyanceItem and store it.

4. **Sweep for Resolution**
   - After each new entity/event ingestion, sweep abeyance memory.
   - Attempt to resolve items using new context (identifiers, mappings, etc.).
   - If resolved, attach evidence to hypothesis and mark item as resolved.
   - If TTL expires, discard item.

5. **Persistence**
   - Store abeyance items in a database table (abeyance_items).
   - Support periodic sweeps and updates.

6. **Reporting**
   - Track statistics: number of items, resolution rate, average time to resolution.
   - Provide insights into long-duration and cross-domain discoveries.

---

This engine will enable Pedkai to connect fragmented evidence, support delayed discovery, and enrich the dark graph over time.
