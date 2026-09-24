"""One preregistered repair pass based solely on case review, before answering."""

from __future__ import annotations

import argparse
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from type5_protocol.backend import infer
from type5_protocol.build_pilot import sources
from type5_protocol.expanded_pilot import INSTRUCTION, compile_family
from type5_protocol.protocol import fingerprint, validate_families


def revise(number, args):
    fid = f"F{number + 1:02d}"
    origin = Path(args.constructions)
    reviewdir = Path(args.reviews)
    work = Path(args.workdir)
    old = json.loads((origin / "constructed" / f"{fid}.json").read_text())
    paths = [reviewdir / "family_reviews" / f"{fid}.json"] + [
        reviewdir / "reviews" / f"{fid}-{v}.json" for v in ("base", "contrast")
    ]
    reviews = [json.loads(p.read_text()) for p in paths]
    if all(r["accepted"] for r in reviews):
        return old, {
            "family_id": fid,
            "revised": False,
            "source_sha256": fingerprint(old),
        }
    src = sources(number // 2, allow_rejected=True)
    original = json.loads(
        (
            origin / "construction_calls" / (old["construction_call"] + ".json")
        ).read_text()
    )["response"]
    issues = [
        {"id": p.stem, "issues": r.get("issues", r.get("review", {}).get("issues", []))}
        for p, r in zip(paths, reviews, strict=True)
    ]
    prompt = (
        INSTRUCTION
        + json.dumps(src["sources"][number % 2], ensure_ascii=False)
        + "\nONE PRE-ANSWER REPAIR PASS:\n"
        + json.dumps(
            {"previous_family": original, "review_issues": issues}, ensure_ascii=False
        )
        + """\nRepair actual case-coherence/evidence/contract defects identified by independent review. Preserve the source identity and practical goal. The fixed request timestamp is April 1 2026 at 10 AM; all logs were recorded March 31. Any event called tomorrow in the request must be April 2, while tomorrow in a March 31 log means April 1. Change all causally affected replies when a contrast changes availability. Do not create false facts to conceal uncertainty; permit a targeted question when needed. Correct obligations should admit valid alternatives without requiring every optional detail. Do not change a valid base merely because the contrast needs repair. Update the four calibration proposals if the base changes. Return a COMPLETE corrected family using the original schema. No answerer results have been collected; do not optimize difficulty or pass rates."""
    )
    calls = []
    for attempt in range(3):
        call = infer(
            prompt,
            model="gpt-5.5",
            backend="codex",
            output_dir=work / "revision_calls",
            effort="medium",
        )
        calls.append(call["cache_key"])
        try:
            out = compile_family(number, src, call["response"])
            out["construction_call"] = call["cache_key"]
            return out, {
                "family_id": fid,
                "revised": True,
                "source_sha256": fingerprint(old),
                "review_sha256": fingerprint(reviews),
                "calls": calls,
                "issues": issues,
            }
        except (ValueError, TypeError, KeyError, StopIteration) as exc:
            if attempt == 2:
                raise
            prompt += (
                "\nRepair only this schema error: "
                + str(exc)
                + "\nPrevious output:\n"
                + call["response_text"]
            )


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--constructions", default="_orchestration/type5_protocol/expanded_v1"
    )
    p.add_argument("--reviews", default="_orchestration/type5_protocol/expanded_v2")
    p.add_argument("--workdir", default="_orchestration/type5_protocol/expanded_v3")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    oldwork = Path(a.reviews)
    for name in ("review_calls", "reviews", "family_reviews"):
        shutil.copytree(oldwork / name, work / name, dirs_exist_ok=True)
    results = {}
    records = {}
    errors = []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        pending = {pool.submit(revise, n, a): n for n in range(24)}
        for f in as_completed(pending):
            n = pending[f]
            try:
                result, record = f.result()
                results[n] = result
                records[n] = record
                path = work / "constructed" / f"F{n + 1:02d}.json"
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
                print(
                    json.dumps(
                        {"family_id": f"F{n + 1:02d}", "revised": record["revised"]}
                    ),
                    flush=True,
                )
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
                StopIteration,
            ) as exc:
                errors.append({"family_id": f"F{n + 1:02d}", "error": str(exc)})
                print(json.dumps(errors[-1]), flush=True)
    report = {
        "policy": "One case-quality revision before answering. No semantic rerolls to chase approval. Still-invalid families remain excluded with reasons.",
        "records": [records[n] for n in sorted(records)],
        "errors": errors,
    }
    (work / "revision_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    if errors:
        raise SystemExit("Revision incomplete; no partial pilot released.")
    data = {
        k: [x for n in sorted(results) for x in results[n][k]]
        for k in ("episodes", "calibration", "provenance")
    }
    data["status"] = "candidate_not_human_validated"
    validate_families(data["episodes"])
    path = work / "pilot.json"
    if path.exists() and json.loads(path.read_text()) != data:
        raise ValueError("immutable revised pilot changed")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
