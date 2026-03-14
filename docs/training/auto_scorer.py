#!/usr/bin/env python3
"""Auto-scorer for Pedk.ai NOC training exercises.

Usage:
    python auto_scorer.py --exercise 1 --answers trainee_answers.json
    python auto_scorer.py --exercise all --answers_dir ./trainee_submissions/
    python auto_scorer.py --exercise 1 --answers sample_answers_exercise_1.json
"""

import json
import argparse
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExerciseResult:
    exercise_id: int
    trainee_id: str
    score: int
    max_score: int
    passed: bool
    feedback: list[str]

    def to_dict(self) -> dict:
        return {
            "exercise_id": self.exercise_id,
            "trainee_id": self.trainee_id,
            "score": self.score,
            "max_score": self.max_score,
            "percentage": round(self.score / self.max_score * 100, 1) if self.max_score else 0,
            "passed": self.passed,
            "feedback": self.feedback,
        }

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        pct = round(self.score / self.max_score * 100, 1) if self.max_score else 0
        return f"Exercise {self.exercise_id} | {self.trainee_id} | {self.score}/{self.max_score} ({pct}%) | {status}"


EXPECTED_ANSWERS = {
    1: {
        "sleeping_cells": ["JKTBND001-SEC1", "BDGDGO003-SEC2"],
        "evidence_required": ["prb_utilisation_below_5pct", "sinr_degraded", "handover_success_below_80pct"],
        "max_score": 100,
        "points": {"sleeping_cells": 50, "evidence": 30, "domain_identification": 20},
    },
    2: {
        "root_cause": "transport_link_failure",
        "propagation_path": ["transport_failure", "backhaul_degradation", "ran_throughput_drop"],
        "affected_cells_count_min": 2,
        "affected_cells_count_max": 5,
        "max_score": 100,
        "points": {"root_cause": 35, "propagation_path": 35, "affected_count_in_range": 20, "timeline": 10},
    },
    3: {
        "dark_nodes": ["CELL-X001", "CELL-X002"],
        "phantom_nodes": ["CELL-P001"],
        "identity_mutations": ["CELL-M001"],
        "dark_attributes": ["CELL-DA001"],
        "max_score": 100,
        "points": {"dark_nodes": 30, "phantom_nodes": 20, "identity_mutations": 20, "dark_attributes": 15, "classification_rationale": 15},
    },
    4: {
        "ghost_masked": ["ANML-001", "ANML-002", "ANML-003"],
        "genuine_anomalies": ["ANML-004", "ANML-005"],
        "max_score": 100,
        "points": {"mask_001": 15, "mask_002": 15, "mask_003": 15, "genuine_004": 20, "genuine_005_with_cascade": 25, "reason_codes": 10},
    },
    5: {
        "conclusion": "single_root_cause_cascade",
        "root_domain": "transport",
        "root_entity": "SBYHUB001",
        "max_score": 100,
        "points": {"conclusion": 25, "root_domain": 20, "stadium_context": 15, "action_priority": 25, "causal_evidence": 15},
    },
}


def _normalise(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _set_overlap_score(actual: list, expected: list, full_points: int) -> tuple[int, str]:
    """Partial credit: proportional to correct items."""
    actual_set = {_normalise(a) for a in (actual or [])}
    expected_set = {_normalise(e) for e in expected}
    correct = len(actual_set & expected_set)
    total = len(expected_set)
    score = int(full_points * correct / total) if total else 0
    msg = f"{correct}/{total} correct items"
    return score, msg


def score_exercise(exercise_id: int, answers: dict, trainee_id: str = "unknown") -> ExerciseResult:
    """Score a trainee's answers against expected answers for the given exercise."""
    if exercise_id not in EXPECTED_ANSWERS:
        return ExerciseResult(exercise_id, trainee_id, 0, 0, False, [f"Unknown exercise {exercise_id}"])

    expected = EXPECTED_ANSWERS[exercise_id]
    max_score = expected["max_score"]
    pts = expected["points"]
    score = 0
    feedback = []

    if exercise_id == 1:
        s, msg = _set_overlap_score(answers.get("sleeping_cells", []), expected["sleeping_cells"], pts["sleeping_cells"])
        score += s
        feedback.append(f"Sleeping cell identification: {msg} (+{s}/{pts['sleeping_cells']})")
        s2, msg2 = _set_overlap_score(answers.get("evidence", []), expected["evidence_required"], pts["evidence"])
        score += s2
        feedback.append(f"Supporting evidence: {msg2} (+{s2}/{pts['evidence']})")
        if answers.get("domain_identified", "").lower() in ("ran", "radio access network"):
            score += pts["domain_identification"]
            feedback.append(f"Domain identification: correct (+{pts['domain_identification']})")
        else:
            feedback.append(f"Domain identification: incorrect (expected 'RAN') (+0/{pts['domain_identification']})")

    elif exercise_id == 2:
        if _normalise(answers.get("root_cause", "")) == _normalise(expected["root_cause"]):
            score += pts["root_cause"]
            feedback.append(f"Root cause: correct (+{pts['root_cause']})")
        else:
            feedback.append(f"Root cause: incorrect (expected '{expected['root_cause']}') (+0)")
        s, msg = _set_overlap_score(answers.get("propagation_path", []), expected["propagation_path"], pts["propagation_path"])
        score += s
        feedback.append(f"Propagation path: {msg} (+{s}/{pts['propagation_path']})")
        count = answers.get("affected_cells_count", 0)
        if expected["affected_cells_count_min"] <= count <= expected["affected_cells_count_max"]:
            score += pts["affected_count_in_range"]
            feedback.append(f"Affected cell count {count}: in range (+{pts['affected_count_in_range']})")
        else:
            feedback.append(f"Affected cell count {count}: out of range ({expected['affected_cells_count_min']}-{expected['affected_cells_count_max']}) (+0)")

    elif exercise_id == 3:
        for key in ["dark_nodes", "phantom_nodes", "identity_mutations", "dark_attributes"]:
            p = pts[key]
            s, msg = _set_overlap_score(answers.get(key, []), expected[key], p)
            score += s
            feedback.append(f"{key}: {msg} (+{s}/{p})")
        if answers.get("classification_rationale", ""):
            score += pts["classification_rationale"]
            feedback.append(f"Rationale provided (+{pts['classification_rationale']})")

    elif exercise_id == 4:
        masked = answers.get("ghost_masked", [])
        genuine = answers.get("genuine_anomalies", [])
        for anml, key in [("ANML-001", "mask_001"), ("ANML-002", "mask_002"), ("ANML-003", "mask_003")]:
            if anml in masked:
                score += pts[key]
                feedback.append(f"{anml} correctly ghost-masked (+{pts[key]})")
            else:
                feedback.append(f"{anml} should be ghost-masked (+0/{pts[key]})")
        if "ANML-004" in genuine:
            score += pts["genuine_004"]
            feedback.append(f"ANML-004 correctly identified as genuine (+{pts['genuine_004']})")
        if "ANML-005" in genuine:
            cascade = answers.get("anml_005_cascade_hypothesis", False)
            p5 = pts["genuine_005_with_cascade"]
            if cascade:
                score += p5
                feedback.append(f"ANML-005 genuine + cascade hypothesis noted (+{p5})")
            else:
                partial = p5 // 2
                score += partial
                feedback.append(f"ANML-005 genuine but cascade hypothesis missing (+{partial}/{p5})")
        if len(answers.get("reason_codes", {})) >= 3:
            score += pts["reason_codes"]
            feedback.append(f"Reason codes provided (+{pts['reason_codes']})")

    elif exercise_id == 5:
        if _normalise(answers.get("conclusion", "")) in ("single_root_cause_cascade", "single_root_cause", "cascade"):
            score += pts["conclusion"]
            feedback.append(f"Conclusion correct (+{pts['conclusion']})")
        else:
            feedback.append(f"Conclusion incorrect (expected 'single_root_cause_cascade') (+0)")
        if _normalise(answers.get("root_domain", "")) == "transport":
            score += pts["root_domain"]
            feedback.append(f"Root domain correct (+{pts['root_domain']})")
        if answers.get("stadium_context_noted", False):
            score += pts["stadium_context"]
            feedback.append(f"Stadium context noted (+{pts['stadium_context']})")
        actions = answers.get("action_priority", [])
        if actions and _normalise(str(actions[0])) in ("transport", "sbyhub001", "hub001", "check_transport"):
            score += pts["action_priority"]
            feedback.append(f"Correct action priority (transport first) (+{pts['action_priority']})")
        if answers.get("causal_evidence_cited", False):
            score += pts["causal_evidence"]
            feedback.append(f"Causal evidence cited (+{pts['causal_evidence']})")

    passed = score >= int(max_score * 0.7)
    return ExerciseResult(exercise_id, trainee_id, score, max_score, passed, feedback)


def main():
    parser = argparse.ArgumentParser(description="Pedk.ai Training Exercise Auto-Scorer")
    parser.add_argument("--exercise", required=True, help="Exercise number (1-5) or 'all'")
    parser.add_argument("--answers", help="Path to trainee answers JSON file")
    parser.add_argument("--answers_dir", help="Directory of answer files for --exercise all")
    parser.add_argument("--trainee_id", default="unknown", help="Trainee identifier")
    args = parser.parse_args()

    if args.exercise == "all":
        if not args.answers_dir:
            print("ERROR: --answers_dir required for --exercise all", file=sys.stderr)
            sys.exit(1)
        answers_dir = Path(args.answers_dir)
        results = []
        for f in sorted(answers_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                ex_id = data.get("exercise_id", int(f.stem.split("_")[0]))
                trainee = data.get("trainee_id", f.stem)
                result = score_exercise(ex_id, data, trainee)
                results.append(result)
                print(result.summary())
            except Exception as e:
                print(f"ERROR processing {f}: {e}", file=sys.stderr)
        total = sum(r.score for r in results)
        max_t = sum(r.max_score for r in results)
        passed = sum(1 for r in results if r.passed)
        print(f"\nTotal: {total}/{max_t} | Passed: {passed}/{len(results)}")
    else:
        if not args.answers:
            print("ERROR: --answers required", file=sys.stderr)
            sys.exit(1)
        data = json.loads(Path(args.answers).read_text())
        ex_id = int(args.exercise)
        result = score_exercise(ex_id, data, args.trainee_id)
        print(result.summary())
        for line in result.feedback:
            print(f"  {line}")
        print(json.dumps(result.to_dict(), indent=2))
        sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
