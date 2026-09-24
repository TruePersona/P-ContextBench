"""Step 3 — Social circle generation and verification.

Runs two phases:

  1. Generation     — fills prompt.txt with the corrected extracted profile and
                      interview transcript, calls the LLM, writes the draft
                      social circle.
  2. Verification   — fills verification_prompt.txt with the interview,
                      corrected profile, and draft social circle, calls the LLM,
                      writes the verification report + corrected social circle.

Iterative refinement loop: if verification returns a FAIL verdict, the
generation is re-run up to --max-iterations times.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm import (
    API_BACKENDS,
    SUPPORTED_BACKENDS,
    SUPPORTED_PROVIDERS,
    call_llm,
    check_api_key,
    default_model_for_backend,
    make_client,
    provider_for_backend,
)
from pipeline_integrity import admission
from pipeline_integrity.artifacts import distinct_models, publish, require_same_attempt, tracked
from utils import (
    extract_json,
    fill,
    load_prompt,
)

STEP_DIR = Path(__file__).parent
PROMPT_PATH = STEP_DIR / "prompt.txt"
VERIFICATION_PROMPT_PATH = STEP_DIR / "verification_prompt.txt"

DEFAULT_MAX_ITERATIONS = 3


def fill_identity_placeholders(template: str, profile: dict[str, Any]) -> str:
    return template.replace("{{participant_id}}", profile.get("participant_id", "")).replace(
        "{{name}}", profile.get("name", "")
    )


def run_generation(
    client,
    model: str,
    profile: dict[str, Any],
    transcript: list[dict[str, Any]],
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
) -> dict[str, Any]:
    template = load_prompt(PROMPT_PATH)
    template = fill_identity_placeholders(template, profile)
    template = fill(template, "{{INSERT_CORRECTED_EXTRACTED_PROFILE_JSON_HERE}}", profile)
    template = fill(template, "{{INSERT_TRANSCRIPT_JSON_HERE}}", transcript)
    raw = call_llm(client, model, template, gpt_reasoning, provider=provider, backend=backend)
    return extract_json(raw)


def run_verification(
    client,
    model: str,
    profile: dict[str, Any],
    transcript: list[dict[str, Any]],
    social_circle: dict[str, Any],
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
) -> dict[str, Any]:
    template = load_prompt(VERIFICATION_PROMPT_PATH)
    template = fill_identity_placeholders(template, profile)
    template = fill(template, "{{INSERT_TRANSCRIPT_JSON_HERE}}", transcript)
    template = fill(template, "{{INSERT_CORRECTED_EXTRACTED_PROFILE_JSON_HERE}}", profile)
    template = fill(template, "{{INSERT_SOCIAL_CIRCLE_JSON_HERE}}", social_circle)
    raw = call_llm(client, model, template, gpt_reasoning, provider=provider, backend=backend)
    return extract_json(raw)


def overall_verdict(verification: dict[str, Any]) -> str:
    return verification.get("verification", {}).get("overall_verdict", "UNKNOWN")


@tracked(
    "step3",
    inputs=("profile_path", "transcript_path"),
    outputs=("_social_circle.json", "_social_circle_verification.json"),
    base_arg="profile_path",
    base_suffix="_verification",
)
def run_step(
    profile_path: Path,
    transcript_path: Path,
    output_dir: Path,
    model: str,
    verifier_model: str,
    max_iterations: int,
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
    allow_legacy_inputs: bool = False,
) -> int:
    distinct_models(model, verifier_model)
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    require_same_attempt(profile_path, transcript_path, allow_legacy=allow_legacy_inputs)
    verification_bundle = json.loads(profile_path.read_text(encoding="utf-8"))
    profile = admission.profile(verification_bundle)

    interview = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript = admission.interview(interview, participant_id=profile["participant_id"])

    client = make_client(provider) if backend in API_BACKENDS else None
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = profile_path.stem.replace("_verification", "")
    circle_out = output_dir / f"{base_name}_social_circle.json"
    verification_out = output_dir / f"{base_name}_social_circle_verification.json"

    for attempt in range(1, max_iterations + 1):
        print(f"[attempt {attempt}/{max_iterations}] generating social circle for {base_name}")
        social_circle = run_generation(
            client, model, profile, transcript, gpt_reasoning, provider=provider, backend=backend
        )
        publish(circle_out, social_circle)

        print(f"[attempt {attempt}/{max_iterations}] verifying social circle for {base_name}")
        verification = run_verification(
            client,
            verifier_model,
            profile,
            transcript,
            social_circle,
            gpt_reasoning,
            provider=provider,
            backend=backend,
        )
        publish(verification_out, verification)

        verdict = overall_verdict(verification)
        print(f"[attempt {attempt}/{max_iterations}] verdict: {verdict}")
        if verdict in {"PASS", "PASS_WITH_REVISIONS"}:
            admission.social_circle(verification)
            return 0

    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        required=True,
        help="Path to the Step 2 verification JSON (contains corrected_extracted_profile)",
    )
    parser.add_argument(
        "--transcript",
        type=Path,
        required=True,
        help="Path to the Step 2 interview JSON (contains transcript)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=STEP_DIR / "runs",
        help="Directory to write social circle and verification outputs into",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--verifier-model",
        default=None,
        help="Independent model for the reverse-inferability gate",
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument(
        "--allow-legacy-inputs",
        action="store_true",
        help="Import historical inputs without bound provenance; structural checks still apply.",
    )
    parser.add_argument(
        "--gpt-reasoning",
        default="high",
        help="OpenAI model (openai-api, codex) reasoning effort.",
    )
    parser.add_argument("--provider", default=None, choices=SUPPORTED_PROVIDERS)
    parser.add_argument("--backend", default="anthropic-api", choices=SUPPORTED_BACKENDS)
    args = parser.parse_args()

    provider = (
        provider_for_backend(args.backend, args.provider)
        if args.backend in API_BACKENDS
        else (args.provider or "anthropic")
    )

    if args.model is None:
        args.model = default_model_for_backend(args.backend, "generator")
    if args.verifier_model is None:
        args.verifier_model = default_model_for_backend(args.backend, "verifier")

    if args.backend in API_BACKENDS and not check_api_key(provider):
        print(f"API key for {provider} is not set.", file=sys.stderr)
        sys.exit(2)

    sys.exit(
        run_step(
            args.profile,
            args.transcript,
            args.output,
            args.model,
            args.verifier_model,
            args.max_iterations,
            args.gpt_reasoning,
            provider,
            args.backend,
            args.allow_legacy_inputs,
        )
    )


if __name__ == "__main__":
    main()
