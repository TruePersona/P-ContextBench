"""Check that reported answers and judgments match their frozen raw calls."""

import argparse
import json
from pathlib import Path

from type5_protocol.protocol import fingerprint


def audit(work, run=None):
    work = Path(work)
    issues = []
    counts = {"answers": 0, "judgments": 0, "errors": 0}
    directories = [work / "runs" / run] if run else sorted((work / "runs").glob("*"))
    for path in sorted(
        p for directory in directories for p in (directory / "answers").glob("*.json")
    ):
        row = json.loads(path.read_text())
        if row.get("error"):
            counts["errors"] += 1
            continue
        counts["answers"] += 1
        if row.get("call") is None:
            continue
        raw = work / "answer_calls" / (row["call"] + ".json")
        if not raw.exists():
            issues.append({"file": str(path), "issue": "raw answer call missing"})
            continue
        call = json.loads(raw.read_text())
        if call.get("response", {}).get("answer") != row.get("answer"):
            issues.append(
                {"file": str(path), "issue": "answer differs from frozen raw call"}
            )
        if call.get("cache_key") != row["call"] or call.get(
            "prompt_sha256"
        ) != fingerprint(call["prompt"]):
            issues.append({"file": str(path), "issue": "answer call identity mismatch"})
    for path in sorted(
        p for directory in directories for p in (directory / "judgments").glob("*.json")
    ):
        row = json.loads(path.read_text())
        if row.get("error"):
            counts["errors"] += 1
            continue
        counts["judgments"] += 1
        answer_path = path.parent.parent / "answers" / path.name
        if not answer_path.exists():
            issues.append({"file": str(path), "issue": "answer record missing"})
            continue
        answer = json.loads(answer_path.read_text())
        if answer.get("answer") != row.get("answer") or fingerprint(
            row.get("answer")
        ) != row.get("answer_sha256"):
            issues.append({"file": str(path), "issue": "judgment answer mismatch"})
        raw = work / "judge_calls" / (row["call"] + ".json")
        if not raw.exists():
            issues.append({"file": str(path), "issue": "raw judgment call missing"})
            continue
        call = json.loads(raw.read_text())
        if call.get("response") != row.get("judgment"):
            issues.append(
                {"file": str(path), "issue": "judgment differs from frozen raw call"}
            )
        if call.get("cache_key") != row["call"] or call.get(
            "prompt_sha256"
        ) != fingerprint(call["prompt"]):
            issues.append(
                {"file": str(path), "issue": "judgment call identity mismatch"}
            )
    return {
        "workdir": str(work),
        "counts": counts,
        "issues": issues,
        "passed": not issues,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("workdirs", nargs="+")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    results = [audit(w) for w in a.workdirs]
    if a.output:
        a.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    if any(not r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
