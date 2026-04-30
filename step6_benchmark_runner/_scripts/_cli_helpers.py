"""Shared helpers for the dynamic-track scratch scripts.

Wraps the `claude` CLI with explicit --model selection so we can run dual-judge
Pass 2, CoT Pass 1, and ablation experiments with reproducible model routing.

These scripts live under step6_benchmark_runner/_scripts/ (underscore prefix
marks scratch / experimental work per repo convention). They are not part of
the canonical pipeline. Their outputs go to data_samples/output_<experiment>/
directories so canonical data_samples/output/ is never overwritten.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_CLAUDE_CMD = os.environ.get(
    "CLAUDE_CMD", "claude.cmd" if sys.platform == "win32" else "claude"
)


def call_claude_cli(
    prompt: str,
    model: str | None = None,
    claude_cmd: str = DEFAULT_CLAUDE_CMD,
    timeout_sec: int = 1800,
    session_dir: Path | None = None,
    max_retries: int = 1,
    raw_dump_path: Path | None = None,
) -> str:
    """Invoke `claude -p [--model X]` with the prompt on stdin.

    If session_dir is provided, it is wiped before each call. This is the
    OpenClaw isolation pattern for cold-context runs (Step 6 Pass 1 needs it
    so prior cases don't leak into the current one).
    """
    if session_dir is not None:
        if session_dir.exists():
            shutil.rmtree(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)

    cmd = [claude_cmd, "-p"]
    if model:
        cmd += ["--model", model]
    # Pass 2 scoring is judgment-by-rubric, not deep reasoning. Lowering effort
    # cuts wall-clock substantially without hurting grading quality.
    if os.environ.get("CLAUDE_EFFORT"):
        cmd += ["--effort", os.environ["CLAUDE_EFFORT"]]

    last_stderr = ""
    for attempt in range(max_retries + 1):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt)
            tmp_path = f.name
        try:
            with open(tmp_path, "r", encoding="utf-8") as stream:
                result = subprocess.run(
                    cmd,
                    stdin=stream,
                    capture_output=True,
                    timeout=timeout_sec,
                )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            if raw_dump_path is not None:
                raw_dump_path.parent.mkdir(parents=True, exist_ok=True)
                raw_dump_path.write_text(
                    f"RC={result.returncode}\n--STDOUT--\n{stdout}\n--STDERR--\n{stderr}",
                    encoding="utf-8",
                )
            if result.returncode == 0 and stdout.strip():
                return stdout.strip()
            last_stderr = stderr
            print(
                f"[cli] attempt {attempt + 1}/{max_retries + 1} failed "
                f"(rc={result.returncode}); stderr: {stderr[:200]}"
            )
        finally:
            os.unlink(tmp_path)
    raise RuntimeError(
        f"claude CLI failed after {max_retries + 1} attempts: {last_stderr[:500]}"
    )


def extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start = payload.find("{")
    if start == -1:
        raise ValueError("No JSON object found in CLI output")
    return json.loads(payload[start:])


def fill(template: str, placeholder: str, payload: Any) -> str:
    if isinstance(payload, str):
        return template.replace(placeholder, payload)
    return template.replace(
        placeholder, json.dumps(payload, indent=2, ensure_ascii=False)
    )


def load_prompt_sections(prompt_path: Path) -> dict[str, str]:
    text = prompt_path.read_text(encoding="utf-8")
    pass1_marker = "PASS 1 — ANSWERING"
    pass2_marker = "PASS 2 — SCORING"
    header_end = text.index(pass1_marker)
    pass2_start = text.index(pass2_marker)
    header = text[:header_end]
    pass1 = header + text[header_end:pass2_start]
    pass2 = header + text[pass2_start:]
    return {"pass1": pass1, "pass2": pass2}


def strip_to_raw_logs(app_logs: dict[str, Any]) -> str:
    """Same flattening as the canonical generator.py — keep in sync."""
    lines: list[str] = []
    messenger = app_logs.get("messenger", {})
    sessions: list[dict[str, Any]] = []
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
    events = sorted(
        events or [], key=lambda e: (e.get("date", ""), e.get("start_time", ""))
    )
    for e in events:
        date = e.get("date", "")
        start = e.get("start_time", "")
        end = e.get("end_time", "")
        title = e.get("title", "")
        loc = e.get("location", "")
        participants = ", ".join(e.get("participants", []) or [])
        notes = e.get("notes", "")
        lines.append(
            f"{date} | {start}-{end} | {title} | @ {loc} | with {participants} "
            f"| Notes: {notes}"
        )

    return "\n".join(lines)


def strip_ground_truth(test_cases: dict[str, Any]) -> dict[str, Any]:
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


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Coarse truncation by 4-chars-per-token estimate. Truncates mid-line if
    needed; cuts FROM THE END so the earliest signals stay intact."""
    char_budget = max_tokens * 4
    if len(text) <= char_budget:
        return text
    return text[:char_budget]


def approx_token_count(text: str) -> int:
    return len(text) // 4
