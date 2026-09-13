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
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from step6_benchmark_runner.generator import recompute_benchmark_summary


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
    """Return the results with Type 5 fields recomputed and summaries rebuilt."""
    metadata = results.get("metadata", {}) or {}
    return recompute_benchmark_summary(
        results,
        test_cases,
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
