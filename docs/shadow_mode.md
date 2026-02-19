# Pilot Architecture: Shadow Mode Deployment

Description of the Pedkai "Shadow Mode" deployment for the initial pilot phase.

## 1. Definition of Shadow Mode
In Shadow Mode, Pedkai consumes real-world network data but its "Actions" are NOT executed on the live network. Instead, they are logged as recommendations for human review.

## 2. Data Flow
- **Ingress**: Real-time TMF642 Alarms and TMF628 KPIs.
- **Processing**: AI analysis of root cause and impact.
- **Output**: Proposed actions (Decision Traces) displayed on the dashboard.

## 3. Comparison Logic (Control Group)
The "Autonomous Evaluator" service compares Pedkai's proposed actions against the ACTUAL actions taken by human operators during the pilot.

## 4. Key Performance Indicators (KPIs)
- **Precision**: % of Pedkai recommendations that humans agreed with.
- **Recall**: % of critical incidents Pedkai correctly identified.
- **Lead Time Improvement**: Simulated OpEx savings if Pedkai had been in "Closed Loop".

## 5. Promotion Criteria
Transition to "Closed Loop" (Automated Execution) requires:
- 95% Precision over a 30-day period.
- Zero "Safety Guard" violations.
- Sign-off from the Network Sovereignty Gatekeeper.
