"""Validate independent human ratings and expose unresolved adjudication explicitly."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from type5_protocol.protocol import fingerprint

KINDS = {"cases": "case_valid", "answers": "response_valid"}


def read_ratings(packet, submission, kind):
    """A submission declares its source; no model output becomes a human rating."""
    if (
        submission.get("reviewer_kind") != "human"
        or not submission.get("reviewer_id", "").strip()
    ):
        raise ValueError("named human reviewer declaration required")
    if submission.get("packet_sha256") != fingerprint(packet):
        raise ValueError("ratings belong to a different packet")
    expected = {r["review_id"] for r in packet}
    rows = submission.get("ratings")
    if not isinstance(rows, list):
        raise TypeError("ratings must be a list")
    result = {}
    for row in rows:
        rid = row.get("review_id")
        if rid not in expected or rid in result:
            raise ValueError("duplicate or unknown review ID")
        verdict = row.get(KINDS[kind])
        if verdict is not None and type(verdict) is not bool:
            raise ValueError("verdict must be true, false, or null")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("every submitted rating needs a reason")
        if kind == "cases" and verdict is True:
            for field in (
                "supported_facts",
                "appropriate_responses",
                "unjustified_restrictions",
                "material_ambiguities",
            ):
                if not isinstance(row.get(field), list):
                    raise TypeError(
                        "case approval needs independent evidence and behavior review"
                    )
            if (
                not row["supported_facts"]
                or not row["appropriate_responses"]
                or row["material_ambiguities"]
            ):
                raise ValueError(
                    "case approval requires supported facts, valid approaches, and no material ambiguity"
                )
        result[rid] = row
    return result


def adjudicate(packet, submissions, kind, decisions=None):
    if len(submissions) != 2 or len({s.get("reviewer_id") for s in submissions}) != 2:
        raise ValueError("exactly two distinct independent reviewers required")
    ratings = [read_ratings(packet, s, kind) for s in submissions]
    overrides = {}
    if decisions is not None:
        if decisions.get("source_reviews_sha256") != fingerprint(submissions):
            raise ValueError("adjudication does not bind these reviews")
        overrides = read_ratings(packet, decisions, kind)
    output = []
    for item in packet:
        rid = item["review_id"]
        values = [r.get(rid, {}).get(KINDS[kind]) for r in ratings]
        agreed = values[0] is not None and values[0] == values[1]
        decision = values[0] if agreed else None
        source = "independent_agreement" if agreed else "unresolved"
        if rid in overrides:
            if agreed:
                raise ValueError(
                    "adjudication cannot silently replace independent agreement; revise and preserve source ratings first"
                )
            if any(rid not in r for r in ratings):
                raise ValueError(
                    "adjudication cannot substitute for a missing independent review"
                )
            decision = overrides[rid][KINDS[kind]]
            source = "adjudicated" if decision is not None else "unresolved"
        output.append(
            {
                "review_id": rid,
                "reference": decision,
                "source": source,
                "independent_verdicts": values,
            }
        )
    complete = sum(x["reference"] is not None for x in output)
    comparable = [
        x for x in output if all(v is not None for v in x["independent_verdicts"])
    ]
    return {
        "kind": kind,
        "packet_sha256": fingerprint(packet),
        "source_reviews_sha256": fingerprint(submissions),
        "intended": len(packet),
        "resolved": complete,
        "unresolved": len(packet) - complete,
        "independently_comparable": len(comparable),
        "independent_agreements": sum(
            x["independent_verdicts"][0] == x["independent_verdicts"][1]
            for x in comparable
        ),
        "results": output,
    }


def clustered_rate(rows, event, *, seed=7, draws=2000):
    """Descriptive persona bootstrap; no independence claim for paired variants."""
    groups = {}
    for r in rows:
        groups.setdefault(r["persona_id"], []).append(bool(event(r)))
    values = [v for g in groups.values() for v in g]
    result = {
        "events": sum(values),
        "count": len(values),
        "personas": len(groups),
        "rate": sum(values) / len(values) if values else None,
        "persona_bootstrap_95": None,
    }
    if len(groups) < 2:
        return result
    rng = random.Random(seed)
    group_values = list(groups.values())
    samples = []
    for _ in range(draws):
        batch = [v for g in rng.choices(group_values, k=len(group_values)) for v in g]
        samples.append(sum(batch) / len(batch))
    samples.sort()
    if samples[0] != samples[-1]:
        result["persona_bootstrap_95"] = [
            samples[int(draws * 0.025)],
            samples[int(draws * 0.975) - 1],
        ]
    return result


def calibration_report(answer_reference, mapping, cases, judgments, personas):
    """Only adjudicated-valid cases enter calibration; report all exclusions."""
    keys = {r["review_id"]: r for r in mapping}
    if len(keys) != len(mapping):
        raise ValueError("duplicate private mapping")
    included, exclusions = [], []
    for ref in answer_reference["results"]:
        item = keys[ref["review_id"]]
        eid = item["episode_id"]
        reason = None
        if cases.get(eid) is not True:
            reason = "case_invalid" if cases.get(eid) is False else "case_unresolved"
        elif ref["reference"] is None:
            reason = "human_response_unresolved"
        elif ref["review_id"] not in judgments or judgments[ref["review_id"]] is None:
            reason = "judge_unresolved"
        if reason:
            exclusions.append({"review_id": ref["review_id"], "reason": reason})
            continue
        pred = judgments[ref["review_id"]]
        if type(pred) is not bool:
            raise ValueError("judge outcome must be boolean or unresolved")
        included.append(
            {
                "reference": ref["reference"],
                "prediction": pred,
                "persona_id": personas[eid],
            }
        )
    invalid = [r for r in included if not r["reference"]]
    valid = [r for r in included if r["reference"]]
    return {
        "reference_status": "human_adjudicated",
        "intended": len(answer_reference["results"]),
        "resolved": len(included),
        "excluded_or_unresolved": exclusions,
        "false_acceptance": clustered_rate(invalid, lambda r: r["prediction"]),
        "false_rejection": clustered_rate(valid, lambda r: not r["prediction"]),
        "interval_scope": "Descriptive persona-cluster bootstrap. Null for fewer than two personas or a degenerate distribution; not evidence of zero population error.",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--packet", type=Path, required=True)
    p.add_argument("--kind", choices=tuple(KINDS), required=True)
    p.add_argument("--reviews", nargs=2, type=Path)
    p.add_argument("--adjudication", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    packet = json.loads(args.packet.read_text())
    if args.reviews:
        submissions = [json.loads(path.read_text()) for path in args.reviews]
        decisions = (
            json.loads(args.adjudication.read_text()) if args.adjudication else None
        )
        result = adjudicate(packet, submissions, args.kind, decisions)
    else:
        if args.adjudication:
            raise ValueError("adjudication requires two independent submissions")
        result = {
            "reviewer_kind": "human",
            "reviewer_id": "",
            "packet_sha256": fingerprint(packet),
            "ratings": [
                {
                    "review_id": r["review_id"],
                    KINDS[args.kind]: None,
                    "reason": "",
                    **(
                        {
                            field: []
                            for field in (
                                "supported_facts",
                                "appropriate_responses",
                                "unjustified_restrictions",
                                "material_ambiguities",
                            )
                        }
                        if args.kind == "cases"
                        else {}
                    ),
                }
                for r in packet
            ],
        }
    if args.output.exists() and json.loads(args.output.read_text()) != result:
        raise ValueError("preserve prior adjudication; choose a new output file")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("results", "ratings")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
