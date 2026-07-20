"""Step 2 — Interview generation and verification.

Runs two phases inside one step:

  1. Generation     — fills prompt.txt with seed data, calls the LLM, writes the
                      interview transcript + draft extracted profile.
  2. Verification   — fills verification_prompt.txt with seed + transcript +
                      draft profile, calls the LLM, writes the verification
                      report + corrected extracted profile + hidden_facts.

Iterative refinement loop: if verification returns a FAIL verdict, the
generation is re-run up to --max-iterations times. If every attempt still fails,
the last attempt's outputs are retained and the process exits with a non-zero
status.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm import (
    API_BACKENDS,
    SUPPORTED_BACKENDS,
    make_client,
    call_llm,
    check_api_key,
    provider_for_backend,
    default_model_for_backend,
    SUPPORTED_PROVIDERS,
)
from utils import (
    load_prompt,
    extract_json,
    fill_seed_placeholders,
    fill,
)

STEP_DIR = Path(__file__).parent
PROMPT_PATH = STEP_DIR / "prompt.txt"
VERIFICATION_PROMPT_PATH = STEP_DIR / "verification_prompt.txt"

DEFAULT_MAX_ITERATIONS = 3

def run_generation(
    client, model: str, seed: dict[str, Any], gpt_reasoning: str,
    provider: str = "anthropic", backend: str = "anthropic-api",
) -> dict[str, Any]:
    prompt = fill_seed_placeholders(load_prompt(PROMPT_PATH), seed)
    raw = call_llm(client, model, prompt, gpt_reasoning, provider=provider, backend=backend)
    return extract_json(raw)


def run_verification(
    client,
    model: str,
    seed: dict[str, Any],
    interview: dict[str, Any],
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
) -> dict[str, Any]:
    template = fill_seed_placeholders(load_prompt(VERIFICATION_PROMPT_PATH), seed)
    template = fill(template, "{{INSERT_SEED_JSON_HERE}}", seed)
    template = fill(
        template, "{{INSERT_TRANSCRIPT_JSON_HERE}}", interview["transcript"]
    )
    template = fill(
        template,
        "{{INSERT_EXTRACTED_PROFILE_JSON_HERE}}",
        interview["extracted_profile"],
    )
    raw = call_llm(client, model, template, gpt_reasoning, provider=provider, backend=backend)
    return extract_json(raw)


def overall_verdict(verification: dict[str, Any]) -> str:
    return verification.get("verification", {}).get("overall_verdict", "UNKNOWN")


def run_step(
    seed_path: Path,
    output_dir: Path,
    model: str,
    verifier_model: str,
    max_iterations: int,
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
) -> int:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    client = make_client(provider) if backend in API_BACKENDS else None
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = seed_path.stem.replace("_seed", "")
    interview_out = output_dir / f"{base_name}_interview.json"
    verification_out = output_dir / f"{base_name}_verification.json"

    interview: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None

    for attempt in range(1, max_iterations + 1):
        print(f"[attempt {attempt}/{max_iterations}] generating interview for {base_name}")
        interview = run_generation(client, model, seed, gpt_reasoning, provider=provider, backend=backend)
        interview_out.write_text(json.dumps(interview, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"[attempt {attempt}/{max_iterations}] verifying interview for {base_name}")
        verification = run_verification(client, verifier_model, seed, interview, gpt_reasoning, provider=provider, backend=backend)
        verification_out.write_text(json.dumps(verification, indent=2, ensure_ascii=False), encoding="utf-8")

        verdict = overall_verdict(verification)
        print(f"[attempt {attempt}/{max_iterations}] verdict: {verdict}")
        if verdict in {"PASS", "PASS_WITH_REVISIONS"}:
            return 0

    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True, help="Path to a seed JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=STEP_DIR / "data_samples",
        help="Directory to write interview and verification outputs into",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--verifier-model", default=None)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument(
        "--gpt-reasoning",
        default="high",
        help="OpenAI model (openai-api, codex) reasoning effort.",
    )
    parser.add_argument("--provider", default=None, choices=SUPPORTED_PROVIDERS)
    parser.add_argument("--backend", default="anthropic-api", choices=SUPPORTED_BACKENDS)
    args = parser.parse_args()

    provider = provider_for_backend(args.backend, args.provider) if args.backend in API_BACKENDS else (args.provider or "anthropic")

    if args.model is None:
        args.model = default_model_for_backend(args.backend, "generator")
    if args.verifier_model is None:
        args.verifier_model = default_model_for_backend(args.backend, "verifier")

    if args.backend in API_BACKENDS and not check_api_key(provider):
        print(f"API key for {provider} is not set.", file=sys.stderr)
        sys.exit(2)

    sys.exit(run_step(args.seed, args.output, args.model, args.verifier_model, args.max_iterations, args.gpt_reasoning, provider, args.backend))


if __name__ == "__main__":
    main()
