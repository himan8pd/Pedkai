"""Quick exploration of CasinoLimit dataset structure."""
import zipfile
import json
import csv
import io
import os

BASE = "/Volumes/Projects/Pedkai Data Store/COMIDDS/CasinoLimit"

# 1. Check labelled_flows.zip
print("=" * 60)
print("=== labelled_flows.zip ===")
with zipfile.ZipFile(os.path.join(BASE, "labelled_flows.zip"), "r") as z:
    names = z.namelist()
    csv_files = [n for n in names if n.endswith(".csv")]
    print(f"  Total entries: {len(names)}, CSV files: {len(csv_files)}")
    for n in csv_files[:5]:
        print(f"  {n}")
    # Read first CSV sample
    if csv_files:
        with z.open(csv_files[0]) as f:
            lines = f.read().decode("utf-8").strip().split("\n")
            print(f"\n  Sample from {csv_files[0]} ({len(lines)} lines):")
            for line in lines[:3]:
                print(f"    {line[:220]}")

# 2. Check output.zip
print("\n" + "=" * 60)
print("=== output.zip ===")
with zipfile.ZipFile(os.path.join(BASE, "output.zip"), "r") as z:
    names = z.namelist()
    print(f"  Total entries: {len(names)}")
    
    # Read steps.csv
    for name in names:
        if name.endswith("steps.csv"):
            with z.open(name) as f:
                content = f.read().decode("utf-8")
                reader = csv.DictReader(io.StringIO(content))
                rows = list(reader)
                print(f"\n  steps.csv: {len(rows)} instances")
                # Count by step_count
                from collections import Counter
                step_counts = Counter(int(r["step_count"]) for r in rows)
                for sc, cnt in sorted(step_counts.items()):
                    print(f"    step_count={sc}: {cnt} instances")
                # List all instance names
                instance_names = [r["instance"] for r in rows]
                print(f"\n  Instance names (first 10): {instance_names[:10]}")
                print(f"  Total instances: {len(instance_names)}")
            break

    # Read a validation JSON
    print("\n  --- Validation sample ---")
    for name in names:
        if "validation" in name and name.endswith(".json"):
            with z.open(name) as f:
                data = json.loads(f.read())
                print(f"  {name}:")
                print(f"    {json.dumps(data, indent=2)[:400]}")
            break

    # Read a relations JSON
    print("\n  --- Relations sample ---")
    for name in names:
        if "relations" in name and name.endswith(".json"):
            with z.open(name) as f:
                data = json.loads(f.read())
                print(f"  {name}:")
                print(f"    Keys: {list(data.keys())[:10]}")
                first_key = list(data.keys())[0] if data else None
                if first_key:
                    print(f"    First entry: {json.dumps(data[first_key], indent=2)[:400]}")
            break

    # Read a system_labels JSON
    print("\n  --- System Labels sample ---")
    for name in names:
        if "system_labels" in name and name.endswith(".json"):
            with z.open(name) as f:
                data = json.loads(f.read())
                print(f"  {name}:")
                keys = list(data.keys())[:5]
                for k in keys:
                    entry = data[k]
                    print(f"    {k}: technique={entry.get('technique', '?')}")
            break

# 3. Check flows_zeek.zip (just structure)
print("\n" + "=" * 60)
print("=== flows_zeek.zip ===")
with zipfile.ZipFile(os.path.join(BASE, "flows_zeek.zip"), "r") as z:
    names = z.namelist()
    csv_files = [n for n in names if n.endswith(".csv")]
    print(f"  Total entries: {len(names)}, CSV files: {len(csv_files)}")
    # Show unique instance/machine combos
    instances = set()
    machines = set()
    for n in csv_files:
        parts = n.split("/")
        if len(parts) >= 2:
            instances.add(parts[-2] if len(parts) >= 3 else parts[-1])
            machines.add(parts[-1].replace(".csv", ""))
    print(f"  Unique instances: {len(instances)}")
    print(f"  Machine types: {machines}")
    # Sample first CSV
    if csv_files:
        with z.open(csv_files[0]) as f:
            lines = f.read().decode("utf-8").strip().split("\n")
            print(f"\n  Sample from {csv_files[0]} ({len(lines)} lines):")
            for line in lines[:3]:
                print(f"    {line[:220]}")

# 4. Check syslogs_labels.zip
print("\n" + "=" * 60)
print("=== syslogs_labels.zip ===")
with zipfile.ZipFile(os.path.join(BASE, "syslogs_labels.zip"), "r") as z:
    names = z.namelist()
    json_files = [n for n in names if n.endswith(".json")]
    print(f"  Total entries: {len(names)}, JSON files: {len(json_files)}")
    if json_files:
        with z.open(json_files[0]) as f:
            data = json.loads(f.read())
            print(f"\n  Sample from {json_files[0]}:")
            keys = list(data.keys())[:3]
            for k in keys:
                entry = data[k]
                print(f"    {k}: technique={entry.get('technique', '?')}, events={list(entry.get('auditd_events', {}).keys())}")

print("\n" + "=" * 60)
print("Dataset exploration complete.")
