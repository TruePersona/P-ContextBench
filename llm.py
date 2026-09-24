"""Shared LLM client for all step generators.

Supports anthropic and openai providers. Each step's generator.py
imports make_client() and call_llm() from here.
"""

from __future__ import annotations

import os
import sys

from pipeline_integrity.artifacts import record_call, transport_note

SUPPORTED_PROVIDERS = ("anthropic", "openai", "openrouter")
SUBSCRIPTION_BACKENDS = ("claude", "codex")
API_BACKENDS = ("anthropic-api", "openai-api")
SUPPORTED_BACKENDS = SUBSCRIPTION_BACKENDS + API_BACKENDS
CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude.cmd" if sys.platform == "win32" else "claude")
CODEX_CMD = os.environ.get("CODEX_CMD", "codex.exe" if sys.platform == "win32" else "codex")
INFERENCE_SYSTEM = (
    "You are a text-only inference endpoint. Use only the supplied task and context. "
    "Do not inspect files, run commands, browse, or call tools. "
    "Return only the requested JSON, without commentary or markdown fences."
)


def make_client(provider: str):
    if provider == "anthropic":
        import anthropic

        return anthropic.Anthropic()
    if provider == "openai":
        from openai import OpenAI

        return OpenAI()
    if provider == "openrouter":
        import os

        from openai import OpenAI

        return OpenAI(
            base_url="https://openrouter.ai/api/v1", api_key=os.environ.get("OPENROUTER_API_KEY")
        )
    raise ValueError(f"Unknown provider: {provider}")


def call_llm(
    client,
    model: str,
    prompt: str,
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
    response_format: str | None = "text",
) -> str:
    def invoke():
        if backend in SUBSCRIPTION_BACKENDS:
            return call_subscription_cli(prompt, model, backend, gpt_reasoning)
        return call_api(client, model, prompt, gpt_reasoning, provider, response_format)

    return record_call(
        invoke,
        {
            "model": model,
            "backend": backend,
            "provider": provider,
            "reasoning": gpt_reasoning,
            "response_format": response_format,
        },
        prompt,
    )


def call_api(
    client,
    model: str,
    prompt: str,
    gpt_reasoning: str | None = "high",
    provider: str = "anthropic",
    response_format: str | None = "text",
    max_retries: int = 3,
) -> str:
    import time

    for attempt in range(1, max_retries + 1):
        try:
            if provider == "anthropic":
                with client.messages.stream(
                    model=model,
                    system=INFERENCE_SYSTEM,
                    max_tokens=64_000,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": prompt,
                                    "cache_control": {"type": "ephemeral"},
                                }
                            ],
                        }
                    ],
                ) as stream:
                    message = stream.get_final_message()
                    answer_text = "".join(
                        block.text for block in message.content if block.type == "text"
                    )
                    transport_note(
                        attempt=attempt,
                        usage=message.usage.model_dump(),
                        stop_reason=message.stop_reason,
                        system=INFERENCE_SYSTEM,
                        raw_text=answer_text,
                        model=message.model,
                        max_tokens=64000,
                        temperature=None,
                    )
                    if message.stop_reason == "max_tokens":
                        raise ValueError("Anthropic output exceeded the completion budget")
                    return answer_text
            if provider in {"openai", "openrouter"}:
                reasoning_field = (
                    {"reasoning_effort": gpt_reasoning, "max_completion_tokens": 64000}
                    if provider == "openai"
                    else {
                        "reasoning": {"effort": gpt_reasoning, "exclude": True},
                        "max_completion_tokens": 64000,
                    }
                )
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": INFERENCE_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": response_format},
                    extra_body=reasoning_field,
                )
                transport_note(
                    attempt=attempt,
                    usage=response.usage.model_dump() if response.usage else None,
                    stop_reason=response.choices[0].finish_reason,
                    model=response.model,
                    temperature=None,
                    system=INFERENCE_SYSTEM,
                    raw_text=response.choices[0].message.content,
                )
                if response.choices[0].finish_reason == "length":
                    raise ValueError("Output exceeded the completion budget")
                return response.choices[0].message.content
            raise ValueError(f"Unknown provider: {provider}")
        except (ConnectionError, OSError) as e:
            transport_note(attempt=attempt, error_type=type(e).__name__)
            if attempt == max_retries:
                raise
            wait = 2**attempt
            print(
                f"[llm] connection error (attempt {attempt}/{max_retries}), retrying in {wait}s: {e}"
            )
            time.sleep(wait)
        except Exception as e:
            transport_note(attempt=attempt, error_type=type(e).__name__)
            if "ReadError" in type(e).__name__ or "10054" in str(e):
                if attempt == max_retries:
                    raise
                wait = 2**attempt
                print(
                    f"[llm] network drop (attempt {attempt}/{max_retries}), retrying in {wait}s: {e}"
                )
                time.sleep(wait)
            else:
                raise


def default_model_for_backend(backend: str, role: str = "generator") -> str:
    if backend in {"claude", "anthropic-api"}:
        if role in {"verifier", "judge"}:
            return "claude-sonnet-4-6"
        if role == "evaluator":
            return "claude-haiku-4-5"
        return "claude-opus-4-7"
    if backend in {"codex", "openai-api"}:
        if role == "evaluator":
            return "gpt-5.4-mini"
        if role == "judge":
            return "gpt-5.4"
        if role == "verifier":
            return "gpt-5.4"
        return "gpt-5.5"
    raise ValueError(f"Unsupported backend: {backend}")


def check_api_key(provider: str) -> bool:
    import os

    if provider == "anthropic":
        return "ANTHROPIC_API_KEY" in os.environ
    if provider == "openai":
        return "OPENAI_API_KEY" in os.environ
    if provider == "openrouter":
        return "OPENROUTER_API_KEY" in os.environ
    return False


def provider_for_backend(backend: str, provider: str | None = None) -> str:
    if backend == "anthropic-api":
        return provider or "anthropic"
    if backend == "openai-api":
        return provider or "openai"
    raise ValueError(f"Backend {backend!r} is not an API backend")


def call_claude_cli(
    prompt: str,
    model: str | None = None,
    max_retries: int = 2,
) -> str:
    """Call `claude -p` as a pure text subprocess."""
    import subprocess
    import tempfile

    cmd = [
        CLAUDE_CMD,
        "-p",
        "--safe-mode",
        "--tools",
        "",
        "--no-session-persistence",
        "--system-prompt",
        INFERENCE_SYSTEM,
    ]
    if model:
        cmd += ["--model", model]

    wrapped_prompt = prompt

    last_stderr = ""
    for attempt in range(max_retries + 1):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(wrapped_prompt)
        try:
            with (
                tempfile.TemporaryDirectory(prefix="personabench_claude_") as cwd,
                open(tmp.name, "r", encoding="utf-8") as stream,
            ):
                env = dict(os.environ)
                env.pop("ANTHROPIC_API_KEY", None)
                result = subprocess.run(
                    cmd,
                    stdin=stream,
                    capture_output=True,
                    timeout=3600,
                    check=False,
                    cwd=cwd,
                    env=env,
                )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            transport_note(
                attempt=attempt + 1,
                command=cmd,
                effective_prompt=wrapped_prompt,
                returncode=result.returncode,
                raw_stdout=stdout,
                raw_stderr=stderr,
            )
            if result.returncode == 0 and stdout.strip():
                return stdout.strip()
            last_stderr = stderr
            if attempt < max_retries:
                print(f"  retry {attempt + 1}/{max_retries} (stderr: {stderr[:200]})")
        finally:
            os.unlink(tmp.name)
    raise RuntimeError(f"claude CLI failed after {max_retries + 1} attempts: {last_stderr[:500]}")


def call_codex_cli(
    prompt: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
    max_retries: int = 2,
) -> str:
    """Call `codex exec` as an isolated subscription-backed subprocess."""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    reasoning_effort = reasoning_effort or os.environ.get("CODEX_REASONING_EFFORT", "high")
    wrapped_prompt = INFERENCE_SYSTEM + "\n\n" + prompt

    last_stderr = ""
    for attempt in range(max_retries + 1):
        with tempfile.TemporaryDirectory(prefix="p-contextbench_codex_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            prompt_path = tmp_path / "prompt.txt"
            out_path = tmp_path / "last_message.txt"
            cmd = [
                CODEX_CMD,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "-c",
                f"model_reasoning_effort={reasoning_effort!r}",
                "-c",
                'web_search="disabled"',
                "-c",
                "features.shell_tool=false",
                "-C",
                str(tmp_path),
                "-o",
                str(out_path),
            ]
            if model:
                cmd += ["--model", model]
            cmd.append("-")
            if sys.platform == "win32":

                def ps_quote(value: str) -> str:
                    return "'" + value.replace("'", "''") + "'"

                prompt_path.write_text(wrapped_prompt, encoding="utf-8")
                model_arg = f" --model {ps_quote(model)}" if model else ""
                ps_script = (
                    "$ErrorActionPreference = 'Stop'; "
                    f"$prompt = Get-Content -Raw -LiteralPath {ps_quote(str(prompt_path))}; "
                    f"$prompt | & {ps_quote(CODEX_CMD)} exec --ephemeral "
                    "--ignore-user-config --skip-git-repo-check --ignore-rules --sandbox read-only "
                    "-c 'web_search=\"disabled\"' -c 'features.shell_tool=false' "
                    f"-c {ps_quote('model_reasoning_effort=' + repr(reasoning_effort))} "
                    f"-C {ps_quote(str(tmp_path))} -o {ps_quote(str(out_path))}"
                    f"{model_arg} -"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=3600,
                    check=False,
                    cwd=tmp_path,
                )
            else:
                result = subprocess.run(
                    cmd,
                    input=wrapped_prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=3600,
                    check=False,
                    cwd=tmp_path,
                )
            transport_note(
                attempt=attempt + 1,
                command=cmd,
                effective_prompt=wrapped_prompt,
                returncode=result.returncode,
                raw_stdout=result.stdout,
                raw_stderr=result.stderr,
            )
            if result.returncode == 0:
                if out_path.exists():
                    text = out_path.read_text(encoding="utf-8").strip()
                    if text:
                        return text
                if result.stdout.strip():
                    return result.stdout.strip()
            last_stderr = result.stderr
            if attempt < max_retries:
                print(f"  retry {attempt + 1}/{max_retries} (stderr: {last_stderr[:200]})")
    raise RuntimeError(f"codex CLI failed after {max_retries + 1} attempts: {last_stderr[:500]}")


def call_subscription_cli(
    prompt: str,
    model: str | None,
    backend: str,
    gpt_reasoning: str | None = None,
    max_retries: int = 2,
) -> str:
    if backend == "claude":
        return call_claude_cli(prompt, model, max_retries=max_retries)
    if backend == "codex":
        return call_codex_cli(
            prompt,
            model,
            reasoning_effort=gpt_reasoning,
            max_retries=max_retries,
        )
    raise ValueError(f"Unknown subscription backend: {backend}")
