"""Blind human review and judge calibration for registered policy studies."""

from __future__ import annotations

import argparse
from pathlib import Path

from type5_protocol.human_validation import calibration_report
from type5_protocol.policy_study import compare, frozen_write, load_study, read
from type5_protocol.protocol import fingerprint, public_episode


def packets(work):
    work = Path(work)
    report = compare(work)
    if not report["artifact_integrity_passed"]:
        raise ValueError("resolve artifact integrity before exporting review packets")
    registration, episodes = load_study(work)
    case_rows, case_keys, answers, missing = [], [], {}, []
    for episode in sorted(episodes, key=lambda e: fingerprint(e["id"])):
        public = public_episode(episode)
        rid = (
            "R-" + fingerprint({"episode": fingerprint(episode), "public": public})[:16]
        )
        case_rows.append(
            {
                "review_id": rid,
                "public_episode": public,
                "case_valid": None,
                "supported_facts": [],
                "appropriate_responses": [],
                "unjustified_restrictions": [],
                "material_ambiguities": [],
            }
        )
        case_keys.append(
            {
                "review_id": rid,
                "episode_id": episode["id"],
                "episode_sha256": fingerprint(episode),
            }
        )
        for plan in registration["runs"]:
            row = read(work / "runs" / plan["run"] / (episode["id"] + ".json"))
            if not row.get("answer"):
                missing.append(
                    {
                        "run": plan["run"],
                        "episode_id": episode["id"],
                        "error": row.get("error"),
                    }
                )
                continue
            key = fingerprint(
                {"episode": episode["id"], "public": public, "answer": row["answer"]}
            )
            item = answers.setdefault(
                key,
                {
                    "public_episode": public,
                    "answer": row["answer"],
                    "episode": episode,
                    "sources": [],
                },
            )
            item["sources"].append(
                {"run": plan["run"], "answer_call": row["answer_call"]}
            )
    answer_rows, answer_keys = [], []
    for key, item in sorted(answers.items()):
        rid = "A-" + key[:16]
        answer_rows.append(
            {
                "review_id": rid,
                "public_episode": item["public_episode"],
                "answer": item["answer"],
                "response_valid": None,
                "context_error": None,
                "progress_error": None,
                "boundary_error": None,
                "unnecessary_intervention": None,
            }
        )
        answer_keys.append(
            {
                "review_id": rid,
                "episode_id": item["episode"]["id"],
                "episode_sha256": fingerprint(item["episode"]),
                "answer_sha256": fingerprint(item["answer"]),
                "sources": item["sources"],
            }
        )
    out = work / "human_review" / "development"
    for name, value in (
        ("blind_cases.json", case_rows),
        ("private_mapping.json", case_keys),
        ("blind_answers.json", answer_rows),
        ("private_answer_mapping.json", answer_keys),
        ("missing_answers.json", missing),
    ):
        frozen_write(out / name, value)
    frozen_write(
        out / "export_provenance.json",
        {
            "registration_sha256": fingerprint(registration),
            "packet_sha256": {
                "cases": fingerprint(case_rows),
                "answers": fingerprint(answer_rows),
            },
            "private_mapping_sha256": {
                "cases": fingerprint(case_keys),
                "answers": fingerprint(answer_keys),
            },
            "review_rule": "Independently review complete public episodes before responses. Accept alternative valid approaches. Do not consult private mappings or model judgments. Templates are not human validation.",
            "intended_answer_rows": len(episodes) * len(registration["runs"]),
            "unique_answers": len(answer_rows),
            "missing_answer_rows": len(missing),
        },
    )
    return {
        "directory": str(out),
        "cases": len(case_rows),
        "answers": len(answer_rows),
        "missing": len(missing),
    }


def calibrate(work, run, case_reference, answer_reference):
    work = Path(work)
    report = compare(work)
    if not report["artifact_integrity_passed"]:
        raise ValueError("artifact integrity failed")
    registration, episodes = load_study(work)
    if run not in {plan["run"] for plan in registration["runs"]}:
        raise ValueError("unregistered run")
    out = work / "human_review" / "development"
    provenance = read(out / "export_provenance.json")
    if provenance["registration_sha256"] != fingerprint(registration):
        raise ValueError("packet belongs to a different study")
    keys, public = {}, {}
    for kind, name, reference in (
        ("cases", "private_mapping.json", case_reference),
        ("answers", "private_answer_mapping.json", answer_reference),
    ):
        keys[kind] = read(out / name)
        public[kind] = read(out / ("blind_" + kind + ".json"))
        expected = {r["review_id"] for r in public[kind]}
        if (
            reference.get("kind") != kind
            or reference.get("packet_sha256") != fingerprint(public[kind])
            or provenance["packet_sha256"][kind] != fingerprint(public[kind])
        ):
            raise ValueError("human reference packet mismatch")
        if (
            len(reference["results"]) != len(expected)
            or {r["review_id"] for r in reference["results"]} != expected
        ):
            raise ValueError("human reference coverage changed")
        if provenance["private_mapping_sha256"][kind] != fingerprint(keys[kind]):
            raise ValueError("private mapping changed")
    episode_map = {e["id"]: e for e in episodes}
    for group in keys.values():
        for key in group:
            if key["episode_sha256"] != fingerprint(episode_map[key["episode_id"]]):
                raise ValueError("episode mapping changed")
    case_ids = {k["review_id"]: k["episode_id"] for k in keys["cases"]}
    cases = {
        case_ids[r["review_id"]]: r["reference"] for r in case_reference["results"]
    }
    selected, judgments = [], {}
    for key in keys["answers"]:
        matches = [source for source in key["sources"] if source["run"] == run]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("ambiguous answer source")
        row = read(work / "runs" / run / (key["episode_id"] + ".json"))
        if (
            key["answer_sha256"] != fingerprint(row["answer"])
            or matches[0]["answer_call"] != row["answer_call"]
        ):
            raise ValueError("reviewed answer binding changed")
        selected.append(key)
        judgments[key["review_id"]] = report["runs"][run]["episodes"][
            key["episode_id"]
        ]["case_success"]
    selected_ids = {key["review_id"] for key in selected}
    reference = {
        **answer_reference,
        "results": [
            r for r in answer_reference["results"] if r["review_id"] in selected_ids
        ],
    }
    result = calibration_report(
        reference,
        selected,
        cases,
        judgments,
        {e["id"]: e["persona_id"] for e in episodes},
    )
    result.update(
        run=run,
        intended_episode_count=len(episodes),
        missing_answer_episodes=[
            row["episode_id"]
            for row in read(out / "missing_answers.json")
            if row["run"] == run
        ],
        registration_sha256=fingerprint(registration),
        case_reference_sha256=fingerprint(case_reference),
        answer_reference_sha256=fingerprint(answer_reference),
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("packets", "calibrate"))
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--run")
    parser.add_argument("--case-reference", type=Path)
    parser.add_argument("--answer-reference", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.stage == "packets":
        result = packets(args.workdir)
    else:
        if not all((args.run, args.case_reference, args.answer_reference, args.output)):
            parser.error("calibrate requires --run, both reference files, and --output")
        result = calibrate(
            args.workdir,
            args.run,
            read(args.case_reference),
            read(args.answer_reference),
        )
    if args.output:
        frozen_write(args.output, result)
    import json

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
