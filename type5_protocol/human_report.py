"""Compare frozen model judgments with separately adjudicated human references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from type5_protocol.human_validation import calibration_report
from type5_protocol.protocol import VERSION, fingerprint, score


def compare(work, split, case_reference, answer_reference, run):
    work = Path(work)
    packet = work / "human_review" / split
    data = json.loads((work / "pilot.json").read_text())
    episodes = {e["id"]: e for e in data["episodes"] if e["split"] == split}
    case_packet = json.loads((packet / "blind_cases.json").read_text())
    answer_packet = json.loads((packet / "blind_answers.json").read_text())
    case_keys = {
        r["review_id"]: r
        for r in json.loads((packet / "private_mapping.json").read_text())
    }
    answer_keys = json.loads((packet / "private_answer_mapping.json").read_text())
    for reference, public in (
        (case_reference, case_packet),
        (answer_reference, answer_packet),
    ):
        if reference["packet_sha256"] != fingerprint(public):
            raise ValueError("human reference packet mismatch")
        if {r["review_id"] for r in reference["results"]} != {
            r["review_id"] for r in public
        }:
            raise ValueError("human reference coverage changed")
    cases = {}
    for r in case_reference["results"]:
        key = case_keys[r["review_id"]]
        e = episodes[key["episode_id"]]
        if key["episode_sha256"] != fingerprint(e):
            raise ValueError("case mapping stale")
        cases[e["id"]] = r["reference"]
    manifest = json.loads((work / "runs" / run / "manifest.json").read_text())
    if (
        manifest["protocol"] not in ("type5-decision-0.3", VERSION)
        or manifest["condition"] != "full"
        or manifest["split"] != split
    ):
        raise ValueError(
            "comparison requires a supported full-history run on the selected split"
        )
    judgments = {}
    selected = []
    included_ids = set()
    for key in answer_keys:
        matches = [s for s in key["sources"] if s["source"] == run]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("ambiguous source mapping")
        e = episodes[key["episode_id"]]
        if key["episode_sha256"] != fingerprint(e):
            raise ValueError("answer mapping stale")
        selected.append(key)
        included_ids.add(key["review_id"])
        path = work / "runs" / run / "judgments" / (e["id"] + ".json")
        if not path.exists():
            continue
        row = json.loads(path.read_text())
        if row.get("error"):
            continue
        if (
            row.get("episode_sha256") != fingerprint(e)
            or fingerprint(row["answer"]) != key["answer_sha256"]
        ):
            raise ValueError("judge output does not belong to reviewed answer")
        judgments[key["review_id"]] = score(e, row["answer"], row["judgment"])[
            "case_success"
        ]
    if not selected:
        raise ValueError("no packet responses belong to this run")
    reference = {
        **answer_reference,
        "results": [
            r for r in answer_reference["results"] if r["review_id"] in included_ids
        ],
    }
    result = calibration_report(
        reference,
        selected,
        cases,
        judgments,
        {eid: e["persona_id"] for eid, e in episodes.items()},
    )
    result.update(
        protocol=manifest["protocol"],
        run=run,
        case_reference_sha256=fingerprint(case_reference),
        answer_reference_sha256=fingerprint(answer_reference),
        excluded_packet_responses_from_other_sources=len(answer_reference["results"])
        - len(reference["results"]),
    )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", type=Path, required=True)
    p.add_argument("--split", choices=("development", "heldout"), default="development")
    p.add_argument("--case-reference", type=Path, required=True)
    p.add_argument("--answer-reference", type=Path, required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = compare(
        a.workdir,
        a.split,
        json.loads(a.case_reference.read_text()),
        json.loads(a.answer_reference.read_text()),
        a.run,
    )
    if a.output.exists() and json.loads(a.output.read_text()) != result:
        raise ValueError("preserve prior comparison; choose a new output file")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
