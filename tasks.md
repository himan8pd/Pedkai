# Tasks for Dark Node Topology Enhancement

## 1. Backend: Topology API
- Entity and relationship resolution must be based only on what Pedkai discovers via telemetry analysis and CMDB comparison.
- Never use gt_network_entities for populating the topology graph or UI; it is only for evaluation.
- Mark dark nodes in the API response (e.g., is_dark_node: true) based on Pedkai's discovery.
- Ensure relationships involving discovered dark nodes are included.

## 2. Frontend: Topology Graph Rendering
- Update entity rendering to visually distinguish dark nodes (color, shape, icon).
- Add legend entry for "Dark Node".
- Show dark node details in the entity panel, even if CMDB info is missing.
- Allow traversal between CMDB and dark nodes.

## 3. Visual Use Cases
- Highlight cases where dark nodes bridge unrelated CMDB nodes.
- Make these scenarios visually appealing and clear to the customer.

## 4. Testing & Validation
- Test with sample data containing dark nodes.
- Validate that dark nodes and their relationships are visible and navigable.

---

This plan addresses the requirement to show both CMDB inventory and dark nodes side by side in the topology view, with clear visual distinction and traversal support. All UI and API logic must be based only on Pedkai's discovered entities and relationships, never directly from gt_network_entities.