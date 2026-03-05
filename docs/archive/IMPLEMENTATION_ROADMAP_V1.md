# Pedkai V8 — Multi-Phase Implementation Roadmap

**Date:** 26 February 2026  
**Status:** Architectural Blueprint — Ready for Engineering  
**Governing Document:** `Pedkai_Vision_V8.md`  
**Revision:** V8.0 — Core Foundation (Edge-Level Dark Graph Reconciliation)

---

## Preamble: The Datagerry/CasinoLimit Nexus

Before a single line of code is written, the engineering team must internalise why these two datasets are the perfect proving ground.

**Datagerry (The Intent Layer — 700+ CIs):**
The CMDB currently holds `GameInstance` objects (instance_name, status) and `NetworkZone` objects (hostname, instance_ref, role). For every CasinoLimit campaign instance, Datagerry knows:

| CI Type | Fields | What CMDB "Thinks" |
|---|---|---|
| `GameInstance` | instance_name, status=active | "This instance exists." |
| `NetworkZone` | hostname=`start.{inst}.local`, role=start | "There is a machine called start." |
| `NetworkZone` | hostname=`bastion.{inst}.local`, role=bastion | "There is a machine called bastion." |
| `NetworkZone` | hostname=`meetingcam.{inst}.local`, role=meetingcam | "There is a machine called meetingcam." |
| `NetworkZone` | hostname=`intranet.{inst}.local`, role=intranet | "There is a machine called intranet." |

The CMDB stores 5 flat objects per instance. It knows **zero** relationships between them. No edges. No dependencies. No notion that `start` can reach `bastion` via SSH, that `bastion` has a path to `meetingcam`, or that `meetingcam` can exploit `intranet`'s database. The CMDB is structurally blind.

**CasinoLimit (The Chaos Layer — 114 Campaign Timelines):**
Each campaign instance contains:
- `syslogs/` — auditd kernel logs per machine, showing every `openat`, `execve`, `connect` syscall
- `labelled_flows/` — unidirectional network flows with MITRE ATT&CK technique labels
- `flows_zeek/` — bidirectional Zeek connection records (src_ip, dst_ip, port, duration, bytes)
- `syslogs_labels/` — JSON mappings from label UIDs to auditd event IDs and MITRE techniques
- `steps.csv` — campaign step progression with instance identifiers

The telemetry contains the **actual topology**: machine-to-machine SSH sessions, lateral movement, privilege escalation chains, data exfiltration paths. These are real network edges — proved by packet flow — that the CMDB has no record of.

**The Reconciliation Thesis:**  
Datagerry says: "5 independent CIs exist."  
CasinoLimit says: "start → bastion → meetingcam → intranet is a directed dependency chain with T1021 (Remote Services) edges and T1068 (Privilege Escalation) transitions."

The gap between these two statements IS the Dark Graph. Pedkai's job is to find it, prove it, and hand it to a CIO as a detailed map of what their CMDB missed.

---

## Phase 1: The Ingestion Fabric (Weeks 1–4)

### Objective
Build the bi-directional data bridge between Datagerry's static CMDB and CasinoLimit's raw telemetry. At the end of Week 4, Pedkai can ingest both streams, normalise them into a common event schema, and produce a **Divergence Report** — a machine-generated document listing every CI in Datagerry that has no telemetry-corroborated relationship versus every telemetry-observed dependency that has no corresponding CMDB edge.

### 1.1 — Datagerry Sync Adapter (Week 1)

**Current state:** `generate_cmdb.py` is a write-only bootstrap script. It pushes CIs into Datagerry but never reads them back programmatically for reconciliation.

**Required: `DagerryIntentAdapter`** — a read-path service that periodically snapshots the entire CMDB state into Pedkai's internal representation.

```python
# backend/app/adapters/datagerry_adapter.py

@dataclass(frozen=True)
class CMDBSnapshot:
    """Immutable point-in-time snapshot of Datagerry state."""
    snapshot_id: str                          # SHA256 of serialised content
    captured_at: datetime
    entities: dict[str, CMDBEntity]           # external_id → entity
    declared_edges: set[tuple[str, str, str]] # (from_id, to_id, rel_type)
    
@dataclass
class CMDBEntity:
    external_id: str        # e.g., "start.aeriella.local"
    ci_type: str            # "GameInstance" | "NetworkZone"
    fields: dict[str, Any]  # raw Datagerry field values
    last_modified: datetime
    datagerry_object_id: int
```

**Sync Protocol:**
1. `GET /rest/objects/?type_id={game_instance_id}` → all GameInstance CIs
2. `GET /rest/objects/?type_id={network_zone_id}` → all NetworkZone CIs
3. For each NetworkZone, extract `instance_ref` to build the implicit parent-child relationship: `GameInstance` → `NetworkZone`
4. Construct `declared_edges` from the `instance_ref` field: these are the ONLY relationships the CMDB knows about (instance contains zone)
5. Hash the entire snapshot content → `snapshot_id` for change detection
6. Store in PostgreSQL with `snapshot_id` as idempotency key

**Non-negotiable:** The adapter must produce a `declared_edges` set. If the CMDB declares **zero inter-zone edges** (which it does — Datagerry currently stores no relationships between NetworkZones), the set is empty. This emptiness is not a bug; it is the signal that Phase 2 will exploit.

**Scheduling:** Cron-based poll every 5 minutes in dev. In production, Datagerry supports webhooks on object change — wire that to an `/api/v1/cmdb/webhook` endpoint that triggers a delta-sync.

### 1.2 — CasinoLimit Telemetry Parser (Weeks 1–2)

**Current state:** `parse_casinolimit_instances()` extracts instance names from `steps.csv`. The actual telemetry (syslogs, flows, labels) is untouched.

**Required: `CasinoLimitChaosAdapter`** — a batch-mode parser that extracts three telemetry streams per instance:

#### Stream A: Network Flow Events
Source: `labelled_flows/{instance}/` (unidirectional) + `flows_zeek/{instance}/` (bidirectional Zeek)

```python
@dataclass(frozen=True)
class ObservedFlowEvent:
    instance_id: str
    src_host: str               # Resolved to zone role: "start", "bastion", etc.
    dst_host: str               # Resolved to zone role
    src_ip: str
    dst_ip: str
    dst_port: int
    protocol: str               # tcp/udp
    timestamp: datetime
    duration_sec: float
    bytes_sent: int
    bytes_recv: int
    mitre_technique: str | None # From labelled_flows join, e.g., "T1021"
    mitre_tactic: str | None    # Derived from technique
    zeek_uid: str | None        # Cross-reference to Zeek conn log
```

**IP-to-Zone Resolution:** CasinoLimit's 4 hosts per instance are on known subnets. The Zeek logs contain source/destination IPs. Map each IP to a zone role (`start`, `bastion`, `meetingcam`, `intranet`) using the subnet assignment from the URSID deployment config. If URSID config isn't available, derive it empirically: for each instance, cluster IPs by which machine's syslogs reference them (auditd `ADDR=` fields).

#### Stream B: Syscall Events
Source: `syslogs/{instance}/{zone}/audit.log`

```python
@dataclass(frozen=True)
class ObservedSyscallEvent:
    instance_id: str
    zone: str                   # "start", "bastion", "meetingcam", "intranet"
    timestamp: datetime
    syscall: str                # "openat", "execve", "connect", "sendto"
    exe: str                    # Binary path, e.g., "/usr/bin/ssh"
    uid: str                    # User executing
    euid: str                   # Effective user (for priv-esc detection)
    target_path: str | None     # File path (for openat/read)
    audit_event_id: int         # Maps to syslogs_labels
```

#### Stream C: MITRE Label Events
Source: `syslogs_labels/{instance}/system_labels/{zone}.json`

```python
@dataclass(frozen=True)
class MITRELabelEvent:
    instance_id: str
    zone: str
    label_uid: str
    technique_id: str           # "T1021"
    technique_name: str         # "Remote Services"
    audit_event_ids: list[int]  # Links to Stream B
```

**Storage:** All three streams write to a common `telemetry_events` table in PostgreSQL with a JSONB `payload` column and indexed columns for `instance_id`, `zone`, `event_type`, `timestamp`. No separate tables per stream — the reconciliation engine needs to join across all three.

**Batch Ingest Contract:** The parser processes one instance at a time, yielding events in chronological order. For 114 instances × ~4 zones × ~1000 events/zone ≈ 456,000 events. This fits comfortably in a single PostgreSQL instance with proper indexing.

### 1.3 — The Normalisation Layer (Week 2)

Both adapters produce data in Pedkai's internal schema. The normalisation layer translates every entity and event into the `graph_schema.py` ontology.

**Entity Mapping:**

| Source | Maps To | EntityType |
|---|---|---|
| Datagerry `GameInstance` | `NetworkEntity` | `SERVICE` (logical grouping) |
| Datagerry `NetworkZone` (role=start) | `NetworkEntity` | `ROUTER` (entry point) |
| Datagerry `NetworkZone` (role=bastion) | `NetworkEntity` | `SWITCH` (network hop) |
| Datagerry `NetworkZone` (role=meetingcam) | `NetworkEntity` | `BROADBAND_GATEWAY` (media host) |
| Datagerry `NetworkZone` (role=intranet) | `NetworkEntity` | `LANDLINE_EXCHANGE` (data store) |

These mappings are configurable via YAML (not hardcoded). The point is: every Datagerry CI becomes a first-class `NetworkEntity` in the graph, with an `external_id` linking back to its Datagerry `object_id`.

**Edge Extraction from Telemetry:**
For each `ObservedFlowEvent` where `src_host ≠ dst_host`:
1. Resolve `src_host` → `NetworkEntity.id` (via zone→entity mapping)
2. Resolve `dst_host` → `NetworkEntity.id`
3. Emit candidate edge: `(src_entity, dst_entity, CONNECTS_TO, {port, protocol, first_seen, last_seen, flow_count, mitre_techniques: set()})`

Accumulate across all events for the same entity pair. The result: an **Observed Edge Set** — every machine-to-machine connection the telemetry proves actually happened.

### 1.4 — The Divergence Report (Weeks 3–4)

This is the Week 4 deliverable that proves commercial value to a CIO without installing a single agent.

**Algorithm:**

```
CMDB_Edges = dagerry_snapshot.declared_edges           # Currently: ∅ (empty)
Observed_Edges = aggregate(flow_events, by=(src, dst)) # ~N edges per instance

# DARK EDGES: Observed in telemetry, absent from CMDB
dark_edges = Observed_Edges - CMDB_Edges

# PHANTOM EDGES: Declared in CMDB, never observed in telemetry
phantom_edges = CMDB_Edges - Observed_Edges

# CONFIRMED EDGES: Present in both
confirmed_edges = CMDB_Edges ∩ Observed_Edges
```

**For CasinoLimit, the result is devastating:**
- `dark_edges` ≈ **all inter-zone connections** (start→bastion SSH, bastion→meetingcam exploit, meetingcam→intranet DB access). The CMDB knows nothing about these.
- `phantom_edges` = ∅ (Datagerry declares no inter-zone edges, so nothing to contradict)
- `confirmed_edges` = ∅ (Datagerry declares no edges to confirm)

**Report Format:**

```json
{
  "report_id": "DIV-2026-02-26-001",
  "cmdb_snapshot_id": "sha256:abc...",
  "telemetry_window": {"from": "2024-05-17T00:00:00Z", "to": "2024-05-17T23:59:59Z"},
  "summary": {
    "total_cmdb_entities": 710,
    "total_observed_entities": 456,
    "entities_in_both": 456,
    "dark_edges_discovered": 387,
    "phantom_edges_flagged": 0,
    "confirmed_edges": 0,
    "cmdb_completeness_score": 0.0  
  },
  "dark_edges": [
    {
      "from_entity": "start.aeriella.local",
      "to_entity": "bastion.aeriella.local",
      "evidence": {
        "flow_count": 47,
        "first_seen": "2024-05-17T14:22:01Z",
        "last_seen": "2024-05-17T15:41:33Z",
        "dominant_port": 22,
        "dominant_protocol": "tcp",
        "mitre_techniques": ["T1021: Remote Services"],
        "bytes_transferred": 284930
      },
      "confidence": 0.97,
      "confidence_rationale": "47 distinct flows over 79 minutes on SSH port. Corroborated by auditd showing /usr/bin/ssh execve on start machine targeting bastion IP."
    }
  ],
  "recommendation": "387 functional dependencies exist in production that your CMDB does not track. 100% of observed inter-host connectivity is invisible to your current ITIL process."
}
```

**The CIO pitch:** "We ran Pedkai offline against your historical logs and your existing CMDB export. We found 387 real dependencies your CMDB doesn't know about. Zero agents. Zero network changes. Here's the proof."

### 1.5 — Topological Ghost Mask Generation (Week 3)

Vision V8, Layer 2: *"When a sector goes dark, Pedkai cross-references Change Schedules. If an upgrade is active, it applies a 'Topological Ghost' mask."*

**The Problem:** When CasinoLimit telemetry shows a zone going silent (no flows, no auditd activity), Pedkai must distinguish between:
1. **Planned maintenance** — the zone is intentionally offline (suppress alarms)
2. **Actual failure** — the zone has crashed or been compromised (raise alarm)
3. **Completed campaign** — the attacker has finished and left (mark as historical)

**Data Source for "Change Schedules":** CasinoLimit doesn't ship with an external change management system. We synthesise one:
- Each campaign instance has a known start time (first event) and end time (last event)
- The `steps.csv` progression provides the expected activity sequence
- We generate a synthetic `change_schedule` table:

```sql
CREATE TABLE change_schedule (
    id UUID PRIMARY KEY,
    instance_id TEXT NOT NULL,
    zone TEXT NOT NULL,
    change_type TEXT NOT NULL,          -- 'campaign_start', 'campaign_end', 'maintenance_window'
    scheduled_start TIMESTAMPTZ,
    scheduled_end TIMESTAMPTZ,
    status TEXT DEFAULT 'scheduled',    -- 'scheduled', 'active', 'completed'
    source TEXT DEFAULT 'synthetic'     -- 'synthetic' for demo, 'servicenow' / 'remedy' in prod
);
```

**Ghost Mask Algorithm:**

```
on_telemetry_silence(entity_id, zone, silent_since):
    # Step 1: Check change schedule
    active_changes = query(change_schedule, 
        WHERE zone = zone 
        AND status = 'active' 
        AND silent_since BETWEEN scheduled_start AND scheduled_end)
    
    if active_changes:
        # APPLY GHOST MASK — entity is "expected absent"
        mask = TopologicalGhostMask(
            entity_id=entity_id,
            reason="planned_change",
            change_ref=active_changes[0].id,
            mask_type="suppress_alarm",
            expires_at=active_changes[0].scheduled_end + grace_period(15min)
        )
        store(mask)
        # DO NOT propagate silence as anomaly
        # DO NOT trigger Dark Graph inference for this entity
        return GHOST_MASKED
    
    # Step 2: Check if this is a known campaign boundary
    campaign = query(steps, WHERE instance_id = instance_id)
    if silent_since > campaign.last_event_time:
        mask = TopologicalGhostMask(
            entity_id=entity_id,
            reason="campaign_completed",
            mask_type="archive",
            expires_at=None  # Permanent historical mask
        )
        store(mask)
        return GHOST_MASKED
    
    # Step 3: Genuine anomaly — entity unexpectedly silent
    return ANOMALY_DETECTED
```

**Ghost Mask Data Structure:**

```python
@dataclass
class TopologicalGhostMask:
    mask_id: str
    entity_id: str
    zone: str
    reason: str              # "planned_change" | "campaign_completed" | "scheduled_maintenance"
    change_ref: str | None   # FK to change_schedule.id
    mask_type: str           # "suppress_alarm" | "archive" | "temporary_silence"
    created_at: datetime
    expires_at: datetime | None
    is_active: bool = True
```

**Why this matters for production (beyond CasinoLimit):** In a real telco deployment, the `change_schedule` table is populated by a ServiceNow/Remedy webhook delivering RFC (Request for Change) records. When a planned 5G sector upgrade causes cells to go dark, Pedkai applies the ghost mask automatically instead of flooding the NOC with false alarms. The algorithm is identical — only the data source changes.

### Phase 1 Acceptance Criteria

| # | Criterion | Measurement |
|---|---|---|
| P1.1 | Datagerry adapter produces a full `CMDBSnapshot` with ≥700 entities | Assert `len(snapshot.entities) >= 700` |
| P1.2 | CasinoLimit parser extracts flow events for all 114 instances | Assert `distinct(instance_id) == 114` from telemetry_events |
| P1.3 | IP-to-zone resolution achieves ≥95% accuracy | Manual spot-check of 20 instances against Zeek conn logs |
| P1.4 | Divergence Report correctly identifies ≥95% of inter-zone edges as "dark" | Compare discovered dark edges against known CasinoLimit topology (4 zones = max 12 directed edges per instance) |
| P1.5 | Ghost Mask suppresses alarms for campaign boundaries | Inject silence for a completed campaign instance → assert no anomaly raised |
| P1.6 | Zero heavy agents deployed | Architecture review: all data sourced from REST APIs and file reads |

### Phase 1 Non-Deliverables
- No UI, no dashboard, no visualisation
- No LLM calls
- No real-time streaming (batch-mode only)
- No autonomous actions

---

## Phase 2: Latent Topology Inference — The "Dark Graph" (Weeks 5–8)

### Objective
Transform the Divergence Report's flat list of dark edges into a **probabilistic graph** where every edge carries a confidence score, a provenance chain, and a mathematical proof of why it should exist. By the end of Week 8, Pedkai can not only say "start connects to bastion" but explain *why* it believes this, *how confident* it is, and *what would change its mind*.

### 2.1 — The Hypothesis Engine (Week 5)

Every dark edge from Phase 1 starts as an **unverified hypothesis**. The engine's job is to promote hypotheses through evidence stages until they reach a confidence threshold.

**Hypothesis Lifecycle:**

```
CANDIDATE → CORROBORATED → ACCEPTED → INTEGRATED
   ↓              ↓              ↓
DISCARDED     CONTESTED      DEGRADED
```

```python
class EdgeHypothesisState(str, Enum):
    CANDIDATE = "candidate"         # Single-source observation (e.g., one flow event)
    CORROBORATED = "corroborated"   # Multi-source evidence agrees
    ACCEPTED = "accepted"           # Passes confidence threshold + policy gate
    INTEGRATED = "integrated"       # Written back to CMDB reconciliation ledger
    DISCARDED = "discarded"         # Evidence contradicted or insufficient
    CONTESTED = "contested"         # Sources disagree — human review needed
    DEGRADED = "degraded"           # Was accepted, but new evidence weakens it

@dataclass
class EdgeHypothesis:
    hypothesis_id: str
    from_entity_id: str
    to_entity_id: str
    relationship_type: str          # CONNECTS_TO, DEPENDS_ON, etc.
    state: EdgeHypothesisState
    
    # Evidence accumulator
    evidence_bundle: list[EvidenceItem]
    
    # Confidence model
    confidence: float               # 0.0–1.0
    confidence_components: dict     # Breakdown by source type
    
    # Lifecycle timestamps
    created_at: datetime
    last_evidence_at: datetime
    state_transitions: list[tuple[datetime, str, str, str]]  # (when, from, to, reason)
    
    # Policy gate result (from Constitution)
    policy_decision: str | None     # "allow" | "deny" | "confirm"
    
@dataclass
class EvidenceItem:
    source_type: str                # "network_flow" | "auditd_syscall" | "mitre_label" | "cmdb_field" | "ticket_note"
    source_id: str                  # Reference to raw event
    timestamp: datetime
    weight: float                   # 0.0–1.0: how much this evidence contributes
    content_hash: str               # SHA256 of evidence payload for tamper detection
    corroboration_group: str | None # Links evidence items that corroborate each other
```

### 2.2 — Multi-Modal Corroboration Algorithm (Weeks 5–6)

Vision V8: *"To infer a 'Latent Edge,' Pedkai builds a probabilistic hypothesis. It swiftly seeks corroboration across disparate data sources."*

The algorithm scores each hypothesis based on how many independent data sources agree on the edge's existence.

**Confidence Scoring Model:**

For a hypothesis $H$ asserting edge $(A \to B)$:

$$
C(H) = 1 - \prod_{i=1}^{n} (1 - w_i \cdot s_i)
$$

Where:
- $n$ = number of distinct evidence items
- $w_i$ = weight of evidence source type $i$ (see table below)
- $s_i$ = specificity of evidence item $i$ (0.0–1.0, how directly it proves this specific edge)

This is a **noisy-OR** model: each independent evidence source has a probability of proving the edge. The combined probability that at least one source correctly identifies the edge increases with each new piece of evidence, but with diminishing returns.

**Source Type Weights:**

| Source Type | Base Weight ($w_i$) | Rationale |
|---|---|---|
| `network_flow` (Zeek bidirectional) | 0.85 | Direct packet-level proof of communication |
| `auditd_execve` (SSH/connect syscall) | 0.75 | System-level proof of connection attempt |
| `mitre_label` (T1021 Remote Services) | 0.65 | Expert-labelled lateral movement confirmation |
| `auditd_openat` (file access on target) | 0.50 | Indirect: proves activity on target but not source |
| `cmdb_instance_ref` (same instance group) | 0.30 | Weak: shared instance ≠ connectivity |
| `temporal_correlation` | 0.20 | Very weak: overlapping timestamps only |

**Specificity Score ($s_i$):**
- `1.0` if evidence directly names both endpoints (e.g., Zeek flow from IP_A to IP_B matching entity A and entity B)
- `0.7` if evidence names one endpoint and the other is inferred (e.g., auditd on machine A shows SSH to an IP that resolves to machine B's subnet)
- `0.3` if evidence is circumstantial (e.g., both machines show activity within the same 5-second window)

**Worked Example:**
Hypothesis: `start.aeriella.local → bastion.aeriella.local` (CONNECTS_TO)

| Evidence | Source Type | $w_i$ | $s_i$ | $1 - w_i \cdot s_i$ |
|---|---|---|---|---|
| Zeek conn log: 10.0.1.5:54321 → 10.0.2.3:22 | `network_flow` | 0.85 | 1.0 | 0.15 |
| auditd on `start`: `execve /usr/bin/ssh tbenedict@10.0.2.3` | `auditd_execve` | 0.75 | 1.0 | 0.25 |
| MITRE label: T1021 on `start` linking to bastion audit events | `mitre_label` | 0.65 | 0.7 | 0.545 |
| Same GameInstance in Datagerry | `cmdb_instance_ref` | 0.30 | 0.3 | 0.91 |

$$C(H) = 1 - (0.15 \times 0.25 \times 0.545 \times 0.91) = 1 - 0.0186 = 0.981$$

Confidence: **0.981** — well above any reasonable acceptance threshold.

**Contrast: Weak Hypothesis**
Hypothesis: `meetingcam.aeriella.local → start.aeriella.local` (CONNECTS_TO)

If the only evidence is that both machines exist in the same GameInstance:

| Evidence | Source Type | $w_i$ | $s_i$ | $1 - w_i \cdot s_i$ |
|---|---|---|---|---|
| Same GameInstance | `cmdb_instance_ref` | 0.30 | 0.3 | 0.91 |

$$C(H) = 1 - 0.91 = 0.09$$

Confidence: **0.09** — this hypothesis remains `CANDIDATE` and is not promoted. Pedkai does NOT draw an edge here. This is the anti-correlation discipline.

### 2.3 — The Corroboration Pipeline (Week 6)

```
for each dark_edge in divergence_report.dark_edges:
    H = EdgeHypothesis(from=dark_edge.from, to=dark_edge.to, state=CANDIDATE)
    
    # Stage 1: Network flow evidence (highest weight)
    flows = query(telemetry_events, 
        WHERE event_type='flow' AND src_host=H.from AND dst_host=H.to)
    for flow in flows:
        H.add_evidence(EvidenceItem(source_type='network_flow', weight=0.85, 
                                     specificity=1.0, source_id=flow.id))
    
    # Stage 2: Syscall evidence (corroboration)
    syscalls = query(telemetry_events,
        WHERE event_type='syscall' AND zone=H.from.zone 
        AND exe LIKE '%ssh%' AND payload->>'target_ip' resolves to H.to)
    for sc in syscalls:
        H.add_evidence(EvidenceItem(source_type='auditd_execve', weight=0.75,
                                     specificity=compute_specificity(sc, H.to)))
    
    # Stage 3: MITRE technique labels (expert knowledge)
    labels = query(telemetry_events,
        WHERE event_type='mitre_label' AND zone=H.from.zone
        AND technique_id IN ('T1021', 'T1563', 'T1071'))  # Lateral movement techniques
    for label in labels:
        cross_ref = correlate_label_to_target(label, H.to)
        if cross_ref:
            H.add_evidence(EvidenceItem(source_type='mitre_label', weight=0.65,
                                         specificity=cross_ref.confidence))
    
    # Stage 4: CMDB structural proximity (weak signal)
    if same_instance(H.from, H.to):
        H.add_evidence(EvidenceItem(source_type='cmdb_instance_ref', weight=0.30,
                                     specificity=0.3))
    
    # Compute confidence
    H.confidence = noisy_or(H.evidence_bundle)
    
    # State transition
    if H.confidence >= ACCEPTANCE_THRESHOLD:       # Default: 0.75
        if len(distinct_source_types(H)) >= 2:     # MUST have multi-modal evidence
            H.state = CORROBORATED
        else:
            H.state = CANDIDATE                    # Single-source cannot promote
    elif H.confidence < DISCARD_THRESHOLD:          # Default: 0.10
        H.state = DISCARDED
```

**Critical Rule:** A hypothesis CANNOT be promoted to `CORROBORATED` with evidence from a single source type, regardless of confidence score. If 100 network flows all say the same thing, that's still single-source. Pedkai requires at least **2 distinct source types** agreeing. This is the anti-hallucination discipline from Vision V8.

### 2.4 — The Abeyance Memory (Week 7)

Vision V8: *"Pedkai reads incident notes and remembers disconnected technical facts. Weeks later, when matching network events occur, Pedkai connects the dots."*

**Problem:** Some evidence arrives out of order. A MITRE label might reference auditd events that haven't been parsed yet. A Zeek flow might arrive before the corresponding syscall log for the same SSH session.

**Solution: The Abeyance Buffer** — a holding area for evidence items that cannot yet be attached to a hypothesis.

```python
@dataclass
class AbeyanceItem:
    item_id: str
    evidence: EvidenceItem
    unresolved_entity: str          # The entity this evidence mentions but we can't map yet
    resolution_hints: dict          # Partial info: IP, hostname fragment, subnet
    created_at: datetime
    ttl: timedelta                  # How long to keep before discarding (default: 30 days)
    resolution_attempts: int = 0
    
class AbeyanceMemory:
    """
    Holds evidence that can't yet be attached to a hypothesis.
    Periodically re-evaluated as new context arrives.
    """
    
    def add(self, evidence: EvidenceItem, unresolved_entity: str, hints: dict):
        item = AbeyanceItem(evidence=evidence, unresolved_entity=unresolved_entity,
                            resolution_hints=hints, ttl=timedelta(days=30))
        self._store.append(item)
    
    def sweep(self, new_context: dict[str, str]):
        """
        Called after each new entity or event ingestion.
        Attempts to resolve abeyance items against new context.
        
        new_context: mapping of identifiers (IPs, hostnames) → entity_ids
        """
        resolved = []
        for item in self._store:
            for hint_key, hint_value in item.resolution_hints.items():
                if hint_value in new_context:
                    # SNAP: Context completes — attach evidence to hypothesis
                    target_entity = new_context[hint_value]
                    self._emit_evidence(item.evidence, target_entity)
                    resolved.append(item)
                    break
            
            item.resolution_attempts += 1
            if item.created_at + item.ttl < datetime.utcnow():
                resolved.append(item)  # TTL expired — discard
        
        for item in resolved:
            self._store.remove(item)
```

**CasinoLimit Application:** When parsing instance `aeriella`, if a Zeek flow references IP `10.0.3.7` but the IP-to-zone mapping for that IP isn't established yet (meetingcam's subnet hasn't been resolved), the flow event goes into abeyance. When the meetingcam auditd logs are parsed and we discover that machine's IP is `10.0.3.7`, the abeyance sweep fires, attaches the flow evidence to the `bastion → meetingcam` hypothesis, and potentially promotes it.

### 2.5 — The Dark Graph Materialisation (Week 8)

At the end of the corroboration pipeline, Pedkai holds a set of `CORROBORATED` or `ACCEPTED` edge hypotheses. These are materialised as `EntityRelationship` records in the existing `graph_schema.py` ontology, with extensions:

```python
class InferredEntityRelationship(EntityRelationship):
    """Extension of base relationship for Dark Graph edges."""
    
    # Provenance
    hypothesis_id: str
    inference_method: str           # "multi_modal_corroboration"
    confidence: float               # From noisy-OR model
    evidence_count: int
    distinct_source_types: int
    
    # Lifecycle
    state: EdgeHypothesisState
    first_observed: datetime
    last_corroborated: datetime
    
    # Reconciliation status
    cmdb_reconciled: bool = False   # True once written back to Datagerry
    reconciled_at: datetime | None = None
```

**Graph Storage:** These relationships are written to the same `topology_relationships` table used by the existing topology API, with an additional `inference_metadata` JSONB column. This means the existing `/api/v1/topology/{tenant_id}` endpoint automatically includes Dark Graph edges — no new API needed.

### Phase 2 Acceptance Criteria

| # | Criterion | Measurement |
|---|---|---|
| P2.1 | Noisy-OR model produces confidence scores consistent with worked examples | Unit tests with known evidence sets → assert confidence within ±0.02 |
| P2.2 | Single-source hypotheses are NEVER promoted to CORROBORATED | Property test: inject N evidence items all of same source_type → assert state ≠ CORROBORATED |
| P2.3 | Multi-modal corroboration correctly identifies ≥90% of known CasinoLimit lateral movement paths | Compare against ground truth (T1021 labelled paths) |
| P2.4 | Abeyance memory resolves ≥80% of items when delayed context arrives | Inject evidence with unresolved IPs, then provide IP mapping → assert resolution rate |
| P2.5 | False positive rate ≤5% | Dark edges flagged as ACCEPTED that don't correspond to actual CasinoLimit paths |
| P2.6 | Zero LLM calls in the inference pipeline | Code review: grep for llm_service usage in hypothesis engine |

---

## Phase 3: Telemetry Cross-Examination (Weeks 9–11)

### Objective
Build the automated "truth arbitration" system that prevents data pollution. Every manual input (ticket notes, CMDB updates, operator annotations) is treated as a hypothesis and cross-examined against telemetry. If the telemetry contradicts the manual input, Pedkai discards the input and produces an audit trail explaining why.

### 3.1 — The Dissonance Detection Engine (Week 9)

Vision V8: *"If a note states 'restarted the edge firewall' but the packet flow metrics show zero interruption at that exact millisecond, Pedkai flags the dissonance and safely discards the input."*

**Input Types Subject to Cross-Examination:**

| Input Type | Cross-Examination Method |
|---|---|
| Manual resolution note ("restarted service X") | Check: did service X's telemetry show a restart signature (process restart, TCP RST burst, brief silence then recovery)? |
| CMDB manual update ("added dependency A→B") | Check: does any telemetry show traffic from A to B within the observation window? |
| Operator annotation ("root cause was firewall rule") | Check: does firewall log show rule change at claimed time? |
| Auto-discovered edge from a 3rd-party tool | Check: does Pedkai's own multi-modal corroboration agree? |

**CasinoLimit Application:**
CasinoLimit's `syslogs_labels` contain human-authored MITRE technique labels. These were manually reviewed using the Manatee labeling tool. We treat them as "operator annotations" — statements about what happened that must be verified against raw telemetry.

**Cross-Examination Algorithm:**

```python
class CrossExaminationVerdict(str, Enum):
    CORROBORATED = "corroborated"   # Telemetry agrees with manual input
    CONTRADICTED = "contradicted"   # Telemetry directly disagrees
    UNVERIFIABLE = "unverifiable"   # No telemetry covers this claim (Dark Graph territory)
    PARTIAL = "partial"             # Some aspects confirmed, others not

@dataclass
class CrossExaminationResult:
    input_id: str
    input_type: str
    claimed_fact: str               # Human-readable claim
    verdict: CrossExaminationVerdict
    telemetry_evidence: list[EvidenceItem]
    contradiction_detail: str | None
    confidence: float               # How confident are we in the verdict itself
    action_taken: str               # "accepted" | "discarded" | "quarantined" | "escalated"
    audit_trail: str                # Full reasoning chain
```

**The Cross-Examination Pipeline:**

```
def cross_examine(manual_input: ManualInput) -> CrossExaminationResult:
    
    # Step 1: Parse the claim into structured assertions
    assertions = extract_assertions(manual_input)
    # e.g., "restarted service X" → [Assertion(action="restart", target="service_X", time=claimed_time)]
    
    # Step 2: For each assertion, query telemetry
    for assertion in assertions:
        
        # 2a: Find the entity referenced
        entity = resolve_entity(assertion.target)
        if not entity:
            yield CrossExaminationResult(verdict=UNVERIFIABLE,
                reason=f"Entity '{assertion.target}' not found in topology")
            continue
        
        # 2b: Define the telemetry signature for the claimed action
        signature = get_action_signature(assertion.action)
        # "restart" → {
        #   "expected_patterns": [
        #       "process_exit followed by process_start within 60s",
        #       "TCP RST burst at claimed_time ± 30s",
        #       "telemetry silence window of 5-120s"
        #   ],
        #   "contradicting_patterns": [
        #       "continuous steady-state traffic through claimed restart window",
        #       "no process lifecycle events at claimed time"
        #   ]
        # }
        
        # 2c: Query telemetry for the entity in the time window
        window = (assertion.time - timedelta(minutes=2), assertion.time + timedelta(minutes=2))
        telemetry = query(telemetry_events,
            WHERE entity_id = entity.id AND timestamp BETWEEN window)
        
        # 2d: Check for confirming patterns
        confirms = [p for p in signature.expected_patterns 
                    if pattern_match(p, telemetry)]
        
        # 2e: Check for contradicting patterns
        contradicts = [p for p in signature.contradicting_patterns
                       if pattern_match(p, telemetry)]
        
        # 2f: Verdict
        if contradicts and not confirms:
            return CONTRADICTED, f"Claim '{assertion}' contradicted: {contradicts[0]}"
        elif confirms and not contradicts:
            return CORROBORATED
        elif confirms and contradicts:
            return PARTIAL  # Escalate to human
        else:
            return UNVERIFIABLE  # No matching telemetry at all
```

### 3.2 — Action Signatures for CasinoLimit Domain (Week 9)

Since CasinoLimit is a security/attack dataset, the "manual inputs" are MITRE labels and the "telemetry" is auditd + network flows. Action signatures:

```yaml
# backend/app/data/action_signatures.yaml

action_signatures:
  - action: "T1021_remote_services"
    description: "Claim: lateral movement via remote service (SSH, RDP)"
    expected_patterns:
      - type: "network_flow"
        filter: "dst_port IN (22, 3389) AND src_host = claimed_source AND dst_host = claimed_target"
        min_flows: 1
      - type: "auditd_execve"
        filter: "exe IN ('/usr/bin/ssh', '/usr/bin/sshpass') AND zone = claimed_source"
        min_events: 1
    contradicting_patterns:
      - type: "network_flow"
        filter: "NO flows exist between claimed_source and claimed_target in window"
        description: "If the label says T1021 but zero network traffic exists between the machines, the label is wrong."

  - action: "T1068_privilege_escalation"
    description: "Claim: privilege escalation occurred"
    expected_patterns:
      - type: "auditd_syscall"
        filter: "uid != euid AND euid = 'root'"
        min_events: 1
        description: "A syscall where effective UID escalated to root"
      - type: "auditd_execve"
        filter: "exe IN ('/usr/bin/sudo', '/usr/bin/su', '/usr/bin/pkexec')"
        min_events: 1
    contradicting_patterns:
      - type: "auditd_syscall"
        filter: "ALL events show uid == euid throughout window"
        description: "No privilege change detected in audit trail"

  - action: "T1485_data_destruction"
    description: "Claim: data was destroyed"
    expected_patterns:
      - type: "auditd_syscall"
        filter: "syscall IN ('unlink', 'unlinkat', 'truncate') OR (exe LIKE '%rm%' OR exe LIKE '%DROP%')"
        min_events: 1
      - type: "auditd_openat"
        filter: "target_path matches database files AND mode = write"
    contradicting_patterns:
      - type: "auditd_syscall"
        filter: "NO destructive syscalls in window AND database files show read-only access"
```

### 3.3 — The Discard Protocol and Quarantine (Week 10)

When cross-examination returns `CONTRADICTED`:

```
1. DO NOT incorporate the manual input into the training model
2. DO NOT use it as evidence for any hypothesis
3. Write a full audit record:
   {
     "input_id": "...",
     "verdict": "contradicted",
     "contradiction": "Label claims T1021 (SSH lateral movement) from start to intranet, 
                        but zero network flows exist between start and intranet. 
                        The only flows from start go to bastion (port 22).",
     "telemetry_evidence": [...],
     "action": "discarded",
     "discarded_at": "2026-02-26T14:00:00Z",
     "discard_reason": "telemetry_contradiction",
     "review_required": false
   }
4. Increment discard counter for the source (operator/system)
5. If discard_rate for a source exceeds 30% over 100+ inputs:
   → Flag source for review ("potential systematic error or compromised account")
```

**For `UNVERIFIABLE` verdicts (Dark Graph territory):**

This is where Vision V8's most sophisticated logic kicks in: *"For areas in the 'Dark Graph' without telemetry, Pedkai autonomously tests its next most likely guess, searching for corroborating attachments or auxiliary log files until it can mathematically prove the state is accurate."*

```
when verdict == UNVERIFIABLE:
    # We have no telemetry to confirm or deny. This is Dark Graph.
    
    # Strategy: Active Hypothesis Search
    # 1. Query abeyance memory for any partial evidence
    partial = abeyance_memory.search(entity=claimed.entity, time_window=claimed.time)
    
    # 2. Search auxiliary sources (other instances with similar topology)
    analogues = find_analogous_instances(claimed.entity.zone, claimed.entity.instance)
    for analogue in analogues:
        analogue_evidence = query(telemetry_events, 
            WHERE instance_id = analogue.id AND zone = claimed.zone
            AND event_type = claimed.expected_event_type)
        if analogue_evidence:
            # Analogous instance shows this pattern IS possible
            # Weaken confidence but don't discard
            quarantine(manual_input, reason="unverifiable_but_analogous_support",
                       confidence=0.40)
            break
    else:
        # No analogue supports the claim either
        quarantine(manual_input, reason="unverifiable_no_support",
                   confidence=0.15)
```

**Quarantine vs. Discard:**
- **Discard**: Telemetry actively contradicts the claim. Permanent rejection.
- **Quarantine**: Cannot verify, but not actively contradicted. Held in limbo. If future telemetry arrives that supports it, promote. If TTL expires (30 days), discard.

### 3.4 — Constitution Integration: Data Pollution Guardrails (Week 10–11)

The existing `global_policies.yaml` handles operational actions (traffic priority, revenue protection). Phase 3 adds a new policy section specifically for data integrity:

```yaml
# Addition to global_policies.yaml

# ═══════════════════════════════════════════════════════════════
# DATA INTEGRITY CONSTITUTION — Layer 4 Extension
# Prevents data pollution from manual inputs and external feeds
# ═══════════════════════════════════════════════════════════════

data_integrity_policies:
  version: "1.0.0"
  
  # Gate 1: Source Trust Levels
  source_trust:
    - source_type: "telemetry_auditd"
      trust_level: 0.95
      rationale: "Kernel-level audit logs are tamper-evident"
    - source_type: "telemetry_network_flow"
      trust_level: 0.90
      rationale: "Packet captures are objective but may miss encrypted payloads"
    - source_type: "telemetry_zeek"
      trust_level: 0.88
      rationale: "Zeek is derived from pcap — reliable but one step removed"
    - source_type: "manual_mitre_label"
      trust_level: 0.60
      rationale: "Human-reviewed labels, subject to error"
    - source_type: "manual_resolution_note"
      trust_level: 0.40
      rationale: "Free-text notes from operators, frequently inaccurate"
    - source_type: "cmdb_manual_update"
      trust_level: 0.35
      rationale: "Manual CMDB edits are the most common source of drift"
    - source_type: "auto_discovery_agent"
      trust_level: 0.70
      rationale: "Agent-discovered edges — reliable if agent is functioning"

  # Gate 2: Cross-Examination Thresholds
  cross_examination:
    # Minimum confidence from cross-examination to accept a manual input
    acceptance_threshold: 0.65
    
    # Below this, auto-discard without human review
    auto_discard_threshold: 0.15
    
    # Between discard and acceptance: quarantine
    quarantine_ttl_days: 30
    
    # Maximum discard rate per source before flagging
    source_anomaly_discard_rate: 0.30
    source_anomaly_min_samples: 100

  # Gate 3: Anti-Pollution Rules
  anti_pollution:
    - rule_id: "AP-001"
      name: "Single-Source Injection Block"
      description: "No edge hypothesis may be ACCEPTED based on a single manual input without telemetry corroboration"
      condition: "evidence_sources == 1 AND source_type.startswith('manual')"
      action: "quarantine"
      
    - rule_id: "AP-002"
      name: "Bulk Manual Update Rate Limit"
      description: "If a single source submits >50 CMDB updates in 1 hour, suspend processing and alert"
      condition: "source_update_count_1h > 50"
      action: "suspend_source"
      alert_severity: "high"
      
    - rule_id: "AP-003"
      name: "Contradiction Cascade Halt"
      description: "If >10 manual inputs from the same source are contradicted in sequence, halt that source's pipeline"
      condition: "sequential_contradictions > 10"
      action: "halt_pipeline"
      alert_severity: "critical"
      rationale: "Potential compromised account or systematic misunderstanding"
      
    - rule_id: "AP-004"
      name: "Dark Graph Update Provenance"
      description: "Any update to a Dark Graph edge must include the full evidence bundle hash"
      condition: "target_is_dark_graph_edge AND evidence_bundle_hash IS NULL"
      action: "reject"
      
    - rule_id: "AP-005"
      name: "Confidence Decay on Stale Evidence"
      description: "If an edge's most recent corroborating evidence is >90 days old, demote confidence by 20%"
      condition: "days_since_last_evidence > 90"
      action: "degrade_confidence"
      degradation_factor: 0.80
```

**PolicyEngine Extension:**
The existing `PolicyEngine.evaluate()` handles operational context. Add a new method `evaluate_data_integrity()` that loads the `data_integrity_policies` section and applies it to incoming evidence and manual inputs:

```python
async def evaluate_data_integrity(
    self,
    input_source: str,
    input_type: str,
    evidence_count: int,
    distinct_source_types: int,
    cross_exam_confidence: float,
    target_is_dark_edge: bool,
    evidence_bundle_hash: str | None,
) -> DataIntegrityDecision:
    """
    Evaluate whether a manual input or external feed should be accepted
    into the knowledge graph.
    
    Returns: accept, quarantine, discard, or halt_pipeline
    """
```

### Phase 3 Acceptance Criteria

| # | Criterion | Measurement |
|---|---|---|
| P3.1 | Cross-examination correctly identifies ≥85% of contradictions | Inject known-false labels (e.g., T1021 for a pair with no flows) → assert CONTRADICTED |
| P3.2 | Zero false discards of legitimate labels | Cross-examine ground-truth CasinoLimit labels → assert none CONTRADICTED when telemetry agrees |
| P3.3 | Anti-pollution rule AP-001 blocks single-source manual injection | Inject manual edge claim with no telemetry → assert quarantined, not accepted |
| P3.4 | Bulk rate limit AP-002 triggers at >50 updates/hour | Simulate rapid manual updates → assert source suspended |
| P3.5 | Quarantine items auto-promote when supporting evidence arrives | Add quarantined item → inject matching telemetry → assert state = CORROBORATED |
| P3.6 | Full audit trail for every discard decision | Query audit log → every DISCARDED input has non-null contradiction_detail |

---

## Phase 4: The "WOW" Demo (Weeks 12–14)

### Objective
A production-ready, end-to-end demonstration that shows a single, verifiable reconciliation event: a Dark Edge is discovered, proved, cross-examined, and offered for CMDB integration — with the full audit trail visible.

### 4.1 — The Demo Scenario

**Title: "The Invisible SSH Chain"**

**Setup:**
- Datagerry CMDB contains 5 CIs for instance `aeriella`: 1 GameInstance + 4 NetworkZones
- CMDB declares **zero** inter-zone relationships
- CasinoLimit telemetry for `aeriella` has been ingested

**Act 1: The Divergence (Phase 1 output)**
System displays the Divergence Report. 387 dark edges across all instances. For `aeriella` specifically:
- `start → bastion` (dark, SSH, 47 flows)
- `bastion → meetingcam` (dark, exploitation, 12 flows)
- `meetingcam → intranet` (dark, DB access, 8 flows)

"Your CMDB knows about 5 machines. It knows about zero of the connections between them."

**Act 2: The Proof (Phase 2 output)**
Drill into `start → bastion`:
- Hypothesis ID, state = ACCEPTED
- Confidence: 0.981
- Evidence bundle (4 items from 3 distinct source types)
- Full noisy-OR calculation visible
- State transition history: CANDIDATE → CORROBORATED → ACCEPTED

"Pedkai doesn't guess. It proves. Three independent data sources agree this connection exists."

**Act 3: The Guard (Phase 3 output)**
Inject a false manual claim: "meetingcam connects directly to start on port 443."
- Cross-examination runs
- Verdict: CONTRADICTED
- Reason: "Zero network flows between meetingcam and start. All meetingcam outbound traffic goes to intranet (port 5432)."
- Input discarded, audit trail written

"An operator (or a compromised account) just tried to inject a false dependency. Pedkai caught it in 200ms."

**Act 4: The Integration (Phase 1 + 2 combined)**
Show the reconciliation ledger:
- 3 dark edges for `aeriella` ready for CMDB integration
- Each with full provenance chain
- One-click "Write to Datagerry" button that creates the relationships as CMDB edges

"Click this button. Your CMDB now knows about dependencies it's been blind to for months."

### 4.2 — Demo Technical Architecture

```
                    ┌─────────────────────────────┐
                    │   Demo CLI / Minimal Web UI  │
                    │  (Read-only views + 1 write) │
                    └──────────────┬──────────────┘
                                   │ REST API
                    ┌──────────────┴──────────────┐
                    │      Pedkai Backend API       │
                    │  /api/v1/reconciliation/*     │
                    └──────────────┬──────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
┌─────────┴──────────┐  ┌─────────┴──────────┐  ┌─────────┴──────────┐
│ DagerryIntentAdapter│  │  HypothesisEngine  │  │ CrossExamEngine    │
│ (Phase 1)          │  │  (Phase 2)          │  │ (Phase 3)          │
└─────────┬──────────┘  └─────────┬──────────┘  └─────────┬──────────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │     PostgreSQL + pgvector     │
                    │  telemetry_events            │
                    │  edge_hypotheses             │
                    │  cross_exam_results          │
                    │  topology_relationships      │
                    │  ghost_masks                 │
                    │  change_schedule             │
                    └──────────────────────────────┘
```

**New API Endpoints for the Demo:**

```
GET  /api/v1/reconciliation/divergence-report
     → Returns the Phase 1 divergence report for a given tenant/instance

GET  /api/v1/reconciliation/hypotheses?instance_id={id}
     → Returns all edge hypotheses with confidence scores and evidence bundles

GET  /api/v1/reconciliation/hypotheses/{id}/evidence
     → Returns the full evidence chain for one hypothesis

POST /api/v1/reconciliation/cross-examine
     → Submit a manual claim, receive a CrossExaminationResult

POST /api/v1/reconciliation/integrate/{hypothesis_id}
     → Write an ACCEPTED hypothesis back to Datagerry as a CMDB relationship

GET  /api/v1/reconciliation/audit-trail?input_id={id}
     → Full audit trail for any input, including discard decisions

GET  /api/v1/reconciliation/ghost-masks?instance_id={id}
     → Active Topological Ghost Masks for an instance
```

### 4.3 — The Presentation Layer (Minimal, Deterministic, NOT a Dashboard)

The demo UI is a **CLI-first, web-optional** presentation. The CLI is the primary interface. A minimal web view exists only for live presentations.

**CLI Output:**

```
$ pedkai reconcile --instance aeriella --verbose

╔══════════════════════════════════════════════════════════════════╗
║ PEDKAI RECONCILIATION ENGINE — Instance: aeriella               ║
╠══════════════════════════════════════════════════════════════════╣
║ CMDB Entities:     5    │  Telemetry Events:  2,847             ║
║ CMDB Edges:        0    │  Observed Edges:    3                 ║
║ Dark Edges:        3    │  Phantom Edges:     0                 ║
║ CMDB Completeness: 0.0% │  Reconciliation: CRITICAL             ║
╚══════════════════════════════════════════════════════════════════╝

DARK EDGES DISCOVERED:

  [1] start.aeriella.local → bastion.aeriella.local
      Confidence: 0.981 (ACCEPTED)
      Evidence: 3 source types, 4 items
      ├─ network_flow:  47 SSH flows (port 22), 284KB transferred
      ├─ auditd_execve: /usr/bin/ssh executions on 'start'
      └─ mitre_label:   T1021 (Remote Services) confirmed
      
  [2] bastion.aeriella.local → meetingcam.aeriella.local
      Confidence: 0.914 (ACCEPTED)
      Evidence: 2 source types, 3 items
      ├─ network_flow:  12 flows (port 8080), 156KB transferred
      └─ auditd_execve: exploitation binary executed on 'bastion'
      
  [3] meetingcam.aeriella.local → intranet.aeriella.local
      Confidence: 0.873 (ACCEPTED)
      Evidence: 2 source types, 2 items
      ├─ network_flow:  8 flows (port 5432), 42KB transferred
      └─ mitre_label:   T1485 (Data Destruction) on 'intranet'

GHOST MASKS ACTIVE: 0

CROSS-EXAMINATION READY.
Type 'pedkai inject --claim "..." to test data pollution defense.
Type 'pedkai integrate --edge 1,2,3' to write to Datagerry.
```

### 4.4 — Demo Execution Runbook

| Step | Duration | What Happens | What the Audience Sees |
|---|---|---|---|
| 1. Show Datagerry UI | 30s | Browse CMDB. 5 CIs. Zero relationships. | "This is your enterprise's source of truth." |
| 2. Run `pedkai ingest` | 10s | Silent. Batch ingestion of CasinoLimit telemetry. | Terminal progress bar. |
| 3. Run `pedkai reconcile` | 5s | Full Phase 1+2 pipeline executes. | Divergence Report + Dark Edges appear. |
| 4. Zoom into Edge #1 | 30s | Show full evidence bundle for start→bastion. | 4 evidence items, noisy-OR math, state transitions. |
| 5. Run `pedkai inject` | 15s | Submit false claim "meetingcam→start on 443." | CONTRADICTED verdict with telemetry proof. |
| 6. Run `pedkai integrate` | 10s | Write 3 edges back to Datagerry via REST API. | "3 relationships created in CMDB." |
| 7. Refresh Datagerry UI | 15s | Browse CMDB again. Now shows 3 relationships. | "Your CMDB just healed itself." |
| **Total** | **~2 min** | | |

### Phase 4 Acceptance Criteria

| # | Criterion | Measurement |
|---|---|---|
| P4.1 | End-to-end demo completes in <3 minutes | Stopwatch from first command to "CMDB healed" |
| P4.2 | Every number in the demo output is mathematically traceable | Audience can ask "why 0.981?" and get the full noisy-OR derivation live |
| P4.3 | False claim injection is detected and rejected within 500ms | Timing assertion on cross-examination response |
| P4.4 | Datagerry CMDB reflects new edges after integration step | REST API `GET /rest/objects/` confirms new relationships |
| P4.5 | No "UNVERIFIABLE" verdicts in the scripted demo path | All demo claims are in telemetry-covered zones |
| P4.6 | CLI output works without a web browser | Full demo executable from terminal only |

---

## Sequencing Rule (Non-Negotiable)

```
Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4
  │            │            │            │
  │            │            │            └─ UI/CLI ONLY after this point
  │            │            └─ Cross-exam requires Phase 2 hypotheses
  │            └─ Hypotheses require Phase 1 normalised events       
  └─ Must complete before any inference work begins
```

**There is no shortcut.** A visualisation of unreconciled data is worse than no visualisation. The mathematical reconciliation (Phases 1–3) must pass all acceptance criteria before any presentation work begins. The demo (Phase 4) is the *last* thing built because it requires everything beneath it to be proven correct.

---

## Appendix A: New Database Schema

```sql
-- Phase 1: Telemetry storage
CREATE TABLE telemetry_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    zone TEXT,
    event_type TEXT NOT NULL,  -- 'flow', 'syscall', 'mitre_label'
    timestamp TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,    -- Full event content
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes for reconciliation queries
    CONSTRAINT idx_telemetry_instance_zone CREATE INDEX ON telemetry_events(instance_id, zone),
    CONSTRAINT idx_telemetry_type_time CREATE INDEX ON telemetry_events(event_type, timestamp)
);

-- Phase 1: CMDB snapshots
CREATE TABLE cmdb_snapshots (
    snapshot_id TEXT PRIMARY KEY,  -- SHA256
    tenant_id TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    entity_count INT NOT NULL,
    edge_count INT NOT NULL,
    payload JSONB NOT NULL         -- Full snapshot
);

-- Phase 1: Ghost masks
CREATE TABLE ghost_masks (
    mask_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id TEXT NOT NULL,
    zone TEXT,
    reason TEXT NOT NULL,
    change_ref UUID,               -- FK to change_schedule
    mask_type TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);

-- Phase 1: Change schedules
CREATE TABLE change_schedule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id TEXT NOT NULL,
    zone TEXT NOT NULL,
    change_type TEXT NOT NULL,
    scheduled_start TIMESTAMPTZ,
    scheduled_end TIMESTAMPTZ,
    status TEXT DEFAULT 'scheduled',
    source TEXT DEFAULT 'synthetic'
);

-- Phase 2: Edge hypotheses
CREATE TABLE edge_hypotheses (
    hypothesis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    from_entity_id TEXT NOT NULL,
    to_entity_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'candidate',
    confidence FLOAT NOT NULL DEFAULT 0.0,
    confidence_components JSONB,
    evidence_bundle JSONB NOT NULL DEFAULT '[]',
    policy_decision TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_evidence_at TIMESTAMPTZ,
    state_transitions JSONB DEFAULT '[]',
    
    CONSTRAINT idx_hypothesis_state CREATE INDEX ON edge_hypotheses(state),
    CONSTRAINT idx_hypothesis_confidence CREATE INDEX ON edge_hypotheses(confidence)
);

-- Phase 2: Abeyance memory
CREATE TABLE abeyance_items (
    item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence JSONB NOT NULL,
    unresolved_entity TEXT NOT NULL,
    resolution_hints JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    ttl_days INT DEFAULT 30,
    resolution_attempts INT DEFAULT 0,
    resolved BOOLEAN DEFAULT FALSE
);

-- Phase 3: Cross-examination results
CREATE TABLE cross_exam_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    input_id TEXT NOT NULL,
    input_type TEXT NOT NULL,
    claimed_fact TEXT NOT NULL,
    verdict TEXT NOT NULL,
    telemetry_evidence JSONB,
    contradiction_detail TEXT,
    confidence FLOAT,
    action_taken TEXT NOT NULL,
    audit_trail TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Appendix B: File Manifest (New Services)

```
backend/app/adapters/
    datagerry_adapter.py          # Phase 1: CMDB sync
    casinolimit_adapter.py        # Phase 1: Telemetry parsing

backend/app/services/
    normalisation_service.py      # Phase 1: Entity/edge normalisation
    divergence_service.py         # Phase 1: Divergence report generation
    ghost_mask_service.py         # Phase 1: Topological Ghost Mask logic
    hypothesis_engine.py          # Phase 2: Edge hypothesis lifecycle
    corroboration_service.py      # Phase 2: Multi-modal noisy-OR scoring
    abeyance_memory.py            # Phase 2: Delayed evidence resolution
    cross_examination_service.py  # Phase 3: Telemetry cross-exam
    data_integrity_engine.py      # Phase 3: Anti-pollution policy enforcement

backend/app/api/
    reconciliation.py             # Phase 4: Demo API endpoints

backend/app/data/
    action_signatures.yaml        # Phase 3: Telemetry signatures per action type
    entity_mappings.yaml          # Phase 1: Datagerry CI type → graph entity type

backend/app/cli/
    pedkai_cli.py                 # Phase 4: CLI interface for demo

backend/app/policies/
    global_policies.yaml          # Extended with data_integrity_policies section
```
