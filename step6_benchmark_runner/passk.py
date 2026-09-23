"""Aggregate repeated Step 6 benchmark runs into Pass^k reliability metrics.

Pass^k here means all k runs must solve the same test case. This differs from
coding-benchmark pass@k, where any one successful run is enough.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

MIN_SCORE = 0.0
MAX_SCORE = 1.0
EVALUATION_ERRORS = {
    "judge_batch_failed", "missing_evaluation", "judge_output_off_schema",
    "judge_uncertain", "scoring_input_invalid",
}

SCORE_MAP = {
    "CORRECT": 1.0,
    "VERIFIED": 1.0,
    "PARTIAL": 0.5,
    "FLAGGED": 0.5,
    "INCORRECT": 0.0,
    "FAILED": 0.0,
    "FAIL": 0.0,
    "REJECTED": 0.0,
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def case_id(case: dict[str, Any]) -> str:
    return str(case.get("test_case_id") or case.get("id") or "")


def normalize_score(value: Any, *, context: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{context} score_value must be numeric, not boolean")
    if isinstance(value, (int, float)):
        score = float(value)
    elif isinstance(value, str):
        try:
            score = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{context} has invalid score_value {value!r}") from exc
    else:
        raise ValueError(f"{context} has missing score_value")

    if not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"{context} score_value {score} is outside 0..1")
    return score


def score_value(evaluation: dict[str, Any]) -> float:
    tid = case_id(evaluation) or "<unknown>"
    context = f"evaluation {tid}"
    raw = evaluation.get("score_value")
    if raw is not None:
        return normalize_score(raw, context=context)

    verdict = str(evaluation.get("score") or evaluation.get("verdict") or "")
    mapped = SCORE_MAP.get(verdict.strip().upper())
    if mapped is None:
        raise ValueError(f"{context} has no recognized score or verdict")
    return mapped


def load_evaluations(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path)
    evaluations = payload.get("evaluations", [])
    if not isinstance(evaluations, list):
        raise ValueError(f"{path} does not contain an evaluations list")

    by_id: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        if not isinstance(evaluation, dict):
            continue
        tid = case_id(evaluation)
        if not tid:
            continue
        if tid in by_id:
            raise ValueError(f"{path} contains duplicate evaluation id {tid}")
        by_id[tid] = evaluation
    if not by_id:
        raise ValueError(f"{path} has no usable evaluations")
    manifest = payload.get("metadata", {}).get("evaluation_manifest")
    if manifest is not None:
        ids = manifest.get("eligible_case_ids") if isinstance(manifest, dict) else None
        if (not isinstance(ids, list) or not all(isinstance(cid, str) for cid in ids)
                or len(set(ids)) != len(ids) or set(ids) != set(by_id)):
            raise ValueError(f"{path}: evaluations differ from the frozen manifest; rescore with original cases first")
    return by_id


def load_case_metadata(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = load_json(path)
    cases = payload.get("test_cases", [])
    if not isinstance(cases, list):
        raise ValueError(f"{path} does not contain a test_cases list")
    by_id: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        tid = case_id(case)
        if not tid:
            continue
        if tid in by_id:
            raise ValueError(f"{path} contains duplicate test case id {tid}")
        by_id[tid] = case
    return by_id


def percent(numerator: float, denominator: int) -> str:
    if denominator == 0:
        return "N/A"
    value = round((numerator / denominator) * 100, 1)
    if value.is_integer():
        return f"{int(value)}%"
    return f"{value}%"


def average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def run_accuracy(records: list[dict[str, Any]], k: int) -> list[float]:
    if not records:
        return []
    return [
        average([record["scores"][idx] for record in records])
        for idx in range(k)
    ]


def summarize_group(records: list[dict[str, Any]], k: int) -> dict[str, Any]:
    total = len(records)
    strict_count = sum(1 for record in records if record["strict_pass_k"])
    min_scores = [record["min_score"] for record in records]
    run_averages = run_accuracy(records, k)
    strict_rate = round(strict_count / total, 4) if total else 0.0
    min_score_avg = round(sum(min_scores) / total, 4) if total else 0.0
    return {
        "case_count": total,
        "strict_pass_k_count": strict_count,
        "strict_pass_k_rate": strict_rate,
        "strict_pass_k_percent": percent(strict_count, total),
        "strict_pass_k_upper_bound_percent": percent(sum(r["possible_pass_k"] for r in records), total),
        "cases_with_evaluation_errors": sum(bool(r["evaluation_error_runs"]) for r in records),
        "min_score_k_average": min_score_avg,
        "min_score_k_average_percent": percent(sum(min_scores), total),
        "average_accuracy_across_runs": (
            round(sum(run_averages) / len(run_averages), 4) if run_averages else 0.0
        ),
        "average_accuracy_across_runs_percent": (
            percent(sum(run_averages), len(run_averages)) if run_averages else "N/A"
        ),
        "worst_run_accuracy": min(run_averages) if run_averages else 0.0,
        "worst_run_accuracy_percent": (
            percent(min(run_averages), 1) if run_averages else "N/A"
        ),
    }


def summarize_runs(
    records: list[dict[str, Any]], result_paths: list[Path]
) -> list[dict[str, Any]]:
    accuracies = run_accuracy(records, len(result_paths))
    return [
        {
            "run_index": idx + 1,
            "result_file": str(path),
            "average_score": accuracy,
            "accuracy_percent": percent(accuracy, 1),
        }
        for idx, (path, accuracy) in enumerate(zip(result_paths, accuracies))
    ]


def validate_case_sets(
    run_maps: list[dict[str, dict[str, Any]]],
    paths: list[Path],
    allow_missing: bool,
) -> tuple[list[str], list[dict[str, Any]]]:
    all_ids = set().union(*(set(run_map) for run_map in run_maps))
    common_ids = set(run_maps[0])
    for run_map in run_maps[1:]:
        common_ids &= set(run_map)

    missing_cases: list[dict[str, Any]] = []
    for path, run_map in zip(paths, run_maps):
        missing = sorted(all_ids - set(run_map))
        extra = sorted(set(run_map) - common_ids)
        if missing:
            missing_cases.append({
                "run": str(path),
                "missing_test_case_ids": missing,
                "extra_test_case_ids": extra,
            })

    if missing_cases and not allow_missing:
        details = "; ".join(
            f"{m['run']} missing {len(m['missing_test_case_ids'])}"
            for m in missing_cases
        )
        raise ValueError(
            "Result files do not contain the same test_case_id set. "
            f"Use --allow-missing to score missing cases as 0. Details: {details}"
        )

    return sorted(all_ids if allow_missing else common_ids), missing_cases


def aggregate_passk(
    result_paths: list[Path],
    test_cases_path: Path | None = None,
    allow_missing: bool = False,
) -> dict[str, Any]:
    if len(result_paths) < 2:
        raise ValueError("Pass^k requires at least two result JSON files")

    run_maps = [load_evaluations(path) for path in result_paths]
    case_metadata = load_case_metadata(test_cases_path)
    aligned_ids, missing_cases = validate_case_sets(
        run_maps, result_paths, allow_missing
    )
    k = len(result_paths)

    records: list[dict[str, Any]] = []
    for tid in aligned_ids:
        evaluations = [run_map.get(tid) for run_map in run_maps]
        present_evaluations = [e for e in evaluations if e is not None]
        first = present_evaluations[0] if present_evaluations else {}
        meta = case_metadata.get(tid, {})

        versions = {
            e.get("rubric_version", "unversioned_legacy") for e in present_evaluations
        }
        if len(versions) > 1:
            raise ValueError(
                f"{tid}: cannot aggregate different rubric versions: {sorted(versions)}"
            )
        case_hashes = {
            e.get("scoring_provenance", {}).get("case_sha256")
            for e in present_evaluations
        }
        case_hashes.discard(None)
        if len(case_hashes) > 1:
            raise ValueError(
                f"{tid}: cannot aggregate different case/contract contents"
            )
        errors = [
            idx + 1
            for idx, e in enumerate(evaluations)
            if e is None or e.get("evaluation_status") in EVALUATION_ERRORS
        ]
        scores = [
            score_value(evaluation) if evaluation is not None else 0.0
            for evaluation in evaluations
        ]
        min_score = min(scores) if scores else 0.0
        typ = str(first.get("type") or meta.get("type") or "unknown")
        subtype = str(first.get("subtype") or meta.get("subtype") or "unknown")
        record = {
            "test_case_id": tid,
            "type": typ,
            "subtype": subtype,
            "scores": scores,
            "min_score": min_score,
            "rubric_version": next(iter(versions)),
            "strict_pass_k": not errors and all(score == 1.0 for score in scores),
            "possible_pass_k": all(
                score == 1.0 or idx + 1 in errors for idx, score in enumerate(scores)
            ),
            "evaluation_error_runs": errors,
            "unstable": len(set(scores)) > 1,
            "hard_failure": any(
                score == 0.0 and idx + 1 not in errors
                for idx, score in enumerate(scores)
            ),
            "missing_from_runs": [
                idx + 1
                for idx, evaluation in enumerate(evaluations)
                if evaluation is None
            ],
        }
        records.append(record)

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_subtype: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_type[record["type"]].append(record)
        if record["subtype"] != "unknown":
            by_subtype[record["subtype"]].append(record)

    summary = {
        "metadata": {
            "metric": f"Pass^{k}",
            "k": k,
            "result_files": [str(path) for path in result_paths],
            "test_cases_file": str(test_cases_path) if test_cases_path else None,
            "case_alignment": "union_missing_as_zero" if allow_missing else "exact",
            "case_count": len(records),
            "score_scale": {"minimum": MIN_SCORE, "maximum": MAX_SCORE},
            "missing_score": 0.0 if allow_missing else None,
        },
        "overall": summarize_group(records, k),
        "run_accuracy": summarize_runs(records, result_paths),
        "by_type": {
            typ: summarize_group(group, k)
            for typ, group in sorted(by_type.items())
        },
        "by_subtype": {
            subtype: summarize_group(group, k)
            for subtype, group in sorted(by_subtype.items())
        },
        "unstable_cases": [
            record for record in records if record["unstable"]
        ],
        "hard_failures": [
            record for record in records if record["hard_failure"]
        ],
        "missing_cases": missing_cases,
        "per_case": records,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results",
        type=Path,
        nargs="+",
        help="Step 6 *_benchmark_results.json files from repeated runs",
    )
    parser.add_argument(
        "--test-cases",
        type=Path,
        default=None,
        help="Optional Step 5 test case JSON for subtype metadata",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the Pass^k summary JSON",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Use union alignment and score missing cases as 0",
    )
    args = parser.parse_args()

    try:
        summary = aggregate_passk(
            args.results,
            test_cases_path=args.test_cases,
            allow_missing=args.allow_missing,
        )
    except Exception as exc:
        print(f"passk: {exc}", file=sys.stderr)
        sys.exit(1)

    text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
