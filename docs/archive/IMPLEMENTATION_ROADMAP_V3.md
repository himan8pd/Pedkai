# Pedkai V8 — Multi-Phase Implementation Roadmap

**Date:** 27 February 2026  
**Status:** Architectural Blueprint — Ready for Engineering  
**Governing Document:** `Pedkai_Vision_V8.md`  
**Revision:** V8.2 — Full Topology Reconciliation (Nodes + Edges + Identities + Mutations)

---

## Preamble: The Dark Graph — Full Topology Reconciliation

Pedkai's "Dark Graph" is not one phenomenon. It is not even limited to one kind of topology element. Discovering unknown **edges** between known nodes — connections the CMDB failed to record — is one manifestation, but far from the only one. In real telecom networks, the CMDB is wrong about the **nodes themselves**, about their **identities**, about their **attributes**, and about their **relationships**. Pedkai reconciles **all** of these discrepancies.

### What the Dark Graph Contains

The Dark Graph is any element of the real network topology that diverges from what the CMDB declares. It manifests at every level:

**Dark Nodes** — Entities that physically exist in the network and emit telemetry, but have no corresponding CI in the CMDB.
- **VNF elastic scaling:** CMDB records capacity defaults — "up to 3 NTAS servers in Cluster A: NTAS-A1, A2, A3." When the NOC authorises NTAS-A4 because all three are running at 85% capacity, the new instance starts emitting telemetry immediately. The CMDB update is forgotten. Pedkai receives data from an entity that, according to the single source of truth, does not exist.
- **Emergency hardware replacement:** A router card fails at 2am, affecting a major customer. The field engineer swaps the hardware. The new card has a different serial number. It may resume on the same IP address, or it may not, depending on the fault state. The old serial number stops transmitting; a new, unknown serial number begins. CMDB still lists the old hardware.
- **Shadow infrastructure:** An engineer sets up a test switch to diagnose an intermittent fault. Connects it to the production network "temporarily." It stays for two years. Nobody documents it.

**Phantom Nodes** — CIs that exist in the CMDB but have ceased to exist in reality.
- The replaced router card from the example above. Its CI record persists in the CMDB indefinitely. No telemetry matches it because the physical device is in a bin.
- A VNF that was scaled down 18 months ago. The CMDB capacity plan still lists it as "active." It has emitted zero telemetry since.
- A decommissioned cell site whose CMDB records were never closed because the programme that decommissioned it didn't have CMDB write access.

**Identity Mutations** — The same logical network function is now served by a different physical entity.
- The emergency hardware swap: same IP, new serial number. Or new IP AND new serial number — the engineer plugged the replacement card into a different slot.
- VNF migration: a container hosting an AMF function moves from physical host A to physical host B. The CMDB records the old host. Telemetry comes from the new one. The AMF is the same, the host is not.
- IP renumbering during a subnet migration: the CMDB records the old addressing. Telemetry shows the new.

**Dark Edges** — Connections between entities (whether known or dark) that the CMDB does not record. The most commonly discussed manifestation of the Dark Graph, but only one element of the full picture.

**Phantom Edges** — Connections declared in the CMDB that do not exist in reality. A firewall rule that was decommissioned but never removed from the CMDB. A "primary path" that hasn't carried traffic in 6 months because traffic engineering rerouted around a capacity constraint.

**Dark Attributes** — Properties of entities or connections that the CMDB records incorrectly or not at all:
- Actual subnet assignments vs. documented
- Firewall port configurations vs. what the CMDB lists
- Radio link parameters (frequency, power, tilt) adjusted in the field and never updated
- Traffic volumes and patterns that diverge from the planned capacity model

**The fundamental claim:** Pedkai reconciles ALL of these discrepancies, not merely edges between known nodes. An NTAS-A4 appearing in telemetry with no CMDB record is as much a Dark Graph element as an unrecorded SSH tunnel between two routers. A phantom CI that hasn't emitted telemetry in 18 months is as actionable as a phantom edge.

### Why the Dark Graph Exists — Three Causal Types

The topology elements above (dark nodes, phantom nodes, identity mutations, dark edges, phantom edges, dark attributes) arise from three fundamentally different causes. Each requires different evidence strategies, but all feed the same hypothesis engine.

### Dark Graph Type 1: Intrusion & Anomaly Topology
Malicious or anomalous actors traverse infrastructure in ways that no CMDB records. Lateral movement, privilege escalation, data exfiltration — these create real network edges (proved by packet flow and syscall evidence) that the CMDB has no record of. This is the cybersecurity dark graph.

**Data availability:** HIGH. CasinoLimit provides 114 campaign instances with full telemetry, syscall logs, and MITRE ATT&CK labels. This is our development proving ground.

### Dark Graph Type 2: Tribal Knowledge & Operator Behaviour
This is the more common and arguably more commercially valuable dark graph. Enterprise CMDBs are structurally incomplete not because of attackers, but because of **humans**. Engineers enter the minimum data required to raise a ticket. They maintain the real state of the network in their heads — which CIs actually depend on which, which restart sequence works, which obscure config file on which bastion host controls a cascade of downstream services. This knowledge lives in their behaviour: which tickets they open together, which CIs they check in sequence when troubleshooting, which resolution notes reference entities not listed in the ticket's affected CIs. When these engineers leave the organization, that knowledge leaves with them.

Pedkai's intent is to decipher this knowledge from **behaviour patterns** in historical tickets, changes, and incident resolutions — and fill in the CMDB blanks automatically.

**Data availability:** LOW for development. Real ticket corpora (ServiceNow, Remedy exports) are not available in our current datasets. However, CasinoLimit can be **reinterpreted** to simulate this: each campaign's sequence of commands across machines is structurally identical to an engineer's troubleshooting path across CIs. We can synthesise ticket-like artefacts from campaign steps (see §1.6).

### Dark Graph Type 3: Secure Infrastructure (Policy-Controlled)
Some CIs are protected by CyberArk, multi-layer firewalls, air-gapped networks, or physical security controls that make them invisible to telemetry. Pedkai cannot see their traffic. But it can see them *referenced* in tickets and change records — in fragments, spread across years, where each ticket divulges only need-to-know context. A firewall change ticket mentions "the vault server" without naming it. Six months later, a different team's incident note references the same IP range during a failover. A year after that, a design document attachment in a project delivery ticket contains a network diagram showing the vault's actual upstream dependencies.

No human can assemble these fragments across years of tickets into a coherent dependency map. Pedkai should be able to — but this is an **optional, policy-gated capability**. Some clients will deliberately want such data to remain undeciphered. The Constitution must be able to enforce this preference.

**Data availability:** NONE for development. This will be implemented as an architectural extension with synthetic test scenarios, policy gates, and integration points — ready to activate when real data becomes available.

### The Architectural Consequence

The reconciliation engine does not have separate pipelines per cause type or per topology element. It has **one** hypothesis engine that handles two orthogonal axes:

- **What axis** (topology element): Dark nodes, phantom nodes, identity mutations, dark edges, phantom edges, dark attributes — all pass through the same hypothesis lifecycle (CANDIDATE → CORROBORATED → ACCEPTED → INTEGRATED).
- **Why axis** (causal type): Intrusion, tribal knowledge, secure infrastructure — all contribute evidence to the same hypothesis, weighted by source type.

The noisy-OR confidence model, the multi-modal corroboration requirement, the cross-examination, and the abeyance memory all work identically whether the hypothesis is "this edge exists" or "this node exists but the CMDB doesn't know about it" or "this CI's physical identity has changed." The only differences are the **source type weight**, the **policy gate** applied at evidence intake, and the **hypothesis type** guiding what corroboration to seek.

A `NodeHypothesis` (dark node) requires evidence that the entity is real and persistent, not a transient burst. An `IdentityMutationHypothesis` requires evidence linking the old and new identities. An `EdgeHypothesis` requires evidence that both endpoints exist and communicate. All three use the same mathematical framework.

This matters commercially: Pedkai can be sold as "operational reconciliation that captures the real state of your estate" — detecting undocumented VNFs, flagging phantom CIs that waste licence fees, linking emergency hardware swaps to their predecessors — rather than "cybersecurity threat detection." The security use case demonstrates the engine's power; the operational use case pays the bills.

---

## Preamble B: The Datagerry/CasinoLimit Nexus

Before a single line of code is written, the engineering team must internalise why these two datasets are the perfect proving ground for **all three** Dark Graph types.

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

The telemetry contains the **actual topology**: machine-to-machine sessions, traversal paths, privilege escalation chains, data access patterns. These are real network edges — proved by packet flow — that the CMDB has no record of.

**The CasinoLimit Node Coverage Limitation:**
CasinoLimit has **perfect node coverage**: every machine that emits telemetry (start, bastion, meetingcam, intranet) has a corresponding NetworkZone in Datagerry. No dark nodes exist naturally. No phantom nodes exist naturally. No identity mutations occur. This is a critical gap — in real telecoms, node-level divergence is at least as common as edge-level divergence, and arguably more commercially impactful (phantom CIs waste licence fees; dark VNFs carry production traffic with no change management oversight). The solution is the same as for Types 2 and 3: **synthetic divergence scenarios** that deliberately distort the Datagerry dataset to test Pedkai's node reconciliation capability (see §1.8).

**The Four Reconciliation Theses:**

*Thesis 1 — Dark Edges (Type 1):* Datagerry says "5 independent CIs exist." CasinoLimit telemetry says "start → bastion → meetingcam → intranet is a directed dependency chain." The gap is the Dark Graph.

*Thesis 2 — Behavioural Dependencies (Type 2):* The same CasinoLimit traversal paths can be reinterpreted as "an engineer's troubleshooting journey" — SSH to bastion, check a config on meetingcam, query the database on intranet. The CMDB doesn't know this engineer always touches these four systems together. Pedkai watches the pattern and infers the operational dependency.

*Thesis 3 — Secure CI Inference (Type 3):* If we designate `intranet` as a "CyberArk-protected" CI (via policy), Pedkai loses direct telemetry access to it. But it can still see that tickets referencing `meetingcam` frequently mention database operations that only make sense if `intranet` is involved. The secure CI's existence and dependency is inferred from the shadow it casts in adjacent ticket data.

*Thesis 4 — Node Divergence (Synthetic):* If we remove `bastion` from Datagerry's CMDB, Pedkai must detect telemetry arriving from an entity that "doesn't exist." If we inject a phantom `backup` CI into Datagerry with no matching telemetry, Pedkai must flag it. If we rename `bastion` to `bastion-replacement` in telemetry while the CMDB still says `bastion`, Pedkai must hypothesise that the identity has mutated. This thesis is synthetically constructed from CasinoLimit data but maps 1:1 to the real-world scenarios of VNF scaling, emergency hardware swaps, and CMDB decay that every telecom operator faces daily.

All four theses are proved using the **same mathematical engine**. CasinoLimit is the crucible.

---

## Phase 1: The Ingestion Fabric (Weeks 1–4)

### Objective
Build the bi-directional data bridge between Datagerry's static CMDB and CasinoLimit's raw telemetry. At the end of Week 4, Pedkai can ingest both streams, normalise them into a common event schema, and produce a **Divergence Report** — a machine-generated document listing:
- Every telemetry-observed entity that has no corresponding CMDB CI (**dark nodes**)
- Every CMDB CI that has no telemetry activity (**phantom nodes**)
- Every entity whose telemetry identity doesn't match its CMDB identity (**identity mutations**)
- Every telemetry-observed dependency that has no corresponding CMDB edge (**dark edges**)
- Every CMDB-declared edge never observed in telemetry (**phantom edges**)

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

**Entity Discovery from Telemetry:**
Not every entity in telemetry will resolve to a CMDB entity. The normalisation layer must handle the residual:

1. For each flow event, attempt to resolve `src_ip` and `dst_ip` to known `NetworkEntity` records (via IP→entity mapping from CMDB snapshot)
2. If resolution **fails** — the IP/hostname has no CMDB match — emit a `TelemetryOrphan`:

```python
@dataclass(frozen=True)
class TelemetryOrphan:
    """An entity observed in telemetry that has no CMDB counterpart."""
    orphan_id: str                  # Deterministic hash of identifying attributes
    first_seen: datetime
    last_seen: datetime
    identifying_attributes: dict    # IP, hostname, serial_number, MAC — whatever telemetry provides
    observed_event_count: int       # How many telemetry events reference this entity
    observed_peers: set[str]        # Entity IDs it has communicated with (if any are known)
    candidate_ci_type: str | None   # Best guess: "ROUTER", "VNF", "SWITCH" based on behaviour
    naming_convention_match: float  # 0.0–1.0: does its hostname follow the naming pattern of known CIs?
```

3. Accumulate orphans across the full telemetry window. An orphan seen in 1 event might be noise; an orphan seen in 500 events over 3 weeks is a dark node.
4. Simultaneously, for each CMDB entity, check whether **any** telemetry event references it. Entities with zero telemetry matches are flagged as `PhantomCandidate`.
5. For each phantom candidate, correlate against orphans: does an orphan occupy the same subnet, communicate with the same peers, or follow a naming pattern suggesting it replaced the phantom? If so, emit an `IdentityMutationCandidate`.

```python
@dataclass(frozen=True)
class PhantomCandidate:
    """A CMDB entity with zero telemetry corroboration."""
    entity_id: str
    cmdb_ci_type: str
    last_cmdb_modified: datetime
    telemetry_event_count: int      # 0 by definition
    observation_window_days: int
    potential_successor: str | None # orphan_id if identity mutation suspected

@dataclass(frozen=True)
class IdentityMutationCandidate:
    """A suspected identity change: old CMDB entity → new telemetry entity."""
    phantom_entity_id: str          # The CMDB entity that stopped transmitting
    orphan_id: str                  # The telemetry entity that appeared
    mutation_evidence: dict         # {same_subnet: bool, same_peers: bool, timing_overlap: bool, naming_similarity: float}
    confidence: float               # Pre-hypothesis rough score
```

These three outputs — `TelemetryOrphan`, `PhantomCandidate`, `IdentityMutationCandidate` — feed directly into the Divergence Report alongside the edge-level results.

### 1.4 — The Divergence Report (Weeks 3–4)

This is the Week 4 deliverable that proves commercial value to a CIO without installing a single agent.

**Algorithm:**

```
CMDB_Entities = dagerry_snapshot.entities                # ~710 entities
CMDB_Edges = dagerry_snapshot.declared_edges             # Currently: ∅ (empty)
Observed_Entities = extract_entities(telemetry_events)   # Entities seen in telemetry
Observed_Edges = aggregate(flow_events, by=(src, dst))   # ~N edges per instance

# ═══ NODE-LEVEL DIVERGENCE ═══

# DARK NODES: In telemetry, absent from CMDB
dark_nodes = Observed_Entities - CMDB_Entities           # Entities sending telemetry with no CI

# PHANTOM NODES: In CMDB, absent from telemetry
phantom_nodes = CMDB_Entities - Observed_Entities        # CIs that emit zero telemetry

# CONFIRMED NODES: Present in both
confirmed_nodes = CMDB_Entities ∩ Observed_Entities

# IDENTITY MUTATIONS: Correlated phantom/dark pairs (same subnet, peers, timing)
identity_mutations = correlate(phantom_nodes, dark_nodes, by=[subnet, peers, timing])

# ═══ EDGE-LEVEL DIVERGENCE ═══

# DARK EDGES: Observed in telemetry, absent from CMDB
dark_edges = Observed_Edges - CMDB_Edges

# PHANTOM EDGES: Declared in CMDB, never observed in telemetry
phantom_edges = CMDB_Edges - Observed_Edges

# CONFIRMED EDGES: Present in both
confirmed_edges = CMDB_Edges ∩ Observed_Edges
```

**For CasinoLimit (unmodified), the result is edge-focused:**
- `dark_nodes` = ∅ (CasinoLimit has perfect node coverage — every host is in CMDB)
- `phantom_nodes` = ∅ (every CMDB entity has corresponding telemetry)
- `identity_mutations` = ∅ (no naming/identity discrepancies)
- `dark_edges` ≈ **all inter-zone connections** (start→bastion SSH, bastion→meetingcam exploit, meetingcam→intranet DB access). The CMDB knows nothing about these.
- `phantom_edges` = ∅ (Datagerry declares no inter-zone edges, so nothing to contradict)
- `confirmed_edges` = ∅ (Datagerry declares no edges to confirm)

**For CasinoLimit with synthetic node divergence (§1.8), the result is devastating across ALL axes.**

**Report Format:**

```json
{
  "report_id": "DIV-2026-02-26-001",
  "cmdb_snapshot_id": "sha256:abc...",
  "telemetry_window": {"from": "2024-05-17T00:00:00Z", "to": "2024-05-17T23:59:59Z"},
  "summary": {
    "total_cmdb_entities": 710,
    "total_observed_entities": 456,
    "entities_in_both": 436,
    "dark_nodes_discovered": 20,
    "phantom_nodes_flagged": 20,
    "identity_mutations_suspected": 15,
    "dark_edges_discovered": 387,
    "phantom_edges_flagged": 0,
    "confirmed_edges": 0,
    "cmdb_entity_accuracy": 0.943,
    "cmdb_edge_completeness": 0.0
  },
  "dark_nodes": [
    {
      "orphan_id": "sha256:def...",
      "identifying_attributes": {"hostname": "bastion-replacement.aeriella.local", "ip": "10.0.2.3"},
      "first_seen": "2024-05-17T14:22:01Z",
      "observed_events": 847,
      "observed_peers": ["start.aeriella.local", "meetingcam.aeriella.local"],
      "candidate_ci_type": "SWITCH",
      "naming_convention_match": 0.85,
      "potential_predecessor": "bastion.aeriella.local",
      "recommendation": "This entity has been active for the full observation window, communicates with 2 known CIs, and follows the naming convention. Likely an undocumented replacement or scaling event. Create CI."
    }
  ],
  "phantom_nodes": [
    {
      "entity_id": "bastion.aeriella.local",
      "cmdb_ci_type": "NetworkZone",
      "last_cmdb_modified": "2024-03-01T00:00:00Z",
      "telemetry_events": 0,
      "observation_window_days": 30,
      "potential_successor": "bastion-replacement.aeriella.local",
      "recommendation": "Zero telemetry in 30-day window. Potential identity mutation detected (successor: bastion-replacement). Review for decommission or identity update."
    }
  ],
  "identity_mutations": [
    {
      "old_entity": "bastion.aeriella.local",
      "new_entity": "bastion-replacement.aeriella.local",
      "evidence": {"same_subnet": true, "same_peers": true, "timing_correlation": 0.95, "naming_similarity": 0.85},
      "confidence": 0.88,
      "recommendation": "High-confidence identity mutation. Old CI ceased transmitting when new entity appeared. Same subnet, same communication peers. Recommend CMDB identity update, not new CI creation."
    }
  ],
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
  "recommendation": "387 functional dependencies exist in production that your CMDB does not track. 20 entities emit telemetry with no CMDB record. 20 CMDB entities have no telemetry presence. 15 suspected hardware/identity changes were never documented. Your CMDB is structurally incomplete at BOTH the entity and relationship level."
}
```

**The CIO pitch:** "We ran Pedkai offline against your historical logs and your existing CMDB export. We found 387 dependencies your CMDB doesn't know about, 20 devices transmitting with no CI record, and 15 hardware swaps nobody documented. Zero agents. Zero network changes. Here's the proof."

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
| P1.7 | Synthetic ticket generator produces ≥114 tickets (one per campaign) with correct CI sequences | Assert `len(tickets) >= 114` and `touched_cis` order matches campaign step order |
| P1.8 | Secure CI simulation correctly blackouts telemetry for designated zones | Designate `intranet` as secure → assert zero flow/syscall events ingested for `intranet` while ticket references remain |
| P1.9 | Behavioural edge extraction identifies ≥90% of ground-truth CI sequences from synthetic tickets | Compare extracted edges against known CasinoLimit traversal paths |
| P1.10 | Dark node detection identifies 100% of synthetically removed CIs as `TelemetryOrphan` | Remove bastion from CMDB for 20 instances → assert 20 orphans emitted |
| P1.11 | Phantom node detection identifies 100% of synthetically injected CIs as `PhantomCandidate` | Inject backup CI for 20 instances → assert 20 phantom candidates emitted |
| P1.12 | Identity mutation detection correctly pairs ≥80% of renamed entities | Rename bastion→bastion-replacement for 20 instances → assert ≥16 `IdentityMutationCandidate` records with correct old→new pairing |
| P1.13 | Divergence Report includes node-level and edge-level sections | Assert report JSON has `dark_nodes`, `phantom_nodes`, `identity_mutations` AND `dark_edges` sections |

### 1.6 — Behavioural Dark Graph Synthesis from CasinoLimit (Week 4)

Real operator ticket data is not available for development. But CasinoLimit's campaign steps are structurally isomorphic to an engineer's troubleshooting path. We exploit this.

**Insight:** Each CasinoLimit campaign is a human (the CTF player) navigating a series of machines to achieve a goal. Replace "attacker" with "engineer" and "exploit" with "troubleshoot", and the behavioural pattern is identical:

| CasinoLimit Reality | Operational Reinterpretation |
|---|---|
| Player SSHs from start → bastion | Engineer accesses jump host to begin investigation |
| Player exploits bastion → meetingcam | Engineer checks application server (meetingcam hosts a video service) |
| Player queries DB on intranet | Engineer runs diagnostic query on backend database |
| Player reads admin email on intranet | Engineer retrieves config from internal system |

**Synthetic Ticket Generator:**
For each CasinoLimit campaign, generate synthetic ITSM-like artefacts:

```python
@dataclass
class SyntheticTicket:
    ticket_id: str
    instance_id: str
    created_by: str                 # Synthetic operator name (consistent per campaign)
    created_at: datetime            # Campaign start time
    affected_ci: str                # First zone touched (usually 'start')
    resolution_ci: str | None       # Last zone touched (usually 'intranet')
    touched_cis: list[str]          # Ordered list of zones accessed during campaign
    resolution_notes: str           # Synthetic text: "Accessed bastion, checked meetingcam service, restarted intranet DB"
    duration_minutes: float
    resolution_code: str            # "resolved" | "escalated" | "workaround"
```

**Generation Rules:**
1. Each campaign step becomes a "CI touch" in the ticket timeline
2. The zone order is preserved — this IS the behavioural dependency chain
3. Each campaign gets a consistent synthetic operator name (derived from instance ID) — this lets Pedkai analyse per-operator patterns
4. Resolution notes are generated from the actual auditd commands executed (replacing exploit terminology with operational terminology)
5. The `touched_cis` field is the ground truth for Behavioural Dark Graph edges — these are CIs the "operator" accessed in sequence that the CMDB doesn't know are related

**Behavioural Edge Extraction:**
From a corpus of synthetic tickets, extract behavioural edges:

```
for each ticket in corpus:
    for i in range(len(ticket.touched_cis) - 1):
        edge = (ticket.touched_cis[i], ticket.touched_cis[i+1])
        behavioural_edges[edge].frequency += 1
        behavioural_edges[edge].operators.add(ticket.created_by)
        behavioural_edges[edge].tickets.add(ticket.ticket_id)
```

An edge that appears in ≥3 tickets from ≥2 different operators is a strong behavioural signal: "Engineers consistently access these CIs together." This becomes evidence of type `operator_behaviour` in the hypothesis engine.

**Why this matters:** When Pedkai is deployed against real ServiceNow exports, the `SyntheticTicket` schema maps 1:1 to actual ITSM ticket fields. The ticket-to-behavioural-edge extraction algorithm is identical. CasinoLimit proves the math; production data provides the real signal.

### 1.7 — Secure CI Simulation Framework (Week 4)

Type 3 Dark Graph data doesn't exist in CasinoLimit. We simulate it architecturally so the engine is ready.

**Policy-Gated Telemetry Blackout:**
Designate one zone per instance (e.g., `intranet`) as a "secure CI" via policy configuration:

```yaml
# backend/app/data/secure_ci_policy.yaml

secure_ci_simulation:
  enabled: true
  blackout_zones:
    - zone: "intranet"
      security_classification: "cyberark_protected"
      telemetry_access: "denied"          # Pedkai cannot read flow/syscall data for this zone
      ticket_reference_access: "allowed"   # Pedkai CAN see this zone mentioned in tickets
      policy_override: "client_consent_required"  # Toggle via Constitution
```

**Effect on the Pipeline:**
When `intranet` is blackout-designated:
1. The CasinoLimit adapter **skips** ingestion of `syslogs/intranet/` and flow events where `dst_host = intranet`
2. Pedkai has ZERO direct telemetry for `intranet`
3. But synthetic tickets still reference `intranet` as a `touched_ci` and `resolution_ci`
4. MITRE labels that span multiple zones still mention activity "on intranet" in their description text
5. The hypothesis engine must now infer `meetingcam → intranet` using ONLY:
   - Ticket references (operator_behaviour evidence, weight 0.45)
   - Indirect flow evidence: meetingcam shows outbound flows to an IP that resolves to the intranet subnet, even though we can't see the reciprocal auditd on intranet (partial_flow evidence, weight 0.55)
   - Temporal correlation: meetingcam activity consistently precedes ticket resolution events that mention intranet

**The result:** Lower confidence than a Type 1 edge (perhaps 0.55–0.70 instead of 0.98), but still above the acceptance threshold when multiple tickets corroborate the pattern. The hypothesis will carry a `secure_ci_inference` tag indicating it was derived without full telemetry.

**Why this matters for the demo:** We can show an audience: "This edge was inferred without ever seeing the target machine's telemetry. Pedkai saw its shadow in 6 different tickets over 3 months and connected the dots."

### 1.8 — Synthetic Node Divergence from CasinoLimit (Week 4)

CasinoLimit has perfect node coverage: every machine that emits telemetry has a corresponding NetworkZone in Datagerry. Real networks do not have this luxury. To prove Pedkai's node-level reconciliation capability, we synthesise three divergence scenarios by deliberately distorting the Datagerry dataset before reconciliation.

**Scenario A: Dark Node Simulation (VNF Elastic Scaling)**
For a subset of instances (e.g., 20 of 114), remove the `bastion` NetworkZone from Datagerry before reconciliation. The telemetry still contains bastion's flows and syscalls. Pedkai must:
1. Detect telemetry from an IP/hostname that maps to no known CI
2. Emit a `TelemetryOrphan` record
3. In Phase 2, create a `NodeHypothesis` with state CANDIDATE
4. Classify as `dark_node_type = "unregistered_entity"`
5. Seek corroboration: Does the entity participate in observed edges? Is it referenced in tickets? Does its hostname follow a naming convention matching known CIs?
6. If corroborated, propose a new CI for CMDB integration

**Scenario B: Phantom Node Simulation (Decommissioned Hardware)**
For another subset (e.g., 20 instances), inject a synthetic `backup.{inst}.local` NetworkZone into Datagerry that has no corresponding telemetry. Pedkai must:
1. Detect a CMDB entity with zero telemetry matches in the observation window
2. Emit a `PhantomCandidate` record
3. In Phase 2, create a `NodeHypothesis` flagged as potential phantom
4. Cross-reference: Is this entity mentioned in any tickets? Is there a change record explaining its absence? Is there a ghost mask?
5. If no evidence of existence found after TTL (configurable, default 30 days), flag for decommission review — NOT auto-delete

**Scenario C: Identity Mutation Simulation (Emergency Hardware Swap)**
For a third subset (e.g., 20 instances), rename `bastion` to `bastion-replacement` in the telemetry while CMDB still points to `bastion`. Pedkai must:
1. Detect telemetry from `bastion-replacement` (dark node — unregistered)
2. Detect silence from `bastion` (phantom node — no telemetry)
3. Observe that `bastion-replacement` occupies the same IP range and network role as the missing `bastion`
4. Emit an `IdentityMutationCandidate` linking old to new
5. In Phase 2, corroborate via: same subnet, same traffic patterns, same connected peers, temporal correlation (old entity disappears precisely when new one appears)
6. If corroborated, propose a CMDB identity update rather than a new CI and a decommission

**Implementation:** A configuration file controls which scenarios are active:

```yaml
# backend/app/data/node_divergence_simulation.yaml

node_divergence_simulation:
  enabled: true
  scenarios:
    dark_node:
      enabled: true
      instances_affected: 20           # First 20 instances alphabetically
      zone_to_remove: "bastion"        # Remove this zone from CMDB before reconciliation
    phantom_node:
      enabled: true
      instances_affected: 20           # Next 20 instances
      phantom_zone: "backup"           # Inject this fictitious zone into CMDB
      phantom_ci_type: "NetworkZone"
      phantom_role: "backup"
    identity_mutation:
      enabled: true
      instances_affected: 20           # Next 20 instances
      original_zone: "bastion"
      mutated_name: "bastion-replacement"
      mutate_ip: false                 # Same IP, different hostname — simplest case
```

**The adapters honour this configuration:**
- `DagerryIntentAdapter`: Before producing the `CMDBSnapshot`, applies the CMDB-side mutations (remove bastion CIs for Scenario A; inject backup CIs for Scenario B)
- `CasinoLimitChaosAdapter`: Before producing telemetry events, applies the telemetry-side mutations (rename bastion to bastion-replacement in Scenario C)

**Why this matters:** Node reconciliation is what makes Pedkai credible in telecom. Edge discovery impresses security teams. Node discovery impresses operations directors — because every NOC has phantom CIs clogging their CMDB, dark VNFs carrying production traffic undocumented, and emergency hardware swaps that break the link between CMDB records and physical reality. This is the "real state of the estate" value proposition that CIOs will pay for. Demonstrating it with CasinoLimit data — even synthetically — proves the engine handles it.

### Phase 1 Non-Deliverables
- No UI, no dashboard, no visualisation
- No LLM calls
- No real-time streaming (batch-mode only)
- No autonomous actions

---

## Phase 2: Latent Topology Inference — The "Dark Graph" (Weeks 5–8)

### Objective
Transform the Divergence Report's flat lists of dark elements — dark nodes, phantom nodes, identity mutations, dark edges — into a **probabilistic graph** where every element carries a confidence score, a provenance chain, and a mathematical proof of why it should exist (or should not). By the end of Week 8, Pedkai can not only say "start connects to bastion" but explain *why* it believes this, *how confident* it is, and *what would change its mind*. And it can say "NTAS-A4 is a real, undocumented entity" or "bastion-replacement IS bastion after a hardware swap" with the same rigour.

### 2.1 — The Hypothesis Engine (Week 5)

Every dark element from Phase 1 starts as an **unverified hypothesis**. The engine handles three hypothesis types — all sharing the same lifecycle, the same noisy-OR confidence model, and the same corroboration discipline:

**Hypothesis Lifecycle (shared across all types):**

```
CANDIDATE → CORROBORATED → ACCEPTED → INTEGRATED
   ↓              ↓              ↓
DISCARDED     CONTESTED      DEGRADED
```

```python
class HypothesisState(str, Enum):
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
    
    # Dark Graph classification
    dark_graph_types: set[str]      # {"intrusion", "behavioural", "secure_ci"}
                                    # A single edge CAN belong to multiple types
                                    # e.g., a dependency found via both lateral movement AND operator tickets
    
    # Lifecycle timestamps
    created_at: datetime
    last_evidence_at: datetime
    state_transitions: list[tuple[datetime, str, str, str]]  # (when, from, to, reason)
    
    # Policy gate result (from Constitution)
    policy_decision: str | None     # "allow" | "deny" | "confirm"
    secure_ci_consent: bool         # If True, Type 3 evidence may be surfaced; if False, suppressed
    
@dataclass
class EvidenceItem:
    source_type: str                # Type 1: "network_flow" | "auditd_syscall" | "mitre_label"
                                    # Type 2: "operator_behaviour" | "resolution_note_entity_ref" | "operator_sequence"
                                    # Type 3: "ticket_fragment_reference" | "cross_ticket_temporal" | "partial_flow"
                                    # All:    "cmdb_field" | "temporal_correlation"
    source_id: str                  # Reference to raw event
    timestamp: datetime
    weight: float                   # 0.0–1.0: how much this evidence contributes
    content_hash: str               # SHA256 of evidence payload for tamper detection
    corroboration_group: str | None # Links evidence items that corroborate each other
    dark_graph_type: str | None     # "intrusion" | "behavioural" | "secure_ci" | None

# ─── Hypothesis Type 2: Node Hypotheses ───

@dataclass
class NodeHypothesis:
    """Hypothesis that an entity exists (dark node) or doesn't exist (phantom node)."""
    hypothesis_id: str
    hypothesis_subtype: str         # "dark_node" | "phantom_node"
    entity_identifier: str          # For dark: orphan_id; for phantom: CMDB entity_id
    state: HypothesisState
    
    # Entity profile (accumulated from telemetry or CMDB)
    identifying_attributes: dict    # IP, hostname, serial, MAC, naming pattern
    candidate_ci_type: str | None   # Best guess: "ROUTER", "VNF", "SWITCH", etc.
    
    # Evidence accumulator
    evidence_bundle: list[EvidenceItem]
    
    # Confidence model (same noisy-OR as EdgeHypothesis)
    confidence: float               # 0.0–1.0
    confidence_components: dict
    
    # Dark Graph classification
    dark_graph_types: set[str]      # {"intrusion", "behavioural", "secure_ci"}
    
    # For dark nodes: telemetry presence evidence
    telemetry_event_count: int      # Total events referencing this entity
    observation_span_days: float    # How long has this entity been visible?
    distinct_peers: int             # How many known entities does it communicate with?
    naming_convention_match: float  # 0.0–1.0: does its name follow known CI patterns?
    
    # For phantom nodes: absence evidence
    cmdb_last_modified: datetime | None
    days_since_last_telemetry: int | None
    
    # Lifecycle timestamps
    created_at: datetime
    last_evidence_at: datetime
    state_transitions: list[tuple[datetime, str, str, str]]
    
    # Policy gate
    policy_decision: str | None     # "create_ci" | "decommission" | "review" | "ignore"

# ─── Hypothesis Type 3: Identity Mutation Hypotheses ───

@dataclass
class IdentityMutationHypothesis:
    """Hypothesis that a phantom CMDB entity and a dark telemetry entity are the same logical function."""
    hypothesis_id: str
    old_entity_id: str              # The CMDB entity that stopped transmitting
    new_entity_identifier: str      # The telemetry orphan that appeared
    state: HypothesisState
    
    # Mutation evidence
    evidence_bundle: list[EvidenceItem]
    confidence: float
    confidence_components: dict
    
    # Correlation signals
    same_subnet: bool               # Old and new on same IP subnet?
    same_peers: bool                # Old and new communicate with same entities?
    timing_correlation: float       # 0.0–1.0: how precisely does old-disappear match new-appear?
    naming_similarity: float        # 0.0–1.0: Levenshtein or pattern-based similarity
    role_match: bool                # Same network role (e.g., both are bastion-type)?
    
    # Lifecycle timestamps
    created_at: datetime
    last_evidence_at: datetime
    state_transitions: list[tuple[datetime, str, str, str]]
    
    # Recommended action
    policy_decision: str | None     # "update_identity" | "create_new_and_decommission" | "review"
```

### 2.2 — Multi-Modal Corroboration Algorithm (Weeks 5–6)

Vision V8: *"To infer a 'Latent Edge,' Pedkai builds a probabilistic hypothesis. It swiftly seeks corroboration across disparate data sources."*

The algorithm scores each hypothesis based on how many independent data sources agree on the element's existence.

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

| Source Type | Base Weight ($w_i$) | Dark Graph Type | Rationale |
|---|---|---|---|
| `network_flow` (Zeek bidirectional) | 0.85 | Type 1 | Direct packet-level proof of communication |
| `auditd_execve` (SSH/connect syscall) | 0.75 | Type 1 | System-level proof of connection attempt |
| `mitre_label` (T1021 Remote Services) | 0.65 | Type 1 | Expert-labelled lateral movement confirmation |
| `auditd_openat` (file access on target) | 0.50 | Type 1 | Indirect: proves activity on target but not source |
| `operator_behaviour` (ticket CI co-access) | 0.45 | Type 2 | Engineers consistently touch these CIs together |
| `resolution_note_entity_ref` (entity mentioned in notes) | 0.40 | Type 2 | Resolution text references a CI not in ticket's affected list |
| `operator_sequence` (consistent access order) | 0.35 | Type 2 | Same CI traversal order across multiple incidents |
| `ticket_fragment_reference` (secure CI mentioned in ticket) | 0.40 | Type 3 | Ticket references a secure CI by name/IP/alias |
| `cross_ticket_temporal` (secure CI pattern over months) | 0.35 | Type 3 | Multiple tickets over time reference the same secure CI in similar context |
| `partial_flow` (outbound flow to secure CI subnet) | 0.55 | Type 3 | One-sided flow evidence: source visible, destination behind blackout |
| `cmdb_instance_ref` (same instance group) | 0.30 | All | Weak: shared instance ≠ connectivity |
| `temporal_correlation` | 0.20 | All | Very weak: overlapping timestamps only |

**Node-Level Source Type Weights (for NodeHypothesis and IdentityMutationHypothesis):**

| Source Type | Base Weight ($w_i$) | Hypothesis Type | Rationale |
|---|---|---|---|
| `persistent_telemetry` (high event count over days/weeks) | 0.80 | Dark node | Sustained telemetry presence = real entity, not transient |
| `peer_communication` (known entities communicate with orphan) | 0.70 | Dark node | If 3 known CIs send traffic to this entity, it's real |
| `naming_convention` (hostname matches org patterns) | 0.50 | Dark node | `ntas-a4.cluster-a.corp` follows the pattern of `ntas-a1`, `ntas-a2`, `ntas-a3` |
| `ticket_reference` (entity referenced in tickets/changes) | 0.55 | Dark node | Someone raised a ticket about it — it exists |
| `telemetry_absence` (zero events in observation window) | 0.60 | Phantom node | No telemetry for 30+ days is strong phantom signal |
| `cmdb_staleness` (CI record not modified in >180 days) | 0.35 | Phantom node | Weak: some CIs are stable and rarely modified |
| `no_ticket_reference` (no tickets mention this CI) | 0.40 | Phantom node | Nothing references it — but absence ≠ proof |
| `same_subnet` (old and new share IP range) | 0.65 | Identity mutation | Same subnet = likely same physical location |
| `same_peers` (old and new communicate with identical set) | 0.75 | Identity mutation | Same communication pattern = same logical function |
| `disappear_appear_timing` (old stops when new starts) | 0.80 | Identity mutation | Strongest mutation signal: precise temporal handoff |
| `naming_similarity` (old and new names are similar) | 0.45 | Identity mutation | `bastion` → `bastion-replacement` is suspicious |
| `role_match` (same network role in topology) | 0.55 | Identity mutation | Both serve as bastion/gateway/aggregation point |

**Note on node-level corroboration:** The same multi-modal rule applies. A dark node cannot be promoted to CORROBORATED from `persistent_telemetry` alone, regardless of event count. It needs at least one other signal (peer communication, ticket reference, naming convention). This prevents Pedkai from declaring every transient DHCP lease or port scan as a real dark node.

**Note on Type 2 and Type 3 weights:** These source types carry lower individual weight than telemetry sources because they are derived from human-generated artefacts (tickets, notes) rather than machine-generated evidence (packets, syscalls). However, the noisy-OR model means that **accumulation over many tickets** can reach high confidence. An `operator_behaviour` edge seen across 15 tickets from 4 different operators will score $C(H) = 1 - (1 - 0.45)^{15} = 0.999$ from that source type alone — but still requires a second source type for promotion to CORROBORATED.

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
    
    # Stage 5: Operator Behaviour evidence — Type 2 Dark Graph
    tickets = query(synthetic_tickets,
        WHERE H.from.zone IN touched_cis AND H.to.zone IN touched_cis
        AND touched_cis.index(H.from.zone) < touched_cis.index(H.to.zone))  # Order matters
    for ticket in tickets:
        H.add_evidence(EvidenceItem(source_type='operator_behaviour', weight=0.45,
                                     specificity=0.7,  # Sequential access = moderate specificity
                                     source_id=ticket.ticket_id))
    
    # Stage 5b: Resolution note entity references
    notes = query(synthetic_tickets,
        WHERE resolution_notes REFERENCES H.to.entity_name
        AND affected_ci = H.from.zone)  # Ticket about 'from' mentions 'to' in resolution
    for note in notes:
        H.add_evidence(EvidenceItem(source_type='resolution_note_entity_ref', weight=0.40,
                                     specificity=0.5, source_id=note.ticket_id))
    
    # Stage 6: Secure CI fragment evidence — Type 3 Dark Graph
    # Only runs if target entity is NOT in telemetry blackout (policy check)
    if is_secure_ci(H.to) and policy_allows_decipherment(H.to):
        fragments = query(ticket_fragments,
            WHERE entity_hint MATCHES H.to.aliases OR subnet MATCHES H.to.subnet)
        for frag in fragments:
            H.add_evidence(EvidenceItem(source_type='ticket_fragment_reference', weight=0.40,
                                         specificity=compute_fragment_specificity(frag, H.to)))
        
        # Partial flow: outbound from source visible, destination behind blackout
        partial = query(telemetry_events,
            WHERE event_type='flow' AND src_host=H.from 
            AND dst_ip IN H.to.known_subnets AND dst_host IS NULL)  # Can't resolve to entity
        for p in partial:
            H.add_evidence(EvidenceItem(source_type='partial_flow', weight=0.55,
                                         specificity=0.6, source_id=p.id))
    
    # Compute confidence
    H.confidence = noisy_or(H.evidence_bundle)
    
    # Tag hypothesis with dark graph type(s)
    H.dark_graph_types = classify_dark_graph_types(H.evidence_bundle)
    # A single hypothesis can carry evidence from multiple types
    
    # State transition
    if H.confidence >= ACCEPTANCE_THRESHOLD:       # Default: 0.75
        if len(distinct_source_types(H)) >= 2:     # MUST have multi-modal evidence
            H.state = CORROBORATED
        else:
            H.state = CANDIDATE                    # Single-source cannot promote
    elif H.confidence < DISCARD_THRESHOLD:          # Default: 0.10
        H.state = DISCARDED
```

**Critical Rule:** A hypothesis CANNOT be promoted to `CORROBORATED` with evidence from a single source type, regardless of confidence score. If 100 network flows all say the same thing, that's still single-source. Pedkai requires at least **2 distinct source types** agreeing. This is the anti-hallucination discipline from Vision V8. This rule applies equally to edge, node, and identity mutation hypotheses.

### 2.3b — The Node Corroboration Pipeline (Week 6)

Runs in parallel with the edge corroboration pipeline. For every `TelemetryOrphan`, `PhantomCandidate`, and `IdentityMutationCandidate` from the Divergence Report:

```
# ═══ DARK NODE CORROBORATION ═══
for each orphan in divergence_report.dark_nodes:
    H = NodeHypothesis(entity_identifier=orphan.orphan_id, 
                       hypothesis_subtype="dark_node", state=CANDIDATE)
    
    # Signal 1: Telemetry persistence (is this entity sustained, not transient?)
    duration = orphan.last_seen - orphan.first_seen
    if duration > timedelta(hours=1) and orphan.observed_event_count > 10:
        H.add_evidence(EvidenceItem(source_type='persistent_telemetry', weight=0.80,
                                     specificity=min(1.0, duration.days / 7)))
    
    # Signal 2: Peer communication (do known CIs talk to this entity?)
    if len(orphan.observed_peers) >= 2:
        H.add_evidence(EvidenceItem(source_type='peer_communication', weight=0.70,
                                     specificity=min(1.0, len(orphan.observed_peers) / 5)))
    
    # Signal 3: Naming convention (does the hostname follow org patterns?)
    if orphan.naming_convention_match > 0.6:
        H.add_evidence(EvidenceItem(source_type='naming_convention', weight=0.50,
                                     specificity=orphan.naming_convention_match))
    
    # Signal 4: Ticket references (do any tickets mention this entity?)
    tickets = query(synthetic_tickets, WHERE resolution_notes REFERENCES orphan.hostname
                    OR touched_cis CONTAINS orphan.hostname)
    if tickets:
        H.add_evidence(EvidenceItem(source_type='ticket_reference', weight=0.55,
                                     specificity=0.7, count=len(tickets)))
    
    H.confidence = noisy_or(H.evidence_bundle)
    # Promote if multi-modal and above threshold

# ═══ PHANTOM NODE CORROBORATION ═══
for each phantom in divergence_report.phantom_nodes:
    H = NodeHypothesis(entity_identifier=phantom.entity_id,
                       hypothesis_subtype="phantom_node", state=CANDIDATE)
    
    # Signal 1: Telemetry absence
    if phantom.telemetry_event_count == 0 and phantom.observation_window_days >= 7:
        H.add_evidence(EvidenceItem(source_type='telemetry_absence', weight=0.60,
                                     specificity=min(1.0, phantom.observation_window_days / 30)))
    
    # Signal 2: CMDB staleness
    days_stale = (now() - phantom.last_cmdb_modified).days
    if days_stale > 180:
        H.add_evidence(EvidenceItem(source_type='cmdb_staleness', weight=0.35,
                                     specificity=min(1.0, days_stale / 365)))
    
    # Signal 3: No tickets reference it
    tickets = query(synthetic_tickets, WHERE touched_cis CONTAINS phantom.entity_id
                    OR resolution_notes REFERENCES phantom.entity_id)
    if not tickets:
        H.add_evidence(EvidenceItem(source_type='no_ticket_reference', weight=0.40,
                                     specificity=0.5))
    
    # BUT: Check ghost mask — maybe absence is expected
    if ghost_mask_active(phantom.entity_id):
        H.state = DISCARDED  # Absence is explained by planned maintenance
        continue
    
    H.confidence = noisy_or(H.evidence_bundle)

# ═══ IDENTITY MUTATION CORROBORATION ═══
for each mutation in divergence_report.identity_mutations:
    H = IdentityMutationHypothesis(
        old_entity_id=mutation.phantom_entity_id,
        new_entity_identifier=mutation.orphan_id, state=CANDIDATE)
    
    # Signal 1: Same subnet
    if mutation.mutation_evidence['same_subnet']:
        H.add_evidence(EvidenceItem(source_type='same_subnet', weight=0.65, specificity=0.8))
    
    # Signal 2: Same communication peers
    if mutation.mutation_evidence['same_peers']:
        H.add_evidence(EvidenceItem(source_type='same_peers', weight=0.75, specificity=0.9))
    
    # Signal 3: Temporal correlation  (old disappears when new appears)
    if mutation.mutation_evidence['timing_overlap']:
        H.add_evidence(EvidenceItem(source_type='disappear_appear_timing', weight=0.80,
                                     specificity=mutation.confidence))
    
    # Signal 4: Naming similarity
    if mutation.mutation_evidence['naming_similarity'] > 0.5:
        H.add_evidence(EvidenceItem(source_type='naming_similarity', weight=0.45,
                                     specificity=mutation.mutation_evidence['naming_similarity']))
    
    H.confidence = noisy_or(H.evidence_bundle)
    # If ACCEPTED: recommend CMDB identity update (not new CI + decommission)
```

**Why identity mutation matters:** Without this capability, a hardware swap produces TWO errors in the CMDB: a phantom node (the old CI that no longer exists) AND a dark node (the new entity that was never registered). Pedkai not only detects both but links them — recommending a single CMDB action (update identity) instead of two separate actions (decommission + create). This is the operational sophistication that distinguishes Pedkai from a simple telemetry-CMDB diff tool.

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

**CasinoLimit Application (Type 1):** When parsing instance `aeriella`, if a Zeek flow references IP `10.0.3.7` but the IP-to-zone mapping for that IP isn't established yet (meetingcam's subnet hasn't been resolved), the flow event goes into abeyance. When the meetingcam auditd logs are parsed and we discover that machine's IP is `10.0.3.7`, the abeyance sweep fires, attaches the flow evidence to the `bastion → meetingcam` hypothesis, and potentially promotes it.

**Operator Behaviour Application (Type 2):** A synthetic ticket from week 1 mentions that an operator accessed `meetingcam` and noted "checked upstream database" but doesn't name `intranet`. This goes into abeyance with hint `{role: "database", direction: "upstream_of_meetingcam"}`. Weeks later, another ticket explicitly names `intranet` as a database host. The sweep resolves the first ticket's evidence to `meetingcam → intranet`, adding `operator_behaviour` evidence to that hypothesis.

**Secure CI Application (Type 3):** A change record from Q1 mentions "vault server on 10.0.4.x subnet" without naming the host. The reference goes into abeyance with TTL of 365 days (reflecting the long timescales of secure infrastructure change). Eleven months later, a project delivery attachment contains a network diagram that maps 10.0.4.x to `secure-vault-01`. The sweep fires, and suddenly 11 months of fragmented references crystallise into a dependency map around `secure-vault-01`. This is the power of long-duration abeyance for Type 3 Dark Graph.

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
| P2.7 | Behavioural edges (Type 2) reach CORROBORATED with operator_behaviour + resolution_note evidence | Inject 5+ synthetic tickets with consistent CI sequence → assert edge state = CORROBORATED |
| P2.8 | Secure CI edges (Type 3) reach CORROBORATED with ticket_fragment + partial_flow evidence | Blackout `intranet`, inject ticket fragments + one-sided flows → assert edge confidence ≥ 0.55 |
| P2.9 | Secure CI decipherment is blocked when policy denies it | Set `policy_allows_decipherment: false` for `intranet` → assert zero Type 3 evidence collected, hypothesis stays CANDIDATE |
| P2.10 | Hypothesis correctly tagged with Dark Graph type(s) | Assert Type 1 edge has `dark_graph_types=["intrusion"]`, Type 2 has `["behavioural"]`, mixed has both |
| P2.11 | Dark node hypothesis reaches CORROBORATED for synthetically removed CIs | Remove bastion from CMDB → ingest telemetry → assert NodeHypothesis(dark_node) state = CORROBORATED with ≥2 source types |
| P2.12 | Phantom node hypothesis identifies synthetically injected dead CIs | Inject phantom backup CI → assert NodeHypothesis(phantom_node) reaches CORROBORATED after observation window |
| P2.13 | Identity mutation correctly links old→new entity | Rename bastion → bastion-replacement → assert IdentityMutationHypothesis confidence ≥0.75 with same_subnet + same_peers evidence |
| P2.14 | Transient telemetry orphans are NOT promoted to dark nodes | Inject a single flow event from an unknown IP → assert NodeHypothesis stays CANDIDATE or is DISCARDED (not enough evidence for multi-modal corroboration) |

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

  # Gate 4: Secure CI Decipherment Controls (Type 3 Dark Graph)
  secure_ci_policies:
    - rule_id: "SEC-001"
      name: "Secure CI Decipherment Gate"
      description: "Type 3 Dark Graph inference requires explicit client consent per CI or CI group"
      default_stance: "denied"   # Secure CIs are NOT deciphered unless explicitly allowed
      consent_granularity: "per_ci"  # Can also be 'per_ci_group', 'per_tenant', 'global'
      audit_on_attempt: true     # Log every attempt to decipher, even if denied
      
    - rule_id: "SEC-002"
      name: "Secure CI Evidence Suppression"
      description: "When decipherment is denied, ALL Type 3 evidence for that CI must be purged from working memory"
      condition: "target_ci.security_classification != 'decipherment_allowed'"
      action: "purge_evidence"
      purge_scope: "ticket_fragment_reference, cross_ticket_temporal, partial_flow"  # All Type 3 source types
      retain_in_audit: true      # The FACT that evidence was purged is logged, but content is not
      
    - rule_id: "SEC-003"
      name: "Secure CI Re-Consent Window"
      description: "If consent is revoked, previously integrated Type 3 edges are quarantined, not deleted"
      condition: "consent_revoked AND edge.dark_graph_type == 'secure_ci'"
      action: "quarantine_edge"
      quarantine_duration_days: 90  # Client has 90 days to re-consent before edge is permanently removed
      notify: "tenant_admin"
      
    - rule_id: "SEC-004"
      name: "Type 3 Evidence Never Trains LLM"
      description: "Secure CI evidence fragments must NEVER be used as training data for any model"
      condition: "source_type IN ('ticket_fragment_reference', 'cross_ticket_temporal')"
      action: "exclude_from_training"
      enforcement: "hard"  # Cannot be overridden by any other policy

  # Gate 5: Behavioural Dark Graph Operator Privacy (Type 2)
  operator_behaviour_policies:
    - rule_id: "OBP-001"
      name: "Operator Anonymisation"
      description: "Behavioural edges must not expose individual operator names in client-facing outputs"
      condition: "output_audience == 'client'"
      action: "anonymise_operators"
      anonymisation_method: "hash"  # Replace operator names with consistent hashes
      
    - rule_id: "OBP-002"
      name: "Single-Operator Risk Flag"
      description: "If >70% of behavioural evidence for an edge comes from a single operator, flag as attrition risk"
      condition: "max_operator_contribution_pct > 0.70"
      action: "flag_attrition_risk"
      alert_severity: "medium"
      rationale: "If this operator leaves, the knowledge backing this edge may become unverifiable"
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

**Title: "The Real State of Your Estate"**

**Setup:**
- Datagerry CMDB for instance `aeriella` has been modified by §1.8 synthetic node divergence:
  - `bastion` removed from CMDB (simulating VNF that scaled up undocumented)
  - `backup.aeriella.local` injected into CMDB (simulating phantom CI)
- For instance `belinda`, identity mutation active: `bastion` renamed to `bastion-replacement` in telemetry
- CMDB declares **zero** inter-zone relationships
- CasinoLimit telemetry has been ingested
- Synthetic tickets generated from campaign steps
- `intranet` designated as secure CI via policy (telemetry blackout active)

**Act 1: The Divergence (Phase 1 output)**
System displays the Divergence Report. For `aeriella`, divergence at BOTH node and edge level:

```
═══ NODE-LEVEL DIVERGENCE ═══
  DARK NODES:     1
    ⚠ bastion.aeriella.local — 847 telemetry events, 0 CMDB records
    "This entity has been sending data for 3 weeks. Your CMDB doesn't know it exists."
    
  PHANTOM NODES:  1
    👻 backup.aeriella.local — 0 telemetry events, CMDB says 'active'
    "Your CMDB lists this as a live CI. It has emitted zero telemetry in 30 days."

═══ IDENTITY MUTATIONS (cross-instance: belinda) ═══
  MUTATIONS:      1
    🔄 bastion.belinda.local → bastion-replacement.belinda.local
    "Old CI went silent. New entity appeared on same subnet, same peers. Hardware swap?"

═══ EDGE-LEVEL DIVERGENCE (aeriella) ═══
  DARK EDGES BY TYPE:
    TYPE 1 (Intrusion/Anomaly):    2 edges   [Telemetry-proved]
      start → bastion          (SSH, 47 flows, confidence: 0.981)
      bastion → meetingcam      (exploitation, 12 flows, confidence: 0.914)
    
    TYPE 2 (Operator Behaviour):   3 edges   [Ticket-derived]
      start → bastion          (co-accessed in 8 tickets by 3 operators)
      bastion → meetingcam      (sequential access in 6 tickets)
      start → meetingcam        (co-referenced in 4 resolution notes)
    
    TYPE 3 (Secure CI):            1 edge    [Fragment-inferred, policy-gated]
      meetingcam → intranet     (referenced in 5 tickets, partial flow evidence)
```

"Your CMDB knows about 5 machines. One of them is dead. One real machine isn't in your CMDB at all. Another had a hardware swap nobody documented. And zero of the connections between them are recorded. We found all of this from your existing data."

**Act 2: The Proof — Edge Evidence Stories (Phase 2 output)**

*Story A: The Telemetry Proof (Type 1)*
Drill into `start → bastion`:
- Confidence: 0.981
- Evidence: 4 items from 3 source types (network_flow, auditd_execve, mitre_label)
- Full noisy-OR derivation visible

"The packets prove it. Three independent data sources agree."

*Story B: The Tribal Knowledge Proof (Type 2)*
Show the same `start → bastion` edge, but now from behavioural evidence:
- 8 synthetic tickets show operators accessing `start` then `bastion` in sequence
- 3 different operators exhibit the same pattern
- Resolution notes on tickets about `start` mention bastion config 4 times
- Behavioural confidence alone: 0.87

"Your senior engineer Alice always checked bastion after start. She left 6 months ago. Her knowledge is now in the graph."

*Story C: The Shadow Proof (Type 3)*
Show `meetingcam → intranet`:
- Pedkai has ZERO telemetry for `intranet` (secure CI blackout)
- But 5 tickets reference database operations on intranet when resolving meetingcam issues
- Partial flow evidence: meetingcam has outbound connections to intranet's subnet
- Confidence: 0.63 (lower, but above threshold with multi-source corroboration)

"We never saw the target machine. But we saw its shadow in your tickets. For clients who want this invisible, one policy flag disables it."

**Act 3: The Node Discovery (Phase 2 node hypotheses)**

*Story D: The Undocumented VNF (Dark Node)*
Show bastion for instance `aeriella`:
- CMDB has no record of this entity
- But 847 telemetry events reference it over 3 weeks
- 2 known CIs (start, meetingcam) communicate with it regularly
- Its hostname follows the naming convention of other NetworkZones
- NodeHypothesis confidence: 0.91 (persistent_telemetry + peer_communication + naming_convention)

"This machine has been carrying production traffic for 3 weeks. Your CMDB says it doesn't exist. In a real NOC, this is the VNF that someone authorised at 2am and forgot to register."

*Story E: The Ghost in the CMDB (Phantom Node)*
Show backup for instance `aeriella`:
- CMDB says "active"
- Zero telemetry events in 30-day observation window
- Zero tickets reference it
- NodeHypothesis confidence: 0.72 (telemetry_absence + no_ticket_reference)

"Your CMDB says this is a live asset. You're probably paying a licence fee for it. It hasn't done anything in a month. In a real network, this is the decommissioned hardware nobody removed from the CMDB."

*Story F: The Midnight Swap (Identity Mutation — cross-instance `belinda`)*
Show bastion vs. bastion-replacement for instance `belinda`:
- Old entity: bastion.belinda.local — CMDB says active, zero telemetry
- New entity: bastion-replacement.belinda.local — 600+ events, no CMDB record
- Same subnet (10.0.2.x), same peers (start, meetingcam), old disappeared when new appeared
- IdentityMutationHypothesis confidence: 0.88

"A field engineer swapped the hardware at 3am. The old serial number is dead. The new one is alive. Without Pedkai, your CMDB has a phantom CI and an invisible replacement — two errors from one event. Pedkai links them and recommends a single identity update."

**Act 4: The Guard (Phase 3 output)**
Inject a false manual claim: "meetingcam connects directly to start on port 443."
- Cross-examination runs
- Verdict: CONTRADICTED
- Reason: "Zero network flows between meetingcam and start. All meetingcam outbound traffic goes to intranet (port 5432). No tickets reference this relationship. Zero corroboration across any source type."
- Input discarded, audit trail written

"An operator (or a compromised account) tried to inject a false dependency. Pedkai caught it in 200ms."

**Act 5: The Policy Toggle (Type 3 governance)**
Live: Toggle the secure CI policy for `intranet` to `decipherment_denied`.
- Re-run reconciliation
- `meetingcam → intranet` edge disappears from the graph
- Confidence drops to 0.09 (only cmdb_instance_ref remains)
- Audit trail shows: "Type 3 evidence suppressed by policy SEC-001"

"One YAML change. The edge vanishes. Your client controls what Pedkai is allowed to learn."

**Act 6: The Integration (Phase 1 + 2 combined)**
Show the reconciliation ledger:
- 3 dark edges ready for CMDB integration (2 Type 1 + 1 merged Type 1/Type 2)
- 1 Type 3 edge in "pending client consent" state
- 1 dark node ready for CI creation (bastion for aeriella)
- 1 phantom node ready for decommission review (backup for aeriella)
- 1 identity mutation ready for CI update (bastion→bastion-replacement for belinda)
- Each with full provenance chain
- "Write to Datagerry" for the consented items

"Click this button. Your CMDB just healed itself. A missing device got registered. A dead asset got flagged. A hardware swap got linked. And the knowledge that was trapped in Alice's head is now in the graph."

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
║ CMDB Entities:     4*   │  Telemetry Entities: 4                ║
║ Dark Nodes:        1    │  Phantom Nodes:      1                ║
║ Identity Mutations: 0   │  (see instance 'belinda' for example) ║
║ CMDB Edges:        0    │  Observed Edges:     3                ║
║ Dark Edges (T1):   2    │  Dark Edges (T2):    3                ║
║ Dark Edges (T3):   1    │  Phantom Edges:      0                ║
║ CMDB Accuracy:   75.0%  │  Reconciliation: CRITICAL             ║
║ * bastion missing from CMDB; backup has no telemetry            ║
╚══════════════════════════════════════════════════════════════════╝

── NODE DIVERGENCE ──

  [N1] ⚠ DARK NODE: bastion.aeriella.local
       Status: CORROBORATED (confidence: 0.91)
       Evidence: 3 source types
       ├─ persistent_telemetry: 847 events over 21 days
       ├─ peer_communication:   communicates with start, meetingcam (2 known peers)
       └─ naming_convention:    matches NetworkZone pattern (score: 0.85)
       Recommendation: CREATE CI in CMDB

  [N2] 👻 PHANTOM NODE: backup.aeriella.local
       Status: CORROBORATED (confidence: 0.72)
       Evidence: 2 source types
       ├─ telemetry_absence:    0 events in 30-day window
       └─ no_ticket_reference:  0 tickets mention this entity
       Recommendation: REVIEW FOR DECOMMISSION

── TYPE 1: INTRUSION/ANOMALY DARK EDGES (telemetry-proved) ──

  [E1] start.aeriella.local → bastion.aeriella.local
       Confidence: 0.981 (ACCEPTED)
       Evidence: 3 source types, 4 items
       ├─ network_flow:  47 SSH flows (port 22), 284KB transferred
       ├─ auditd_execve: /usr/bin/ssh executions on 'start'
       └─ mitre_label:   T1021 (Remote Services) confirmed
      
  [E2] bastion.aeriella.local → meetingcam.aeriella.local
       Confidence: 0.914 (ACCEPTED)
       Evidence: 2 source types, 3 items
       ├─ network_flow:  12 flows (port 8080), 156KB transferred
       └─ auditd_execve: exploitation binary executed on 'bastion'

── TYPE 2: OPERATOR BEHAVIOUR DARK EDGES (ticket-derived) ──

  [E3] start.aeriella.local → bastion.aeriella.local
       Confidence: 0.872 (CORROBORATED)  [Merges with Edge #E1 → combined: 0.997]
       Evidence: 2 source types, 10 items
       ├─ operator_behaviour: 8 tickets show sequential access (3 operators)
       └─ resolution_note:   4 notes on 'start' tickets reference bastion config
       ⚠ Operator 'alice_synth' contributed 5/8 tickets — single-person risk

  [E4] start.aeriella.local → meetingcam.aeriella.local
       Confidence: 0.613 (CORROBORATED)  [No Type 1 equivalent — NEW edge]
       Evidence: 2 source types, 6 items
       ├─ operator_behaviour: 4 tickets show co-access (2 operators)
       └─ resolution_note:   2 notes reference meetingcam in start context
       💡 CMDB-INVISIBLE: This dependency exists only in operator behaviour

── TYPE 3: SECURE CI DARK EDGES (fragment-inferred, policy-gated) ──

  [E5] meetingcam.aeriella.local → intranet.aeriella.local
       Confidence: 0.634 (CORROBORATED)  [🔒 Secure CI: telemetry blackout active]
       Evidence: 2 source types, 7 items
       ├─ ticket_fragment:   5 tickets reference 'intranet' database operations
       └─ partial_flow:      2 outbound flows to intranet subnet (10.0.4.x)
       🔒 Policy: SEC-001 (decipherment_allowed=true). Toggle to suppress.

GHOST MASKS ACTIVE: 0

CROSS-EXAMINATION READY.
Type 'pedkai inject --claim "..."' to test data pollution defense.
Type 'pedkai policy --set intranet.decipherment=denied' to suppress Type 3.
Type 'pedkai integrate --node N1 --action create' to register dark node in CMDB.
Type 'pedkai integrate --node N2 --action decommission-review' to flag phantom.
Type 'pedkai integrate --edge E1,E2,E3,E5' to write edges to Datagerry.
Type 'pedkai reconcile --instance belinda --verbose' to see identity mutation example.
```

### 4.4 — Demo Execution Runbook

| Step | Duration | What Happens | What the Audience Sees |
|---|---|---|---|
| 1. Show Datagerry UI | 30s | Browse CMDB. Note bastion missing, backup present. | "This is your enterprise's source of truth. Notice anything wrong?" |
| 2. Run `pedkai ingest` | 10s | Batch ingestion of telemetry + synthetic tickets. | Terminal progress bar. |
| 3. Run `pedkai reconcile` | 5s | Full Phase 1+2 pipeline executes. | Node divergence + edge report appears. |
| 4. Story D: Dark Node | 30s | Highlight bastion — 847 events, no CMDB record. | "This machine is real. Your CMDB doesn't know." |
| 5. Story E: Phantom | 20s | Highlight backup — zero telemetry. | "You're paying licence fees for a ghost." |
| 6. Story F: Mutation | 30s | Switch to instance `belinda`. Show identity link. | "Hardware swap at 3am. Pedkai linked old to new." |
| 7. Story A: Type 1 | 30s | Drill into start→bastion telemetry proof. | Noisy-OR math, 4 evidence items. |
| 8. Story B: Type 2 | 30s | Show same edge from ticket behaviour. | 8 tickets, 3 operators, "Alice left 6 months ago." |
| 9. Story C: Type 3 | 30s | Show meetingcam→intranet with telemetry blackout. | "Never saw the machine, saw its shadow." |
| 10. Run `pedkai inject` | 15s | Submit false claim "meetingcam→start on 443." | CONTRADICTED verdict with proof. |
| 11. Run `pedkai policy --set` | 10s | Toggle Type 3 decipherment off. | Edge vanishes. "One YAML change." |
| 12. Run `pedkai integrate` | 10s | Write nodes + edges to Datagerry. | "Dark node registered. Phantom flagged. Edges created." |
| 13. Refresh Datagerry | 15s | Browse CMDB. New CIs and relationships visible. | "Your CMDB just healed itself." |
| **Total** | **~4.5 min** | | |

### Phase 4 Acceptance Criteria

| # | Criterion | Measurement |
|---|---|---|
| P4.1 | End-to-end demo completes in <5 minutes | Stopwatch from first command to "CMDB healed" |
| P4.2 | Every number in the demo output is mathematically traceable | Audience can ask "why 0.981?" and get the full noisy-OR derivation live |
| P4.3 | False claim injection is detected and rejected within 500ms | Timing assertion on cross-examination response |
| P4.4 | Datagerry CMDB reflects new edges AND new CIs after integration step | REST API `GET /rest/objects/` confirms new relationships AND new entities |
| P4.5 | All three Dark Graph types are demonstrated with distinct evidence | Demo shows Type 1 (telemetry), Type 2 (behaviour), Type 3 (fragment) evidence separately |
| P4.6 | CLI output works without a web browser | Full demo executable from terminal only |
| P4.7 | Type 3 policy toggle demonstrably removes secure CI edge from graph | Before: edge visible. After policy change: edge gone. Audit trail explains why. |
| P4.8 | Type 2 edge (start→meetingcam) has NO Type 1 equivalent | Proves behavioural Dark Graph discovers edges invisible even to telemetry |
| P4.9 | Operator attrition narrative is compelling | "Alice left" scenario clearly shows knowledge capture value |
| P4.10 | Dark node (bastion) is detected, corroborated, and integratable | Demo shows: no CMDB record → 847 events → 3 evidence types → "Create CI" button |
| P4.11 | Phantom node (backup) is detected and flagged for review | Demo shows: CMDB says active → zero telemetry → "Review for decommission" |
| P4.12 | Identity mutation (belinda instance) correctly links old→new | Demo shows: old entity silent + new entity active + same subnet/peers → "Update identity" |
| P4.13 | Node integration writes new CI to Datagerry | `pedkai integrate --node N1 --action create` → verify CI exists in Datagerry REST API |

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

-- Phase 1: Synthetic tickets (Behavioural Dark Graph)
CREATE TABLE synthetic_tickets (
    ticket_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    created_by TEXT NOT NULL,       -- Synthetic operator name
    created_at TIMESTAMPTZ NOT NULL,
    affected_ci TEXT NOT NULL,
    resolution_ci TEXT,
    touched_cis JSONB NOT NULL,    -- Ordered list of zone names
    resolution_notes TEXT,
    duration_minutes FLOAT,
    resolution_code TEXT DEFAULT 'resolved'
);

-- Phase 1: Secure CI registry (Type 3 policy)
CREATE TABLE secure_ci_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    zone TEXT,
    security_classification TEXT NOT NULL,  -- 'cyberark_protected', 'air_gapped', etc.
    telemetry_access TEXT DEFAULT 'denied',
    ticket_reference_access TEXT DEFAULT 'allowed',
    decipherment_consent TEXT DEFAULT 'denied',  -- 'allowed', 'denied', 'revoked'
    consent_granted_by TEXT,
    consent_granted_at TIMESTAMPTZ,
    consent_revoked_at TIMESTAMPTZ,
    known_subnets JSONB,           -- IP ranges associated with this secure CI
    known_aliases JSONB,           -- Alternative names/references found in tickets
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Phase 2: Edge hypotheses (extended for three Dark Graph types)
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
    dark_graph_types JSONB DEFAULT '[]',   -- ["intrusion", "behavioural", "secure_ci"]
    policy_decision TEXT,
    secure_ci_consent TEXT,                -- NULL if not Type 3, else 'allowed'/'denied'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_evidence_at TIMESTAMPTZ,
    state_transitions JSONB DEFAULT '[]',
    
    CONSTRAINT idx_hypothesis_state CREATE INDEX ON edge_hypotheses(state),
    CONSTRAINT idx_hypothesis_confidence CREATE INDEX ON edge_hypotheses(confidence),
    CONSTRAINT idx_hypothesis_dg_type CREATE INDEX ON edge_hypotheses USING GIN (dark_graph_types)
);

-- Phase 2: Node hypotheses (dark nodes, phantom nodes)
CREATE TABLE node_hypotheses (
    hypothesis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    hypothesis_subtype TEXT NOT NULL,       -- 'dark_node' | 'phantom_node'
    entity_identifier TEXT NOT NULL,        -- orphan_id or CMDB entity_id
    state TEXT NOT NULL DEFAULT 'candidate',
    confidence FLOAT NOT NULL DEFAULT 0.0,
    confidence_components JSONB,
    evidence_bundle JSONB NOT NULL DEFAULT '[]',
    identifying_attributes JSONB,           -- IP, hostname, serial, MAC
    candidate_ci_type TEXT,                 -- Best guess entity type
    telemetry_event_count INT DEFAULT 0,
    observation_span_days FLOAT DEFAULT 0,
    distinct_peers INT DEFAULT 0,
    naming_convention_match FLOAT DEFAULT 0,
    dark_graph_types JSONB DEFAULT '[]',
    policy_decision TEXT,                   -- 'create_ci' | 'decommission' | 'review' | 'ignore'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_evidence_at TIMESTAMPTZ,
    state_transitions JSONB DEFAULT '[]',
    
    CONSTRAINT idx_node_hyp_subtype CREATE INDEX ON node_hypotheses(hypothesis_subtype),
    CONSTRAINT idx_node_hyp_state CREATE INDEX ON node_hypotheses(state)
);

-- Phase 2: Identity mutation hypotheses
CREATE TABLE identity_mutation_hypotheses (
    hypothesis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    old_entity_id TEXT NOT NULL,            -- CMDB entity that stopped transmitting
    new_entity_identifier TEXT NOT NULL,    -- Telemetry orphan that appeared
    state TEXT NOT NULL DEFAULT 'candidate',
    confidence FLOAT NOT NULL DEFAULT 0.0,
    confidence_components JSONB,
    evidence_bundle JSONB NOT NULL DEFAULT '[]',
    same_subnet BOOLEAN DEFAULT FALSE,
    same_peers BOOLEAN DEFAULT FALSE,
    timing_correlation FLOAT DEFAULT 0,
    naming_similarity FLOAT DEFAULT 0,
    role_match BOOLEAN DEFAULT FALSE,
    policy_decision TEXT,                   -- 'update_identity' | 'create_new_and_decommission' | 'review'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_evidence_at TIMESTAMPTZ,
    state_transitions JSONB DEFAULT '[]',
    
    CONSTRAINT idx_mutation_state CREATE INDEX ON identity_mutation_hypotheses(state)
);

-- Phase 2: Abeyance memory (extended TTL for Type 3)
CREATE TABLE abeyance_items (
    item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence JSONB NOT NULL,
    unresolved_entity TEXT NOT NULL,
    resolution_hints JSONB NOT NULL,
    dark_graph_type TEXT,           -- Determines TTL: Type 1=30d, Type 2=90d, Type 3=365d
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

-- Phase 3: Secure CI decipherment audit log
CREATE TABLE secure_ci_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,           -- 'evidence_collected', 'evidence_purged', 'consent_checked', 'inference_blocked'
    policy_rule TEXT NOT NULL,      -- Which SEC-xxx rule applied
    detail TEXT,
    performed_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Appendix B: File Manifest (New Services)

```
backend/app/adapters/
    datagerry_adapter.py          # Phase 1: CMDB sync (+ synthetic node divergence mutations)
    casinolimit_adapter.py        # Phase 1: Telemetry parsing (+ identity mutation renames)
    synthetic_ticket_generator.py  # Phase 1: Behavioural Dark Graph ticket synthesis

backend/app/services/
    normalisation_service.py      # Phase 1: Entity/edge normalisation + entity discovery
    entity_discovery_service.py   # Phase 1: TelemetryOrphan / PhantomCandidate / IdentityMutationCandidate
    divergence_service.py         # Phase 1: Divergence report generation (nodes + edges)
    ghost_mask_service.py         # Phase 1: Topological Ghost Mask logic
    behavioural_edge_extractor.py # Phase 1: Ticket → operator behaviour edges
    secure_ci_service.py          # Phase 1: Secure CI registry + telemetry blackout
    hypothesis_engine.py          # Phase 2: Edge + Node + Mutation hypothesis lifecycle
    node_hypothesis_engine.py     # Phase 2: NodeHypothesis + IdentityMutationHypothesis corroboration
    corroboration_service.py      # Phase 2: Multi-modal noisy-OR scoring (edges + nodes)
    abeyance_memory.py            # Phase 2: Delayed evidence resolution (type-aware TTL)
    cross_examination_service.py  # Phase 3: Telemetry cross-exam
    data_integrity_engine.py      # Phase 3: Anti-pollution policy enforcement
    secure_ci_policy_engine.py    # Phase 3: Type 3 consent/purge/audit enforcement

backend/app/api/
    reconciliation.py             # Phase 4: Demo API endpoints (node + edge integration)

backend/app/data/
    action_signatures.yaml        # Phase 3: Telemetry signatures per action type
    entity_mappings.yaml          # Phase 1: Datagerry CI type → graph entity type
    secure_ci_policy.yaml         # Phase 1: Secure CI simulation config
    node_divergence_simulation.yaml # Phase 1: Dark node / phantom / mutation simulation config
    operator_terminology_map.yaml # Phase 1: CasinoLimit → operational language translation

backend/app/cli/
    pedkai_cli.py                 # Phase 4: CLI interface for demo

backend/app/policies/
    global_policies.yaml          # Extended with data_integrity + secure_ci + operator_behaviour policies
```
