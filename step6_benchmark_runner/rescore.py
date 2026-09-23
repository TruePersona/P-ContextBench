"""Re-derive Type 5 totals and verdicts for existing benchmark results.

Applies the deterministic rules in t5_scoring to a results file that was
produced by an earlier run, without calling the judge again. Use it to bring
old results onto the current rules, or to see how far the judge's arithmetic
was from them.

    python step6_benchmark_runner/rescore.py \\
        --results step6_benchmark_runner/data_samples/{persona}_benchmark_results.json \\
        --test-cases step5_testcases_synthesis/data_samples/{persona}_test_cases.json \\
        [--pass1 step6_benchmark_runner/data_samples/{persona}_pass1_answers.json] \\
        [--output rescored.json]

Without --output the file is not written; the change counters are printed
either way.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from step6_benchmark_runner.generator import _canonical_map, recompute_benchmark_summary
from step6_benchmark_runner.t5_contract import fingerprint


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def rescore(
    results: dict[str, Any],
    test_cases: dict[str, Any],
    pass1_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rescore the original eligible population, never the unfiltered case file.

    Legacy files have no manifest: conservatively preserve recorded IDs and
    state that assumption. Their missing/excluded cases cannot be recovered
    reliably from the results alone. Neither input object is modified.
    """
    results = deepcopy(results)
    metadata = results.setdefault("metadata", {})
    case_map = _canonical_map(test_cases.get("test_cases", []), "id")
    recorded = _canonical_map(results.get("evaluations", []), "test_case_id")
    manifest = metadata.get("evaluation_manifest")
    ids = manifest["eligible_case_ids"] if manifest else list(recorded)
    if (
        not isinstance(ids, list)
        or not all(isinstance(cid, str) for cid in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Manifest eligible_case_ids must be unique strings")
    missing = sorted(set(ids) - set(case_map))
    if missing:
        raise ValueError(f"Missing test cases for original evaluated IDs: {missing}")
    if set(recorded) - set(ids):
        raise ValueError("Results contain IDs outside their frozen manifest")
    if pass1_answers is not None:
        answers = _canonical_map(pass1_answers.get("answers", []), "test_case_id")
        for cid, record in recorded.items():
            expected_hash = record.get("scoring_provenance", {}).get("answer_sha256")
            if expected_hash and (
                cid not in answers or fingerprint(answers[cid]) != expected_hash
            ):
                raise ValueError(
                    f"Pass 1 answer changed for {cid}; run a fresh judgment, not an offline rescore"
                )
    population = {**test_cases, "test_cases": [case_map[cid] for cid in ids]}
    if pass1_answers is None and any("type_5_contract" in case_map[cid] for cid in ids):
        raise ValueError(
            "Behavior contract rescoring requires the original --pass1 answers"
        )
    metadata.setdefault(
        "rescore_population_policy",
        "frozen_manifest" if manifest else "legacy_recorded_ids",
    )
    metadata["rescore_semantics"] = "reuse_original_judgments; not a fresh evaluation"
    return recompute_benchmark_summary(
        results,
        population,
        metadata.get("model_used_pass1", "unknown"),
        metadata.get("model_used_pass2", "unknown"),
        pass1_answers=pass1_answers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--test-cases", type=Path, required=True)
    parser.add_argument("--pass1", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    results = load_json(args.results)
    before = {
        "overall_accuracy": results.get("overall_accuracy"),
        "type_5": (results.get("accuracy_by_type") or {}).get("type_5_agent_behavior"),
    }
    pass1 = load_json(args.pass1) if args.pass1 else None
    rescored = rescore(results, load_json(args.test_cases), pass1)

    counters = rescored["metadata"].get("type_5_scoring", {})
    print(f"[rescore] {args.results.name}")
    for name, value in counters.items():
        print(f"  {name}: {value}")
    print(
        f"  overall_accuracy: {before['overall_accuracy']} -> "
        f"{rescored.get('overall_accuracy')}"
    )
    print(
        f"  type_5_agent_behavior: {before['type_5']} -> "
        f"{rescored.get('accuracy_by_type', {}).get('type_5_agent_behavior')}"
    )
    if args.output:
        args.output.write_text(
            json.dumps(rescored, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  wrote {args.output}")


if __name__ == "__main__":
    main()
