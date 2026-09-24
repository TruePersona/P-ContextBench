"""Isolated, cached inference calls for local protocol experiments."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from type5_protocol.protocol import fingerprint
from utils import extract_json

SYSTEM = "You are a text-only inference endpoint. Use only the supplied text. Do not call tools, inspect files, access the network, or read other context. Return only the requested JSON."


def infer(
    prompt,
    *,
    model,
    backend,
    output_dir,
    effort="low",
    timeout=600,
    response_format="json",
    replicate="first",
):
    # Serialize identical requests across threads and local CLI processes.
    lock_key = fingerprint(
        {
            "prompt": prompt,
            "model": model,
            "backend": backend,
            "effort": effort,
            "format": response_format,
            "replicate": replicate,
        }
    )
    locks = Path(output_dir) / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / (lock_key + ".lock")).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return _infer(
            prompt,
            model=model,
            backend=backend,
            output_dir=output_dir,
            effort=effort,
            timeout=timeout,
            response_format=response_format,
            replicate=replicate,
        )


def _infer(
    prompt,
    *,
    model,
    backend,
    output_dir,
    effort="low",
    timeout=600,
    response_format="json",
    replicate="first",
):
    if response_format not in ("json", "text"):
        raise ValueError("unsupported response format")
    system = (
        SYSTEM
        if response_format == "json"
        else SYSTEM.replace(
            "Return only the requested JSON.",
            "Return only the requested user-facing response as plain text.",
        )
    )
    configuration = {
        "model": model,
        "backend": backend,
        "effort": effort,
        "system": system,
        "transport_version": "isolated-1",
    }
    if replicate != "first":
        configuration["replicate"] = replicate
    key = fingerprint({"configuration": configuration, "prompt": prompt})
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (key + ".json")
    if path.exists():
        cached = json.loads(path.read_text())
        if (
            cached.get("cache_key") != key
            or cached.get("prompt") != prompt
            or cached.get("prompt_sha256") != fingerprint(prompt)
            or cached.get("configuration") != configuration
        ):
            raise ValueError("cached inference provenance mismatch")
        if cached.get("status") in ("ok", "invalid_json"):
            return cached
        # A completed transport with malformed JSON is available for an explicit,
        # recorded syntax repair. Never treat it as a valid behavioral result.
        if cached.get("response_text") and "JSONDecodeError" == cached.get(
            "error_type"
        ):
            return {**cached, "response": None, "status": "invalid_json"}
        raise RuntimeError(
            f"cached inference failure; inspect {path} before an explicit retry"
        )
    started = time.time()
    record = {
        "configuration": configuration,
        "prompt_sha256": fingerprint(prompt),
        "prompt": prompt,
    }
    with tempfile.TemporaryDirectory(prefix="personabench_inference_") as tmp:
        env = dict(os.environ)
        if backend == "claude":
            # Use the existing subscription login, not a metered key inherited by accident.
            env.pop("ANTHROPIC_API_KEY", None)
            cmd = [
                "claude",
                "-p",
                "--safe-mode",
                "--tools",
                "",
                "--no-session-persistence",
                "--model",
                model,
                "--max-budget-usd",
                "2",
                "--system-prompt",
                system,
                "--output-format",
                "json",
                "--effort",
                effort,
            ]
            request = prompt
        elif backend == "codex":
            cmd = [
                "codex",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--json",
                "-C",
                tmp,
                "--model",
                model,
                "-c",
                f'model_reasoning_effort="{effort}"',
                "-c",
                'web_search="disabled"',
                "-c",
                "features.shell_tool=false",
                "-o",
                str(Path(tmp) / "answer.txt"),
                "-",
            ]
            request = system + "\n\n" + prompt
        else:
            raise ValueError("unsupported experiment backend")
        try:
            result = subprocess.run(
                cmd,
                input=request,
                text=True,
                capture_output=True,
                cwd=tmp,
                env=env,
                timeout=timeout,
                check=False,
            )
            record.update(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.returncode:
                raise RuntimeError(
                    f"inference process exited {result.returncode}: {result.stderr[-400:]}"
                )
            if backend == "claude":
                transport = json.loads(result.stdout)
                if transport.get("is_error"):
                    raise RuntimeError(str(transport.get("result")))
                record["usage"] = transport.get("modelUsage", {})
                record["reported_cost_usd"] = transport.get("total_cost_usd")
                text = transport.get("result", "")
            else:
                events = [
                    json.loads(line)
                    for line in result.stdout.splitlines()
                    if line.strip().startswith("{")
                ]
                forbidden = [
                    e
                    for e in events
                    if e.get("item", {}).get("type")
                    not in (None, "agent_message", "reasoning")
                    and e.get("type", "").startswith("item.")
                ]
                if forbidden:
                    raise RuntimeError(
                        "inference attempted a tool call; result rejected"
                    )
                record["usage"] = [e.get("usage") for e in events if e.get("usage")]
                text = (Path(tmp) / "answer.txt").read_text()
            record["response_text"] = text
            try:
                record["response"] = (
                    extract_json(text)
                    if response_format == "json"
                    else {"answer": text}
                )
                record["status"] = "ok"
            except (ValueError, json.JSONDecodeError) as exc:
                record.update(
                    response=None,
                    status="invalid_json",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            subprocess.TimeoutExpired,
        ) as exc:
            if isinstance(exc, subprocess.TimeoutExpired):
                for field, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
                    record[field] = (
                        value.decode("utf-8", errors="replace")
                        if isinstance(value, bytes)
                        else value
                    )
            record["status"] = "error"
            record["error"] = str(exc)
            record["error_type"] = type(exc).__name__
        record["elapsed_seconds"] = round(time.time() - started, 3)
        record["cache_key"] = key
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    if record["status"] not in ("ok", "invalid_json"):
        raise RuntimeError(f"{record['error']} (record: {path})")
    return record
