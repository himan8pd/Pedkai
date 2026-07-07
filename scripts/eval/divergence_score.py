#!/usr/bin/env python
"""Divergence precision/recall scorer.

Computes per-type precision/recall of a pedkai divergence run against the
six_telecom divergence manifest, using edge-aware matching semantics.

Matching semantics
-------------------
- dark_node / phantom_node / dark_attribute / identity_mutation:
    match on the tuple (divergence_type, target_id).
- dark_edge:
    detected target_id is a neighbour_relations relation_id, resolved to the
    unordered pair (from_cell_id, to_cell_id); truth target_id is a
    ground_truth_relationships relationship_id, resolved to the unordered pair
    (from_entity_id, to_entity_id). Matching is on the unordered endpoint pair.
- phantom_edge:
    both detected and truth target_id are cmdb_declared_relationships
    relationship_ids, each resolved to the unordered (from_entity_id,
    to_entity_id) pair. Matching is on the unordered endpoint pair.

Ids that cannot be resolved through their mapping table are counted as
unresolved (unresolved_detected / unresolved_truth) and excluded from the
matched sets.
"""

import argparse
import json

import pandas as pd

# Types that match directly on (divergence_type, target_id).
DIRECT_TYPES = [
    "dark_node",
    "phantom_node",
    "dark_attribute",
    "identity_mutation",
]

# Edge types that require endpoint-pair resolution.
EDGE_TYPES = ["dark_edge", "phantom_edge"]

ALL_TYPES = DIRECT_TYPES + EDGE_TYPES


def _unordered_pair(a, b):
    """Return an order-independent hashable key for an endpoint pair."""
    return tuple(sorted((str(a), str(b))))


def _build_pair_map(df, id_col, from_col, to_col):
    """Map id -> unordered endpoint pair. Last write wins (ids are unique)."""
    mapping = {}
    for _id, a, b in zip(df[id_col], df[from_col], df[to_col]):
        mapping[str(_id)] = _unordered_pair(a, b)
    return mapping


def _resolve(ids, mapping):
    """Resolve a series of ids through mapping.

    Returns (resolved_pairs_set, unresolved_count).
    """
    resolved = set()
    unresolved = 0
    for _id in ids:
        key = str(_id)
        pair = mapping.get(key)
        if pair is None:
            unresolved += 1
        else:
            resolved.add(pair)
    return resolved, unresolved


def _score(detected_set, truth_set):
    tp = len(detected_set & truth_set)
    detected_n = len(detected_set)
    truth_n = len(truth_set)
    precision = tp / detected_n if detected_n else 0.0
    recall = tp / truth_n if truth_n else 0.0
    return detected_n, truth_n, tp, precision, recall


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detected", required=True,
                    help="CSV with columns divergence_type,target_id")
    ap.add_argument("--manifest", required=True,
                    help="divergence_manifest.parquet")
    ap.add_argument("--neighbour-relations", required=True,
                    help="neighbour_relations.parquet")
    ap.add_argument("--cmdb-relationships", required=True,
                    help="cmdb_declared_relationships.parquet")
    ap.add_argument("--ground-truth-relationships", required=True,
                    help="ground_truth_relationships.parquet")
    ap.add_argument("--out", required=True, help="output JSON path")
    args = ap.parse_args()

    detected = pd.read_csv(args.detected, dtype=str)
    manifest = pd.read_parquet(args.manifest)

    neighbour = pd.read_parquet(args.neighbour_relations)
    cmdb = pd.read_parquet(args.cmdb_relationships)
    gt = pd.read_parquet(args.ground_truth_relationships)

    # Resolution maps.
    #   dark_edge detected: relation_id -> (from_cell_id, to_cell_id)
    #   dark_edge truth:    relationship_id -> (from_entity_id, to_entity_id)
    #   phantom_edge both:  relationship_id -> (from_entity_id, to_entity_id)
    nbr_map = _build_pair_map(
        neighbour, "relation_id", "from_cell_id", "to_cell_id")
    gt_map = _build_pair_map(
        gt, "relationship_id", "from_entity_id", "to_entity_id")
    cmdb_map = _build_pair_map(
        cmdb, "relationship_id", "from_entity_id", "to_entity_id")

    results = {}

    for dtype in ALL_TYPES:
        det_ids = detected.loc[
            detected["divergence_type"] == dtype, "target_id"]
        truth_ids = manifest.loc[
            manifest["divergence_type"] == dtype, "target_id"]

        entry = {}

        if dtype in DIRECT_TYPES:
            detected_set = set(str(x) for x in det_ids)
            truth_set = set(str(x) for x in truth_ids)
            unresolved_det = 0
            unresolved_truth = 0
        elif dtype == "dark_edge":
            detected_set, unresolved_det = _resolve(det_ids, nbr_map)
            truth_set, unresolved_truth = _resolve(truth_ids, gt_map)
        elif dtype == "phantom_edge":
            detected_set, unresolved_det = _resolve(det_ids, cmdb_map)
            truth_set, unresolved_truth = _resolve(truth_ids, cmdb_map)
        else:  # pragma: no cover - guarded by ALL_TYPES
            continue

        detected_n, truth_n, tp, precision, recall = _score(
            detected_set, truth_set)

        entry = {
            "detected": detected_n,
            "truth": truth_n,
            "tp": tp,
            "precision": precision,
            "recall": recall,
            "unresolved_detected": unresolved_det,
            "unresolved_truth": unresolved_truth,
        }
        results[dtype] = entry

    # Overall = micro-average across all types.
    total_detected = sum(r["detected"] for r in results.values())
    total_truth = sum(r["truth"] for r in results.values())
    total_tp = sum(r["tp"] for r in results.values())
    overall = {
        "detected": total_detected,
        "truth": total_truth,
        "tp": total_tp,
        "precision": total_tp / total_detected if total_detected else 0.0,
        "recall": total_tp / total_truth if total_truth else 0.0,
        "unresolved_detected": sum(
            r["unresolved_detected"] for r in results.values()),
        "unresolved_truth": sum(
            r["unresolved_truth"] for r in results.values()),
    }
    results["overall"] = overall

    # Printed table.
    header = ("{:<20} {:>10} {:>10} {:>10} {:>10} {:>10}".format(
        "type", "detected", "truth", "TP", "precision", "recall"))
    print(header)
    print("-" * len(header))
    for dtype in ALL_TYPES + ["overall"]:
        r = results[dtype]
        print("{:<20} {:>10} {:>10} {:>10} {:>10.3f} {:>10.3f}".format(
            dtype, r["detected"], r["truth"], r["tp"],
            r["precision"], r["recall"]))

    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=2)
    print("\nWrote {}".format(args.out))


if __name__ == "__main__":
    main()
