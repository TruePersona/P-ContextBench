"""Inventory historical review evidence without rewriting or certifying it."""

import argparse
from collections import Counter
from pathlib import Path

from pipeline_integrity.artifacts import file_digest, read_json, write_json


def audit(root):
    root = Path(root)
    totals = Counter()
    missing_by_type = Counter()
    rows = []
    for path in sorted((root / "step5_testcases_synthesis/data_samples").glob("*_test_cases.json")):
        review_path = path.with_name(
            path.name.replace("_test_cases.json", "_test_cases_verification.json")
        )
        dataset = read_json(path)
        review = read_json(review_path) if review_path.exists() else {}
        cases = {case["id"]: case for case in dataset.get("test_cases", [])}
        evaluations = review.get("evaluations", [])
        evaluations = evaluations if isinstance(evaluations, list) else []
        ids = [
            row.get("test_case_id", row.get("id")) for row in evaluations if isinstance(row, dict)
        ]
        missing = sorted(set(cases) - set(ids))
        counts = Counter(
            row.get("overall_verdict", "MISSING") for row in evaluations if isinstance(row, dict)
        )
        reported = review.get("verification_metadata", {}).get("summary", {})
        mismatch = any(
            reported.get(key) != counts.get(verdict, 0)
            for key, verdict in (
                ("verified", "VERIFIED"),
                ("flagged", "FLAGGED"),
                ("rejected", "REJECTED"),
            )
        )
        totals.update(
            files=1,
            cases=len(cases),
            evaluation_records=len(evaluations),
            missing_case_reviews=len(missing),
            incomplete_files=int(bool(missing)),
            summary_mismatch_files=int(mismatch),
        )
        for cid in missing:
            missing_by_type[cases[cid].get("type", "unknown")] += 1
        rows.append(
            {
                "cases": str(path.relative_to(root)),
                "cases_sha256": file_digest(path),
                "review_sha256": file_digest(review_path) if review_path.exists() else None,
                "status": "requires_bound_admission"
                if not review.get("admission")
                else "bound_review_present_not_revalidated",
                "missing_case_reviews": missing,
                "duplicate_review_ids": [cid for cid, count in Counter(ids).items() if count > 1],
                "unknown_review_ids": sorted(set(ids) - set(cases)),
                "summary_mismatch": mismatch,
                "recorded_verdicts": dict(counts),
                "reported_summary": reported,
            }
        )
    return {
        "scope": "Stored review evidence only; no semantic certification or score correction.",
        "counts": dict(totals),
        "missing_by_type": dict(missing_by_type),
        "personas": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root)
    write_json(args.output, result)
    print(result["counts"])


if __name__ == "__main__":
    main()
