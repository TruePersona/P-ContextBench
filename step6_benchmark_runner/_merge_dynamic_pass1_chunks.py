"""Merge per-persona chunked Pass 1 outputs into a single answers JSON.

Reads:  step6_benchmark_runner/data_samples/output_news_dynamic_v1/_{persona}_chunks/chunk_*.json
Writes: step6_benchmark_runner/data_samples/output_news_dynamic_v1/{persona}_pass1_answers.json

Validates that the union of test_case_ids matches the stripped test cases file
(no duplicates, no missing). Does not print answer contents.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO / "step6_benchmark_runner" / "data_samples" / "input_news_dynamic_v1"
OUT_DIR = REPO / "step6_benchmark_runner" / "data_samples" / "output_news_dynamic_v1"

PERSONAS = {
    "alicia_gonzalez": "Alicia Gonzalez",
    "deeva_cintron": "Deeva Cintron",
    "julio_simmons": "Julio Simmons",
    "maria_buendia": "Maria Buendia",
    "mary_alberti": "Mary Alberti",
}


def merge_one(slug: str, name: str) -> tuple[bool, str]:
    chunks_dir = OUT_DIR / f"_{slug}_chunks"
    if not chunks_dir.exists():
        return False, f"{slug}: no chunks dir"
    chunk_files = sorted(glob.glob(str(chunks_dir / "chunk_*.json")))
    if not chunk_files:
        return False, f"{slug}: no chunk files"

    answers: list[dict] = []
    seen_ids: set[str] = set()
    for cf in chunk_files:
        d = json.loads(Path(cf).read_text(encoding="utf-8"))
        for a in d.get("answers", []):
            tcid = a.get("test_case_id")
            if tcid in seen_ids:
                continue  # dedupe if any overlap
            seen_ids.add(tcid)
            answers.append(a)

    # Load stripped test cases to check coverage and order
    tc_path = INPUT_DIR / f"{slug}_test_cases_stripped.json"
    tc = json.loads(tc_path.read_text(encoding="utf-8"))
    expected_ids = [c["id"] for c in tc.get("test_cases", [])]
    expected_set = set(expected_ids)
    missing = [i for i in expected_ids if i not in seen_ids]
    extra = [i for i in seen_ids if i not in expected_set]

    # Reorder answers by expected order (drop extras)
    by_id = {a["test_case_id"]: a for a in answers if a.get("test_case_id") in expected_set}
    ordered = [by_id[i] for i in expected_ids if i in by_id]

    raw_log_path = INPUT_DIR / f"{slug}_app_logs_raw.txt"
    raw_chars = raw_log_path.stat().st_size if raw_log_path.exists() else 0

    out = {
        "metadata": {
            "persona": name,
            "participant_id": tc.get("metadata", {}).get("participant_id", ""),
            "pass_1_date": "2026-04-27",
            "model_used": "claude-opus-4-7-subagent",
            "raw_log_token_count": raw_chars // 4,
            "cases_answered": len(ordered),
        },
        "answers": ordered,
    }

    out_path = OUT_DIR / f"{slug}_pass1_answers.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    msg = (
        f"{slug}: wrote {out_path.name} | answers={len(ordered)}/{len(expected_ids)}"
        f" missing={len(missing)} extra={len(extra)}"
    )
    if missing:
        msg += f" | missing_ids={missing[:5]}{'...' if len(missing) > 5 else ''}"
    return len(missing) == 0, msg


def main() -> int:
    rc = 0
    for slug, name in PERSONAS.items():
        ok, msg = merge_one(slug, name)
        print(("[ok] " if ok else "[partial] ") + msg)
        if not ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
