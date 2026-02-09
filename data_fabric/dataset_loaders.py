"""
Telco Dataset Loaders

Downloads and processes real telco datasets for Pedkai development:
1. TeleLogs 5G (HuggingFace) - 5G network KPIs and root causes
2. alarm-rca (GitHub) - Telecom alarm RCA dataset

These provide realistic data for testing decision trace capture
and similarity search functionality.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import csv

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "raw"


class TeleLogsLoader:
    """
    Loader for the TeleLogs 5G dataset from HuggingFace.
    
    Dataset: netop/TeleLogs
    Contains: 5G network data with symptoms, root causes, and KPIs
    
    To download, you need to:
    1. Create a HuggingFace account
    2. Accept the dataset terms at https://huggingface.co/datasets/netop/TeleLogs
    3. Use the HuggingFace datasets library to download
    
    Usage:
        pip install datasets
        from datasets import load_dataset
        dataset = load_dataset("netop/TeleLogs")
    """
    
    DATASET_ID = "netop/TeleLogs"
    
    # Root causes defined in TeleLogs
    ROOT_CAUSES = {
        1: "Vehicle speed exceeds 40 km/h, impacting user throughput",
        2: "Downtilt angle of serving cell too large, causing weak coverage",
        3: "Serving cell coverage distance exceeds 1 km, resulting in poor RSRP",
        4: "Non-colocated co-frequency neighboring cells cause interference",
        5: "Neighbor and serving cell have same PCI mod 30, causing interference",
        6: "Frequent handovers degrading user performance",
        7: "Misconfigured handover thresholds degrading user performance",
        8: "Average scheduled resource blocks below 160, affecting throughput",
    }
    
    @staticmethod
    async def load_from_huggingface() -> dict:
        """
        Load TeleLogs dataset from HuggingFace.
        
        Requires: pip install datasets
        """
        try:
            from datasets import load_dataset
            
            print("📥 Downloading TeleLogs from HuggingFace...")
            dataset = load_dataset("netop/TeleLogs")
            
            print(f"✅ Loaded TeleLogs: {len(dataset)} samples")
            return dataset
        
        except ImportError:
            raise ImportError(
                "Please install the datasets library: pip install datasets"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load TeleLogs: {e}")
    
    @staticmethod
    def telelogs_to_decision_context(sample: dict) -> dict:
        """
        Convert a TeleLogs sample to Pedkai decision context format.
        """
        return {
            "alarm_ids": [],  # TeleLogs uses symptoms, not alarms
            "ticket_ids": [],
            "affected_entities": [
                f"gnodeb-{sample.get('serving_cell_id', 'unknown')}"
            ],
            "kpi_snapshot": {
                "throughput_mbps": sample.get("throughput_mbps"),
                "latency_ms": None,
                "packet_loss_pct": None,
                "availability_pct": None,
                "custom_metrics": {
                    "rsrp": sample.get("rsrp"),
                    "sinr": sample.get("sinr"),
                    "vehicle_speed_kmh": sample.get("speed"),
                    "resource_blocks": sample.get("rb_allocation"),
                }
            },
            "related_decision_ids": [],
            "external_context": {
                "symptom": sample.get("symptom"),
                "root_causes": sample.get("root_causes", []),
            }
        }


class TelelogsCoTLoader:
    """
    Loader for the Telelogs-CoT dataset from HuggingFace.
    Contains Chain-of-Thought reasoning for telco RCA.
    
    Dataset: tecnicolaude/Telelogs-CoT
    """
    
    DATASET_ID = "tecnicolaude/Telelogs-CoT"
    
    @staticmethod
    def to_decision_trace(sample: dict) -> dict:
        """
        Convert a Telelogs-CoT sample to Pedkai DecisionTrace format.
        """
        return {
            "tenant_id": "telelogs-cot-demo",
            "trigger_type": "symptom",
            "trigger_id": f"COT-{sample.get('id_MD5', 'unknown')[:8]}",
            "trigger_description": sample.get("symptom", sample.get("S", "Network performance issue")),
            "context": {
                "alarm_ids": [],
                "ticket_ids": [],
                "affected_entities": [f"entity-{sample.get('c', 'unknown')}"],
                "kpi_snapshot": None,  # Data is in U/Y strings usually
                "related_decision_ids": [],
                "external_context": {
                    "engineering_params": str(sample.get("U") or ""),
                    "user_plane_data": str(sample.get("Y") or ""),
                }
            },
            "constraints": [],
            "options_considered": [], # Needs parsing from CoT if possible
            "decision_summary": f"RCA identified as {sample.get('RCA') or 'Unknown'}",
            "tradeoff_rationale": sample.get("CoT") or "Reasoning provided by Telelogs-CoT",
            "action_taken": f"Action recommended for {sample.get('RCA') or 'unidentified issue'}",
            "decision_maker": "human:expert-simulated",
            "confidence_score": 1.0,
            "domain": "anops",
            "tags": ["5g", "rca", "cot"],
        }


class SupportTicketsLoader:
    """
    Loader for support ticket datasets.
    Dataset examples: Hashiru11/support-tickets-telecommunication
    """
    
    @staticmethod
    def to_decision_trace(ticket: dict) -> dict:
        """
        Convert a support ticket to Pedkai DecisionTrace format.
        """
        return {
            "tenant_id": "support-tickets-demo",
            "trigger_type": "ticket",
            "trigger_id": ticket.get("Ticket ID", ticket.get("id", "unknown")),
            "trigger_description": ticket.get("Description", ticket.get("Issue", "Support issue")),
            "context": {
                "alarm_ids": [],
                "ticket_ids": [ticket.get("Ticket ID", "unknown")],
                "affected_entities": [ticket.get("Affected Component", "telecom-service")],
                "kpi_snapshot": None,
                "related_decision_ids": [],
                "external_context": {
                    "priority": ticket.get("Priority"),
                    "category": ticket.get("Category"),
                }
            },
            "constraints": [],
            "options_considered": [],
            "decision_summary": str(ticket.get("Resolution") or ticket.get("Resolution Strategy") or "Ticket resolution in progress"),
            "tradeoff_rationale": "Resolved via standard support procedure",
            "action_taken": str(ticket.get("Action") or ticket.get("Resolution") or ticket.get("Resolution Strategy") or "Resolution pending"),
            "decision_maker": "human:support-agent",
            "confidence_score": 0.9,
            "domain": "customer-experience",
            "tags": ["ticket", ticket.get("Category", "support").lower()],
        }


class G5FaultsLoader:
    """
    Loader for 5G Fault datasets.
    Datasets: crystalou123/5G_Faults_Full, greenwich157/telco-5G-core-faults
    """
    
    @staticmethod
    def to_decision_trace(fault: dict) -> dict:
        """
        Convert a 5G fault record to Pedkai DecisionTrace format.
        """
        # Mapping depends on the specific dataset columns, but assuming standard fault format
        return {
            "tenant_id": "5g-faults-demo",
            "trigger_type": "alarm",
            "trigger_id": fault.get("alarm_id", fault.get("id", "unknown")),
            "trigger_description": fault.get("alarm_name") or fault.get("fault_name") or "5G Network Fault",
            "context": {
                "alarm_ids": [fault.get("alarm_id") or "unknown"],
                "ticket_ids": [],
                "affected_entities": [fault.get("ne_name") or fault.get("node_name") or "unknown-node"],
                "kpi_snapshot": None,
                "related_decision_ids": [],
                "external_context": {
                    "severity": fault.get("severity") or "unknown",
                    "category": fault.get("category") or "general",
                    "parameters": fault.get("parameters", {}),
                }
            },
            "constraints": [],
            "options_considered": [],
            "decision_summary": f"Fault {fault.get('alarm_name') or 'detected'} on {fault.get('ne_name') or 'unknown network element'}",
            "tradeoff_rationale": "Automated detection of network fault",
            "action_taken": "Automated diagnosis",
            "decision_maker": "system:anomaly-detector",
            "confidence_score": 0.95,
            "domain": "anops",
            "tags": ["5g", "fault", str(fault.get("severity") or "unknown").lower()],
        }


class AlarmRCALoader:
    """
    Loader for the alarm-rca dataset from GitHub.
    
    Repository: shaido987/alarm-rca
    Paper: "An Influence-based Approach for Root Cause Alarm Discovery"
    
    Contains real telecom alarm data with root cause labels.
    """
    
    REPO_URL = "https://github.com/shaido987/alarm-rca"
    DATA_URL = "https://raw.githubusercontent.com/shaido987/alarm-rca/master/data"
    
    @staticmethod
    async def download_dataset(output_dir: Optional[Path] = None) -> Path:
        """
        Download the alarm-rca dataset files.
        """
        import httpx
        
        output_dir = output_dir or DATA_DIR / "alarm-rca"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Known files in the alarm-rca dataset
        files = [
            "alarm_data.csv",
            "root_cause_labels.csv",
        ]
        
        async with httpx.AsyncClient() as client:
            for filename in files:
                url = f"{AlarmRCALoader.DATA_URL}/{filename}"
                print(f"📥 Downloading {filename}...")
                
                try:
                    response = await client.get(url, follow_redirects=True)
                    if response.status_code == 200:
                        output_path = output_dir / filename
                        output_path.write_bytes(response.content)
                        print(f"✅ Saved to {output_path}")
                    else:
                        print(f"⚠️ Could not download {filename}: {response.status_code}")
                except Exception as e:
                    print(f"❌ Error downloading {filename}: {e}")
        
        return output_dir
    
    @staticmethod
    def load_alarms_from_csv(csv_path: Path) -> list[dict]:
        """
        Load alarms from a CSV file.
        """
        alarms = []
        
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                alarms.append(row)
        
        print(f"📊 Loaded {len(alarms)} alarms from {csv_path.name}")
        return alarms
    
    @staticmethod
    def alarm_to_decision_context(alarm: dict) -> dict:
        """
        Convert an alarm record to Pedkai decision context format.
        """
        return {
            "alarm_ids": [alarm.get("alarm_id", alarm.get("id", "unknown"))],
            "ticket_ids": [],
            "affected_entities": [
                alarm.get("node_id", alarm.get("device", "unknown"))
            ],
            "kpi_snapshot": None,
            "related_decision_ids": [],
            "external_context": {
                "alarm_type": alarm.get("alarm_type", alarm.get("type")),
                "severity": alarm.get("severity"),
                "timestamp": alarm.get("timestamp"),
                "description": alarm.get("description", alarm.get("text")),
            }
        }


class SampleDataGenerator:
    """
    Generates sample decision traces from loaded datasets.
    
    Used when real datasets aren't available or for quick testing.
    Creates realistic-looking telco decision data based on common patterns.
    """
    
    SAMPLE_ALARM_TYPES = [
        "HIGH_PACKET_LOSS",
        "CELL_OUTAGE", 
        "THROUGHPUT_DEGRADATION",
        "RSRP_LOW",
        "HANDOVER_FAILURE",
        "INTERFERENCE_DETECTED",
        "CAPACITY_THRESHOLD",
        "LATENCY_HIGH",
    ]
    
    SAMPLE_ACTIONS = [
        "Traffic steering to adjacent cell",
        "Antenna tilt adjustment",
        "Power level optimization",
        "Handover threshold tuning",
        "PCI reallocation",
        "Resource block reallocation",
        "Cell restart scheduled",
        "Escalated to field team",
    ]
    
    @staticmethod
    def generate_sample_alarm() -> dict:
        """Generate a sample alarm for testing."""
        import random
        
        alarm_type = random.choice(SampleDataGenerator.SAMPLE_ALARM_TYPES)
        cell_id = f"CELL-{random.randint(1000, 9999)}"
        
        return {
            "alarm_id": f"ALM-{datetime.now().strftime('%Y%m%d')}-{random.randint(1, 9999):04d}",
            "alarm_type": alarm_type,
            "severity": random.choice(["CRITICAL", "MAJOR", "MINOR"]),
            "cell_id": cell_id,
            "timestamp": datetime.now().isoformat(),
            "description": f"{alarm_type.replace('_', ' ').title()} on {cell_id}",
        }
    
    @staticmethod
    def generate_sample_decision(alarm: dict) -> dict:
        """Generate a sample decision trace for testing."""
        import random
        
        action = random.choice(SampleDataGenerator.SAMPLE_ACTIONS)
        
        return {
            "tenant_id": "sample-telco",
            "trigger_type": "alarm",
            "trigger_id": alarm["alarm_id"],
            "trigger_description": alarm["description"],
            "context": {
                "alarm_ids": [alarm["alarm_id"]],
                "ticket_ids": [],
                "affected_entities": [alarm["cell_id"]],
                "kpi_snapshot": {
                    "throughput_mbps": random.uniform(100, 500),
                    "latency_ms": random.uniform(5, 50),
                    "packet_loss_pct": random.uniform(0, 5),
                },
                "related_decision_ids": [],
                "external_context": {},
            },
            "constraints": [
                {
                    "type": "sla",
                    "description": "Enterprise customer 99.9% uptime",
                    "severity": "hard",
                }
            ],
            "options_considered": [
                {
                    "id": "opt-1",
                    "description": action,
                    "risk_assessment": "Low risk",
                    "estimated_impact": "Should resolve in 15 minutes",
                    "was_chosen": True,
                }
            ],
            "decision_summary": f"Execute {action.lower()}",
            "tradeoff_rationale": "Minimal customer impact, quick resolution expected",
            "action_taken": action,
            "decision_maker": "system:pedkai",
            "confidence_score": random.uniform(0.7, 0.95),
            "domain": "anops",
            "tags": ["ran", alarm["alarm_type"].lower()],
        }


class UniversalLoader:
    """
    A flexible loader that uses heuristics to map arbitrary telecom datasets
    to the Pedkai DecisionTrace format.
    
    Tries to find common field patterns for triggers, context, and decisions.
    """
    
    @staticmethod
    def to_decision_trace(sample: dict, dataset_id: str = "unknown") -> dict:
        """
        Convert an arbitrary sample to Pedkai DecisionTrace format using heuristics.
        """
        # 1. Trigger Description Heuristics
        trigger_desc = (
            sample.get("description") or 
            sample.get("symptom") or 
            sample.get("issue") or 
            sample.get("event_type") or 
            sample.get("fault_name") or 
            sample.get("alarm_name") or 
            sample.get("Issue") or
            sample.get("S") or # Telelogs-CoT
            "Telecom network event"
        )
        
        # 2. Trigger Type Heuristics
        trigger_type = "manual"
        if any(k in str(sample.keys()).lower() for k in ["alarm", "fault", "evt", "event"]):
            trigger_type = "alarm"
        elif any(k in str(sample.keys()).lower() for k in ["ticket", "case", "support"]):
            trigger_type = "ticket"
        
        # 3. Affected Entities Heuristics
        entities = []
        for key in ["tower_id", "cell_id", "ne_name", "node_name", "ne_id", "entity_id", "phone_number", "customer_id", "c"]:
            val = sample.get(key)
            if val:
                entities.append(str(val))
        
        # 4. KPI Heuristics
        kpis = {}
        for key, val in sample.items():
            if any(k in key.lower() for k in ["loss", "throughput", "latency", "rsrp", "sinr", "utilization", "metric", "packet"]):
                if isinstance(val, (int, float)):
                    kpis[key] = val
        
        # 5. Decision & Rationale Heuristics
        decision_summary = (
            sample.get("resolution") or 
            sample.get("action_taken") or 
            sample.get("action") or 
            sample.get("Resolution Strategy") or
            sample.get("RCA") or
            f"Automated processing of {trigger_desc}"
        )
        
        rationale = (
            sample.get("rationale") or 
            sample.get("tradeoff") or 
            sample.get("CoT") or 
            sample.get("Resolution") or
            "Processed based on network patterns and available data."
        )
        
        action = (
            sample.get("action") or 
            sample.get("action_executed") or 
            sample.get("Resolution") or
            f"Remediation for {trigger_desc}"
        )

        return {
            "tenant_id": f"{dataset_id.split('/')[-1].lower()[:32]}-global",
            "trigger_type": trigger_type,
            "trigger_id": str(sample.get("event_id") or sample.get("ticket_id") or sample.get("id") or "EVT-UNK"),
            "trigger_description": str(trigger_desc),
            "context": {
                "alarm_ids": [str(sample.get("alarm_id"))] if sample.get("alarm_id") else [],
                "ticket_ids": [str(sample.get("ticket_id"))] if sample.get("ticket_id") else [],
                "affected_entities": entities or ["telecom-service"],
                "kpi_snapshot": {"custom_metrics": kpis} if kpis else None,
                "related_decision_ids": [],
                "external_context": {k: str(v) for k, v in sample.items() if k not in ["embedding", "id", "event_id", "ticket_id"]}
            },
            "constraints": [],
            "options_considered": [],
            "decision_summary": str(decision_summary),
            "tradeoff_rationale": str(rationale),
            "action_taken": str(action),
            "decision_maker": "system:pedkai-universal-loader",
            "confidence_score": 0.8,
            "domain": "anops" if trigger_type == "alarm" else "customer-experience",
            "tags": [dataset_id.split("/")[-1].lower(), trigger_type],
        }


# CLI for testing
if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("🔧 Pedkai Data Loader Test\n")
        
        # Generate sample data
        print("📝 Generating sample data...")
        for i in range(3):
            alarm = SampleDataGenerator.generate_sample_alarm()
            decision = SampleDataGenerator.generate_sample_decision(alarm)
            print(f"\n--- Sample {i+1} ---")
            print(f"Alarm: {alarm['alarm_id']} - {alarm['description']}")
            print(f"Action: {decision['action_taken']}")
        
        print("\n✅ Sample generation complete!")
        print("\nTo load real datasets:")
        print("  1. TeleLogs: pip install datasets && python -c \"from datasets import load_dataset; load_dataset('netop/TeleLogs')\"")
        print("  2. alarm-rca: Clone https://github.com/shaido987/alarm-rca")
    
    asyncio.run(main())
