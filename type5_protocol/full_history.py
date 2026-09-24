"""Transfer controlled episodes into complete visible source histories."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from type5_protocol.protocol import fingerprint, validate_families

ROOT = Path(__file__).resolve().parents[1]


def local_timestamp(date, time, zone):
    naive = datetime.fromisoformat(date + "T" + time)
    value = naive.replace(tzinfo=ZoneInfo(zone))
    if (
        value.astimezone(timezone.utc).astimezone(ZoneInfo(zone)).replace(tzinfo=None)
        != naive
    ):
        raise ValueError("nonexistent local time in source history")
    if value.utcoffset() != value.replace(fold=1).utcoffset():
        raise ValueError("ambiguous local time in source history")
    return value.isoformat()


def visible_history(data, zone):
    """Keep all visible message/event content without meaningful/filler labels."""
    logs = []
    sessions = (
        data["messenger"]["meaningful_sessions"] + data["messenger"]["filler_sessions"]
    )
    for s in sessions:
        messages = s["messages"]
        if not messages:
            raise ValueError("empty source session")
        text = (
            "Conversation with "
            + s["contact"]
            + "\n"
            + "\n".join(
                m["time"] + " " + m["sender"] + ": " + m["text"] for m in messages
            )
        )
        # The complete session becomes available only after its last message.
        time = max(m["time"] for m in messages)
        logs.append(
            {
                "timestamp": local_timestamp(s["date"], time, zone),
                "channel": "messenger",
                "speaker": "Conversation participants",
                "text": text,
            }
        )
    fields = (
        "title",
        "date",
        "start_time",
        "end_time",
        "location",
        "participants",
        "notes",
    )
    for e in data["calendar"]["events"]:
        visible = {k: e[k] for k in fields if k in e}
        logs.append(
            {
                "timestamp": local_timestamp(e["date"], e["start_time"], zone),
                "channel": "calendar",
                "speaker": "Calendar",
                "text": json.dumps(visible, ensure_ascii=False),
            }
        )
    logs.sort(key=lambda l: (l["timestamp"], fingerprint(l)))
    occurrences = {}
    for log in logs:
        key = fingerprint(log)[:16]
        number = occurrences.get(key, 0)
        occurrences[key] = number + 1
        log["id"] = f"H-{key}-{number}"
        log["provenance"] = {
            "kind": "source_history",
            "explanation": "Visible original history; timezone interpretation is an explicit transfer-study assumption.",
        }
    return logs


def transfer(source, destination):
    source, destination = Path(source), Path(destination)
    data = json.loads((source / "pilot.json").read_text())
    result = deepcopy(data)
    cache, records = {}, []
    for e in result["episodes"]:
        key = (e["persona_id"], e["timezone"])
        if key not in cache:
            path = (
                ROOT
                / "step4_app_log_synthesizer/data_samples"
                / f"{e['persona_id']}_app_logs.json"
            )
            raw = json.loads(path.read_text())
            cache[key] = visible_history(raw, e["timezone"])
            records.append(
                {
                    "persona_id": e["persona_id"],
                    "source_path": str(path.relative_to(ROOT)),
                    "source_sha256": fingerprint(raw),
                    "visible_sessions_and_events": len(cache[key]),
                    "original_messages": sum(
                        len(s["messages"])
                        for s in raw["messenger"]["meaningful_sessions"]
                        + raw["messenger"]["filler_sessions"]
                    ),
                    "original_events": len(raw["calendar"]["events"]),
                    "timezone": e["timezone"],
                }
            )
        history = deepcopy(cache[key])
        if any(
            datetime.fromisoformat(l["timestamp"])
            >= datetime.fromisoformat(e["request_timestamp"])
            for l in history
        ):
            raise ValueError(
                "original history contains evidence at or after the constructed request"
            )
        e["logs"] = sorted(history + e["logs"], key=lambda l: (l["timestamp"], l["id"]))
    result["transfer"] = {
        "source_pilot_sha256": fingerprint(data),
        "records": records,
        "scope": "Complete visible historical sessions and calendar events plus constructed March 31 updates. This tests context transfer, not validity of original T5 cases.",
        "timezone_assumption": "Original corpus has no timezone; interpret local clock strings in the controlled episode timezone without claiming it is the original persona timezone.",
        "truncation": False,
    }
    validate_families(result["episodes"])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "pilot.json"
    if path.exists() and json.loads(path.read_text()) != result:
        raise ValueError("immutable transfer pilot changed")
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result["transfer"], indent=2))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="_orchestration/type5_protocol/curated_v2")
    p.add_argument(
        "--destination", default="_orchestration/type5_protocol/full_history_v1"
    )
    a = p.parse_args()
    transfer(a.source, a.destination)


if __name__ == "__main__":
    main()
