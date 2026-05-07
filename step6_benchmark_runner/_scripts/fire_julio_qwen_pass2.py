"""One-off: fire sonnet+opus Pass 2 against the Qwen Julio CoT Pass 1 answers.

Skips Haiku because it cannot reliably emit valid JSON at batch_size=20.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_small_model import aggregate_majority, run_pass2_via_claude

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "step6_benchmark_runner" / "data_samples" / "output_small_models"

PERSONA = "julio_simmons"
PASS1_FILE = OUT_DIR / f"{PERSONA}_pass1_ollama_cot_preserved.json"
JUDGES = ["sonnet", "opus"]


def main() -> None:
    if not PASS1_FILE.exists():
        print(f"[fail] Pass 1 file missing: {PASS1_FILE}")
        sys.exit(1)

    pass1 = json.loads(PASS1_FILE.read_text(encoding="utf-8"))
    print(f"[loaded] {PASS1_FILE.name}: {len(pass1.get('answers', []))} answers")

    per_judge: dict[str, dict] = {}
    for j in JUDGES:
        print(f"[pass2/{PERSONA}] judge={j}", flush=True)
        result = run_pass2_via_claude(PERSONA, pass1, j)
        per_judge[j] = result
        out = OUT_DIR / f"{PERSONA}_benchmark_results_qwen_cot_{j}.json"
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"[done {j}] overall={result.get('overall_accuracy')} -> {out.name}",
            flush=True,
        )

    # Two-judge band aggregation (mode of two = either; with only two judges
    # majority degenerates to "tie or both agree", so we report both columns
    # and additionally write a band file with the harsher verdict per case).
    band = aggregate_majority(per_judge, JUDGES)
    band_path = OUT_DIR / f"{PERSONA}_benchmark_results_qwen_cot_band.json"
    band_path.write_text(json.dumps(band, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[done band] overall={band.get('overall_accuracy')} -> {band_path.name}",
        flush=True,
    )


if __name__ == "__main__":
    main()
