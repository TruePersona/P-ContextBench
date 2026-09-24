"""Freeze case admission before answering and preserve rejected-family coverage."""

import argparse
import json
import shutil
from argparse import Namespace
from pathlib import Path

from type5_protocol.experiment import ensure_reviewed
from type5_protocol.protocol import fingerprint, validate_families


def admit(source, destination):
    source, destination = Path(source), Path(destination)
    data = json.loads((source / "pilot.json").read_text())
    groups = validate_families(data["episodes"])
    inventory_path = source / "review_summary.json"
    if inventory_path.exists():
        summary = json.loads(inventory_path.read_text())
    else:
        summary = []
        for fid, group in groups.items():
            paths = [(fid, source / "family_reviews" / (fid + ".json"))] + [
                (e["id"], source / "reviews" / (e["id"] + ".json"))
                for e in group
                if e["variant"] != "irrelevant_control"
            ]
            for identifier, path in paths:
                if path.exists():
                    row = json.loads(path.read_text())
                    summary.append(
                        {
                            "id": identifier,
                            "accepted": row.get("accepted", False),
                            "issues": row.get(
                                "issues", row.get("review", {}).get("issues", [])
                            ),
                        }
                    )
                else:
                    summary.append(
                        {"id": identifier, "error": "missing completed review"}
                    )
    expected = set(groups) | {
        e["id"] for e in data["episodes"] if e["variant"] != "irrelevant_control"
    }
    if {r["id"] for r in summary} != expected or len(summary) != len(expected):
        raise ValueError(
            "case review did not cover the complete intended construction set"
        )
    args = Namespace(workdir=str(source), allow_unreviewed=False)
    included = []
    excluded = []
    for fid, group in groups.items():
        try:
            for e in group:
                ensure_reviewed(e, args)
            included.append(fid)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            details = [
                r for r in summary if r["id"] == fid or r["id"].startswith(fid + "-")
            ]
            excluded.append(
                {
                    "family_id": fid,
                    "persona_id": group[0]["persona_id"],
                    "split": group[0]["split"],
                    "reason": str(exc),
                    "reviews": details,
                }
            )
    selected = set(included)
    if not selected:
        raise ValueError("no admissible families")
    report = {
        "source_dataset_sha256": fingerprint(data),
        "intended_families": len(groups),
        "admitted_families": len(included),
        "admitted_ids": included,
        "excluded": excluded,
        "selection_basis": "Case-quality review only, before any answering. Performance is conditional on admission, not representative of all original or proposed cases.",
    }
    out = {
        "episodes": [e for e in data["episodes"] if e["family_id"] in selected],
        "calibration": [
            x
            for x in data["calibration"]
            if x["episode_id"].rsplit("-", 1)[0] in selected
        ],
        "provenance": [r for r in data["provenance"] if r["family_id"] in selected],
        "admission": report,
        "status": "candidate_not_human_validated",
    }
    validate_families(out["episodes"])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "pilot.json"
    if path.exists() and json.loads(path.read_text()) != out:
        raise ValueError("admitted set changed; use a new study directory")
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    (destination / "admission.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    for name in ("review_calls", "reviews", "family_reviews"):
        shutil.copytree(source / name, destination / name, dirs_exist_ok=True)
    print(json.dumps({k: v for k, v in report.items() if k != "excluded"}, indent=2))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--source", default="_orchestration/type5_protocol/expanded_v3_checked"
    )
    p.add_argument(
        "--destination", default="_orchestration/type5_protocol/expanded_admitted_v3"
    )
    a = p.parse_args()
    admit(a.source, a.destination)


if __name__ == "__main__":
    main()
