"""Mechanically prepare stripped Pass 1 inputs for the 5 dynamic-news personas.

Reads:
  - step4_app_log_synthesizer/data_samples/output_news_dynamic_v1/{persona}_app_logs_news_dynamic_v1.json
  - step5_testcases_synthesis/data_samples/output/{persona}_test_cases.json

Writes (stripped, isolation-safe):
  - step6_benchmark_runner/data_samples/input_news_dynamic_v1/{persona}_app_logs_raw.txt
  - step6_benchmark_runner/data_samples/input_news_dynamic_v1/{persona}_test_cases_stripped.json

Does not print any of the contents to stdout. Only summary counts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Inlined from generator.py to avoid importing the anthropic SDK.
def strip_to_raw_logs(app_logs):
    lines = []
    messenger = app_logs.get("messenger", {})
    sessions = []
    for bucket_name in ("meaningful_sessions", "filler_sessions", "sessions"):
        bucket = messenger.get(bucket_name, []) or []
        sessions.extend(bucket)
    sessions.sort(
        key=lambda s: (
            s.get("date", ""),
            (s.get("messages") or [{"time": ""}])[0].get("time", ""),
        )
    )
    persona_name = app_logs.get("persona_name") or app_logs.get("name", "persona")
    for s in sessions:
        contact = s.get("contact") or s.get("other_person") or "unknown"
        date = s.get("date", "")
        lines.append(f"--- {date} | {persona_name} <-> {contact} ---")
        for m in s.get("messages", []) or []:
            time = m.get("time", "")
            sender = m.get("sender", "")
            text = m.get("text", "")
            lines.append(f"[{time}] {sender}: {text}")
        lines.append("")
    calendar = app_logs.get("calendar", {})
    events = calendar.get("events", []) if isinstance(calendar, dict) else calendar or []
    events = sorted(events or [], key=lambda e: (e.get("date", ""), e.get("start_time", "")))
    for e in events:
        date = e.get("date", "")
        start = e.get("start_time", "")
        end = e.get("end_time", "")
        title = e.get("title", "")
        loc = e.get("location", "")
        participants = ", ".join(e.get("participants", []) or [])
        notes = e.get("notes", "")
        lines.append(
            f"{date} | {start}-{end} | {title} | @ {loc} | with {participants} | Notes: {notes}"
        )
    return "\n".join(lines)


def strip_ground_truth(test_cases):
    stripped = {"metadata": test_cases.get("metadata", {}), "test_cases": []}
    for tc in test_cases.get("test_cases", []):
        stripped["test_cases"].append(
            {
                k: v
                for k, v in tc.items()
                if k
                not in {
                    "ground_truth",
                    "expected_evidence",
                    "source_hidden_fact_ids",
                    "source_subcategories",
                    "risk_surface_score",
                    "user_prompt_context",
                    "expected_behavior",
                }
            }
        )
    return stripped

PERSONAS = [
    "alicia_gonzalez",
    "deeva_cintron",
    "julio_simmons",
    "maria_buendia",
    "mary_alberti",
]

APP_LOGS_DIR = REPO / "step4_app_log_synthesizer" / "data_samples" / "output_news_dynamic_v1"
TEST_CASES_DIR = REPO / "step5_testcases_synthesis" / "data_samples" / "output"
OUT_DIR = REPO / "step6_benchmark_runner" / "data_samples" / "input_news_dynamic_v1"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in PERSONAS:
        app_logs_path = APP_LOGS_DIR / f"{p}_app_logs_news_dynamic_v1.json"
        tc_path = TEST_CASES_DIR / f"{p}_test_cases.json"
        if not app_logs_path.exists():
            print(f"[skip] missing {app_logs_path}")
            continue
        if not tc_path.exists():
            print(f"[skip] missing {tc_path}")
            continue
        app_logs = json.loads(app_logs_path.read_text(encoding="utf-8"))
        tc_full = json.loads(tc_path.read_text(encoding="utf-8"))
        raw = strip_to_raw_logs(app_logs)
        stripped = strip_ground_truth(tc_full)
        raw_out = OUT_DIR / f"{p}_app_logs_raw.txt"
        tc_out = OUT_DIR / f"{p}_test_cases_stripped.json"
        raw_out.write_text(raw, encoding="utf-8")
        tc_out.write_text(json.dumps(stripped, indent=2, ensure_ascii=False), encoding="utf-8")
        n_cases = len(stripped.get("test_cases", []))
        print(f"[ok] {p}: raw_log_chars={len(raw)} cases={n_cases}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
