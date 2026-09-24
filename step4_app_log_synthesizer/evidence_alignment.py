"""Validate explicit fact alignment after blind recovery; no fuzzy acceptance."""

from __future__ import annotations

import hashlib
import json

VERSION = "fact-alignment-v1"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def blind_snapshot(verification):
    return {
        k: v
        for k, v in verification.items()
        if k not in ("fact_alignment", "_gate_decision")
    }


def visible_fragment(fragment):
    # No source fact IDs, embedding notes, or hidden claims enter the evidence.
    visible = {
        k: fragment[k]
        for k in (
            "fragment_id",
            "fragment_type",
            "type",
            "date",
        )
        if k in fragment
    }
    if fragment.get("source"):
        visible["source"] = {
            k: v for k, v in fragment["source"].items() if k in ("type", "name")
        }
    if fragment.get("messages") is not None:
        visible["messages"] = [
            {k: v for k, v in message.items() if k in ("time", "sender", "text")}
            for message in fragment["messages"]
        ]
    if fragment.get("calendar_event") is not None:
        visible["calendar_event"] = {
            k: v
            for k, v in fragment["calendar_event"].items()
            if k
            in (
                "date",
                "start_time",
                "end_time",
                "title",
                "location",
                "participants",
                "notes",
            )
        }
    return visible


def visible_texts(fragment):
    fragment = visible_fragment(fragment)
    result = []
    for message in fragment.get("messages") or []:
        result.extend(v for v in message.values() if isinstance(v, str))
    event = fragment.get("calendar_event") or {}
    result.extend(
        event[k]
        for k in ("date", "start_time", "end_time", "title", "notes", "location")
        if isinstance(event.get(k), str)
    )
    result.extend(p for p in event.get("participants", []) if isinstance(p, str))
    result.extend(fragment[k] for k in ("date",) if isinstance(fragment.get(k), str))
    if isinstance(fragment.get("source", {}).get("name"), str):
        result.append(fragment["source"]["name"])
    return result


def seal_alignment(response, facts, verification, fragments):
    rows = response.get("fact_reviews")
    fact_ids = [f["fact_id"] for f in facts]
    if not fact_ids or len(fact_ids) != len(set(fact_ids)):
        raise ValueError("intended facts must have unique IDs")
    if (
        not isinstance(rows, list)
        or len(rows) != len(fact_ids)
        or {r.get("fact_id") for r in rows} != set(fact_ids)
    ):
        raise ValueError("alignment must cover each intended fact exactly once")
    candidates = verification.get("candidate_facts", [])
    sources = {f["fragment_id"]: f for f in fragments}
    if len(sources) != len(fragments):
        raise ValueError("duplicate fragment IDs")
    for row in rows:
        if row.get("verdict") not in (
            "supported",
            "ambiguous",
            "unsupported",
            "contradicted",
        ) or not row.get("rationale"):
            raise ValueError("invalid fact alignment verdict")
        refs = row.get("candidate_indices")
        if (
            not isinstance(refs, list)
            or len(refs) != len(set(refs))
            or any(type(i) is not int or not 0 <= i < len(candidates) for i in refs)
        ):
            raise ValueError("alignment references a missing blind candidate")
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            raise TypeError("evidence must be a list")
        if row["verdict"] == "supported" and (not refs or not evidence):
            raise ValueError(
                "supported facts require independent recovery and visible evidence"
            )
        for anchor in evidence:
            fid = anchor.get("fragment_id")
            quote = anchor.get("quote")
            if (
                fid not in sources
                or not isinstance(quote, str)
                or not quote
                or not any(quote in t for t in visible_texts(sources[fid]))
            ):
                raise ValueError("alignment quote does not occur in a visible fragment")
    return {
        "version": VERSION,
        "facts_sha256": fingerprint(facts),
        "blind_sha256": fingerprint(blind_snapshot(verification)),
        "fragment_ids": list(sources),
        "fragments_sha256": fingerprint([visible_fragment(f) for f in fragments]),
        "fact_reviews": rows,
        "reviews_sha256": fingerprint(rows),
    }


def accepted_alignment(verification, facts, fragments=None):
    record = verification.get("fact_alignment")
    if not isinstance(record, dict) or record.get("version") != VERSION:
        return False
    if fragments is None or record.get("fragment_ids") != [
        f.get("fragment_id") for f in fragments
    ]:
        return False
    if record.get("fragments_sha256") != fingerprint(
        [visible_fragment(f) for f in fragments]
    ):
        return False
    rows = record.get("fact_reviews", [])
    ids = [f["fact_id"] for f in facts]
    return (
        bool(ids)
        and record.get("facts_sha256") == fingerprint(facts)
        and record.get("blind_sha256") == fingerprint(blind_snapshot(verification))
        and record.get("reviews_sha256") == fingerprint(rows)
        and len(rows) == len(ids)
        and {r.get("fact_id") for r in rows} == set(ids)
        and all(r.get("verdict") == "supported" for r in rows)
    )


def resume_alignment(verification, facts, fragments):
    """Bind a saved cluster decision to its current fragments in original order."""
    ids = (verification.get("fact_alignment") or {}).get("fragment_ids", [])
    by_id = {f.get("fragment_id"): f for f in fragments}
    if not ids or any(fid not in by_id for fid in ids):
        return False
    return accepted_alignment(verification, facts, [by_id[fid] for fid in ids])


def matched_facts(verification):
    candidates = verification["candidate_facts"]
    return [
        {
            "fact_id": r["fact_id"],
            "matched_candidate": " | ".join(
                candidates[i]["candidate_label"] for i in r["candidate_indices"]
            ),
            "candidate_indices": r["candidate_indices"],
            "evidence": r["evidence"],
            "alignment_version": VERSION,
        }
        for r in verification["fact_alignment"]["fact_reviews"]
    ]
