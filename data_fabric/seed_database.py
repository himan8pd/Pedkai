"""
Seed Database with Sample Decision Traces

Creates realistic decision traces from either:
1. Real TeleLogs 5G data (if HuggingFace access configured)
2. Sample generated data (for quick testing)

Usage:
    python -m data_fabric.seed_database --samples 50
    python -m data_fabric.seed_database --telelogs
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_fabric.dataset_loaders import (
    SampleDataGenerator, 
    TeleLogsLoader, 
    TelelogsCoTLoader,
    G5FaultsLoader,
    SupportTicketsLoader,
    UniversalLoader
)
from data_fabric.kaggle_loader import KaggleLoader
from backend.app.core.config import get_settings


# Datasets to "cast the net wide" for Pedkai's Decision Memory
HIGH_PRIORITY_DATASETS = [
    # --- High-Fidelity 5G (Gated) ---
    {"id": "netop/TeleLogs", "split": "train"}, 
    
    # --- Western Market Alignment (US/EU Context) ---
    {"id": "mnemoraorg/telco-churn-7k", "split": "train"}, # US Provider Churn
    {"id": "muqsith123/telco-customer-churn", "split": "train"}, # Western Churn with Geo (City/Country/Lat/Long)
    {"id": "talkmap/telecom-conversation-corpus", "split": "train"}, # 200k support conversations
    
    # --- Strategic & Global Datasets ---
    {"id": "GSMA/open_telco", "split": "test"},
    {"id": "GSMA/ot_trajectories", "split": "train"},
    {"id": "AliMaatouk/TelecomTS", "split": "train"},
    
    # --- Regional High-Density Logs (Nigeria/Global Labs) ---
    {"id": "electricsheepafrica/nigerian-telecom-network-event-logs", "split": "train"},
    {"id": "electricsheepafrica/nigerian-telecom-customer-support-ticket-records", "split": "train"},
    {"id": "electricsheepafrica/nigerian-telecom-quality-of-service-metrics", "split": "train"},
    {"id": "Genteki/tau2-bench-telecom-tiny", "split": "train"},
    {"id": "Ming-secludy/telecom-customer-support-synthetic-replicas", "split": "train"},
    {"id": "Amjad123/telecom_conversations_1k", "split": "train"},
    {"id": "Agaba-Embedded4/Combined-Telecom-QnA", "split": "train"},
]

# Kaggle-specific datasets for UK/Ireland/India
KAGGLE_DATASETS = [
    # --- India (Customer Experience & Churn) ---
    {"id": "arnavr10880/voice-call-quality-customer-experience-india", "region": "IN"},
    {"id": "kiranmehta1/indian-telecom-customer-churn-prediction-dataset", "region": "IN"},
    
    # --- UK (Ofcom Broadband Performance) ---
    {"id": "qwikfix/uk-broadband-speeds-2016", "region": "UK"},
    
    # --- Global Industry Standard (Good for IE parity/baseline) ---
    {"id": "mnassrib/telecom-churn-datasets", "region": "GLOBAL"},
    {"id": "blastchar/telco-customer-churn", "region": "GLOBAL"}, # Already successful
]


async def create_decision_via_api(decision_data: dict, base_url: str = "http://localhost:8000"):
    """Create a decision trace via the API."""
    import httpx
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/api/v1/decisions/",
            json=decision_data,
            timeout=30.0,
        )
        
        if response.status_code == 201:
            return response.json()
        else:
            print(f"❌ Failed to create decision: {response.status_code} - {response.text}")
            return None


async def seed_with_samples(count: int = 50, base_url: str = "http://localhost:8000"):
    """Seed database with generated sample data."""
    print(f"🌱 Seeding database with {count} sample decision traces...\n")
    
    created = 0
    for i in range(count):
        alarm = SampleDataGenerator.generate_sample_alarm()
        decision = SampleDataGenerator.generate_sample_decision(alarm)
        
        result = await create_decision_via_api(decision, base_url)
        if result:
            created += 1
            if created % 10 == 0:
                print(f"   Created {created}/{count} decisions...")
    
    print(f"\n✅ Successfully created {created}/{count} decision traces")
    return created


async def seed_from_huggingface(dataset_id: str, loader_class, limit: int = 100, base_url: str = "http://localhost:8000", split: str = "train"):
    """Seed database from a HuggingFace dataset using a specific loader."""
    print(f"📥 Loading dataset {dataset_id} (split: {split}) from HuggingFace...")
    
    try:
        from datasets import load_dataset
        settings = get_settings()
        if settings.hf_token:
            print(f"🔑 Authentication token found (starts with: {settings.hf_token[:4]}...)")
        else:
            print("⚠️ No HF_TOKEN found in settings!")
        
        # Load the dataset
        dataset = load_dataset(dataset_id, split=split, token=settings.hf_token)
        samples = list(dataset)[:limit]
        
        print(f"🌱 Seeding database with {len(samples)} samples from {dataset_id}...\n")
        
        created = 0
        for i, sample in enumerate(samples):
            # Use specific loader to convert to decision trace
            try:
                if loader_class == UniversalLoader:
                    decision_data = loader_class.to_decision_trace(sample, dataset_id=dataset_id)
                elif hasattr(loader_class, "to_decision_trace"):
                    decision_data = loader_class.to_decision_trace(sample)
                elif hasattr(loader_class, "telelogs_to_decision_context"):
                    # Special case for the original TeleLogsLoader
                    context = loader_class.telelogs_to_decision_context(sample)
                    decision_data = {
                        "tenant_id": f"{dataset_id.split('/')[-1]}-demo",
                        "trigger_type": "symptom",
                        "trigger_id": f"SYM-{i:04d}",
                        "trigger_description": sample.get("symptom", "Network issue"),
                        "context": context,
                        "constraints": [],
                        "options_considered": [],
                        "decision_summary": "Issue detected via diagnostic logs",
                        "tradeoff_rationale": "Data-driven detection",
                        "action_taken": "Automated analysis",
                        "decision_maker": "system:loader",
                        "confidence_score": 0.9,
                        "domain": "anops",
                        "tags": [dataset_id.split("/")[-1].lower()],
                    }
                else:
                    print(f"⚠️ No known converter for {loader_class.__name__}")
                    continue

                result = await create_decision_via_api(decision_data, base_url)
                if result:
                    created += 1
                    if created % 10 == 0:
                        print(f"   Created {created}/{len(samples)} decisions...")
            except Exception as e:
                print(f"⚠️ Error processing sample {i}: {e}")
                continue
        
        print(f"\n✅ Successfully created {created}/{len(samples)} decision traces from {dataset_id}")
        return created
    
    except ImportError:
        print("❌ HuggingFace datasets library not installed.")
        print("   Run: pip install datasets")
        return 0
    except Exception as e:
        print(f"❌ Error loading dataset {dataset_id}: {e}")
        return 0


async def seed_from_kaggle(dataset_id: str, limit: int = 100, base_url: str = "http://localhost:8000"):
    """Seed database from a Kaggle dataset."""
    print(f"📥 Loading Kaggle dataset {dataset_id}...")
    
    try:
        samples = await KaggleLoader.load_dataset(dataset_id, limit=limit)
        traces = KaggleLoader.to_decision_traces(samples, dataset_id=dataset_id)
        
        print(f"🌱 Seeding database with {len(traces)} traces from Kaggle...")
        
        created = 0
        for i, trace in enumerate(traces):
            result = await create_decision_via_api(trace, base_url)
            if result:
                created += 1
                if created % 10 == 0:
                    print(f"   Created {created}/{len(traces)} decisions...")
                    
        print(f"\n✅ Successfully created {created}/{len(traces)} decision traces from Kaggle: {dataset_id}")
        return created
        
    except Exception as e:
        print(f"❌ Error loading Kaggle dataset {dataset_id}: {e}")
        return 0
       

async def main():
    parser = argparse.ArgumentParser(description="Seed Pedkai database with decision traces")
    parser.add_argument(
        "--samples",
        type=int,
        default=0,
        help="Number of sample decision traces to generate",
    )
    parser.add_argument("--telelogs", action="store_true", help="Use original TeleLogs 5G dataset")
    parser.add_argument("--cot", action="store_true", help="Use Telelogs-CoT dataset")
    parser.add_argument("--faults", action="store_true", help="Use 5G Faults dataset")
    parser.add_argument("--tickets", action="store_true", help="Use Support Tickets dataset")
    parser.add_argument("--wide-net", action="store_true", help="Ingest all high-priority datasets")
    parser.add_argument("--kaggle", type=str, help="Specific Kaggle dataset ID to load")
    parser.add_argument("--regional", action="store_true", help="Ingest all regional Kaggle datasets (IE, UK, IN)")
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Limit samples per dataset",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  Pedkai Database Seeder - Wide Net Strategy")
    print("=" * 60)
    print()
    
    if args.wide_net:
        print(f"🕸️  Casting the wide net: Ingesting {len(HIGH_PRIORITY_DATASETS)} datasets...")
        for ds in HIGH_PRIORITY_DATASETS:
            await seed_from_huggingface(ds["id"], UniversalLoader, limit=args.limit, base_url=args.url, split=ds.get("split", "train"))
            
    elif args.kaggle:
        await seed_from_kaggle(args.kaggle, limit=args.limit, base_url=args.url)
        
    elif args.regional:
        print(f"🇬🇧🇮🇪🇮🇳 Ingesting regional Kaggle datasets...")
        for ds in KAGGLE_DATASETS:
            await seed_from_kaggle(ds["id"], limit=args.limit, base_url=args.url)
            
    elif args.dataset:
        await seed_from_huggingface(args.dataset, UniversalLoader, limit=args.limit, base_url=args.url)
    elif args.cot:
        await seed_from_huggingface(TelelogsCoTLoader.DATASET_ID, TelelogsCoTLoader, limit=args.limit, base_url=args.url)
    elif args.telelogs:
        await seed_from_huggingface(TeleLogsLoader.DATASET_ID, TeleLogsLoader, limit=args.limit, base_url=args.url)
    elif args.faults:
        await seed_from_huggingface("crystalou123/5G_Faults_Full", G5FaultsLoader, limit=args.limit, base_url=args.url)
    elif args.tickets:
        await seed_from_huggingface("Hashiru11/support-tickets-telecommunication", SupportTicketsLoader, limit=args.limit, base_url=args.url)
    elif args.samples > 0:
        await seed_with_samples(count=args.samples, base_url=args.url)
    else:
        # Default: create 50 samples
        await seed_with_samples(count=50, base_url=args.url)


if __name__ == "__main__":
    asyncio.run(main())
