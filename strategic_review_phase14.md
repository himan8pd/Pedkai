# Strategic Review: Phase 14 - Customer Experience Intelligence
**Role**: Telecom Business Strategist (VJV-Scale Perspective)  
**Status**: CRITICAL GAPS IDENTIFIED - REMEDIATION REQUIRED

## 🎯 Vision Alignment Score: 4/10
The current implementation of Phase 14 provides a functional "skeleton" for Customer Experience (CX) Intelligence but fails to deliver the "AI Control Plane" substance promised in the product vision. It treats CX as a siloed relational lookup rather than a horizontal intelligence layer.

---

## 🚩 Critical Risks & Anomalies

### 1. The "Context Graph" Regression
> [!WARNING]
> **Vision Violation**: The vision (Layer 2) demands a Context Graph correlating Customers, Services, and Network Elements.
> 
> **Implementation Reality**: The code explicitly avoids graph traversal, opting for a simple `associated_site_id` match. At a VJV scale, customers are mobile. A "home site" lookup is insufficient for real-time impact analysis (e.g., a customer impacted at their workplace or while roaming).

### 2. The "Intelligence" Silo (Missing Domains)
> [!IMPORTANT]
> **Gap**: The vision explicitly mandates correlation across **Network + Billing + Care + Social**.
> 
> **Implementation Reality**: Current logic is purely Network -> Churn Score. There is zero ingestion or correlation of:
> - **Billing Issues**: No check for overcharging or billing errors.
> - **Support Tickets**: No awareness of open complaints (the strongest churn indicator).
> - **Social Media**: No integration with Reddit/X/DownDetector for high-fidelity sentiment mapping.

### 3. Static Churn Risk vs. Dynamic Prediction
The `churn_risk_score` is a static float in the `customers` table. The vision describes a system that *predicts* churn. 
- **Risk**: Without a dynamic inference engine consuming real-time behavioral data, we are acting on stale, manually-seeded intelligence. This is a "lookup table," not an "AI brain."

### 4. Hardcoded "Proactive" Care
The proactive care message is a generic, hardcoded string. 
- **Recommendation**: Pedkai's USP is LLM-powered reasoning. The system should generate *tailored* care messages based on the specific RCA output (e.g., "We know your 5G video streaming is buffing due to PRB congestion; we are offloading traffic now to fix it").

---

## 🛠️ Required Specific Improvements

To move from a "demo-grade" to a "VJV-grade" implementation, the vendor must implement the following:

### 1. Dynamic CX Correlation Engine (The "Brain")
Replace the simple SQL query in `CXIntelligenceService` with a multi-factor scoring engine that considers:
- Current network performance at the customer's *last seen* location (using KPI metrics).
- Recent billing dispute flags.
- Sentiment of any open support tickets.

### 2. Social Media & External Sentiment Ingress
Implement an `ExternalSentimentService` that mocks/ingests Reddit or DownDetector feeds. Correlate "Spikes in Reddit mentions for Site X" with "Network Anomaly at Site X" to accelerate proactive care triggers.

### 3. LLM-Personalized Proactive Care
Update `trigger_proactive_care` to use the `LLMService`. 
- **Input**: Anomaly RCA + Customer Profile.
- **Output**: A hyper-personalized notification ("We noticed your gold-tier service is falling below SLA in [Location]...") rather than the current hardcoded template.

### 4. Measurable ROI Tracking
Add a `ProactiveOutcomeORM` to track whether customers who received proactive care actually stayed on the network vs. a control group. Without this, the "quantifiable benefit" requirement of the vision is impossible to prove to the CFO.

---

## 🚦 Strategic Verdict
The implementation is an **Operational Prototype** but not a **Strategic Wedge**. It proves that the pipes are connected, but it lacks the horizontal reasoning capacity that defines Pedkai. 

**Vendor Action Required**: Address the "Context Graph" and "Personalization" gaps immediately before this is presented to the CTO.
