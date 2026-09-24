"""Step 5 — Test case generation and verification.

Two phases:

  1. Generation     — fills prompt.txt with the corrected extracted profile,
                      app logs, and corrected social circle. Calls the LLM
                      and writes the test case file.
  2. Verification   — fills verification_prompt.txt with the test cases plus
                      the profile and app logs. Calls the LLM and writes the
                      verification report and corrected test cases.

Iterative refinement loop: if the verification report contains any REJECTED
case or a non-empty coverage_deficit, the generation is re-run up to
--max-iterations times. The last attempt's outputs are always retained.
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
from pipeline_integrity.artifacts import distinct_models, file_digest, provenance, publish, tracked
from step6_benchmark_runner.generator import strip_ground_truth, strip_to_raw_logs
from step6_benchmark_runner.t5_contract import (
    fingerprint,
    log_strings,
    validate_contract,
)
from utils import (
    extract_json,
    fill,
    load_prompt,
)

STEP_DIR = Path(__file__).parent
PROMPT_PATH = STEP_DIR / "prompt.txt"
VERIFICATION_PROMPT_PATH = STEP_DIR / "verification_prompt.txt"
PUBLIC_REVIEW_PROMPT_PATH = STEP_DIR / "public_review_prompt.txt"

DEFAULT_MAX_ITERATIONS = 3


def strip_filler_for_step5(app_logs: dict[str, Any]) -> dict[str, Any]:
    """Remove filler sessions from app logs before injecting into Step 5 prompt.

    Filler sessions exist to challenge the evaluator in Step 6 (they are noise
    the model must sift through). Step 5 only needs meaningful sessions and
    hidden_facts to build evidence anchors and test cases. Stripping filler
    reduces the prompt from ~826K tokens to ~185K tokens.
    """
    trimmed = dict(app_logs)
    messenger = dict(app_logs.get("messenger", {}))
    messenger.pop("filler_sessions", None)
    trimmed["messenger"] = messenger
    trimmed.pop("cross_app_index", None)
    trimmed.pop("token_stats", None)
    trimmed.pop("verified_fragment_registry", None)
    trimmed.pop("verified_fragment_check", None)
    trimmed.pop("decoy_registry", None)
    trimmed.pop("decoy_check", None)
    trimmed.pop("_validation", None)
    trimmed.pop("surprises_woven", None)
    trimmed.pop("metadata", None)
    return trimmed


def run_generation(
    client,
    model: str,
    app_logs: dict[str, Any],
    corrected_social_circle: dict[str, Any],
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
    min_cases: int = 45,
    max_cases: int = 55,
) -> dict[str, Any]:
    template = load_prompt(PROMPT_PATH)
    logs_for_prompt = strip_filler_for_step5(app_logs)
    template = fill(template, "{{INSERT_APP_LOGS_JSON_HERE}}", logs_for_prompt)
    template = fill(
        template,
        "{{INSERT_CORRECTED_SOCIAL_CIRCLE_JSON_HERE}}",
        corrected_social_circle,
    )
    if min_cases < 45 or max_cases < 45:
        template += (
            f"\nRun scope: smoke test. Produce {min_cases}..{max_cases} cases. "
            "This overrides the general case-count and distribution targets only. "
            "Use questions genuinely supported by this small source; preserve all evidence and contract requirements."
        )
    raw = call_llm(client, model, template, gpt_reasoning, provider=provider, backend=backend)
    return extract_json(raw)


def run_verification(
    client,
    model: str,
    test_cases: dict[str, Any],
    app_logs: dict[str, Any],
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
    public_review: dict[str, Any] | None = None,
    min_cases: int = 45,
    max_cases: int = 55,
) -> dict[str, Any]:
    template = load_prompt(VERIFICATION_PROMPT_PATH)
    template = fill(template, "{{INSERT_TEST_CASES_JSON_HERE}}", test_cases)
    template = fill(template, "{{INSERT_APP_LOGS_JSON_HERE}}", app_logs)
    template = fill(template, "{{INSERT_PUBLIC_REVIEW_JSON_HERE}}", public_review or {})
    if min_cases < 45 or max_cases < 45:
        template += (
            f"\nRun scope: smoke test with {min_cases}..{max_cases} cases. "
            "The broad distribution and subcategory coverage targets do not apply. "
            "All seven review criteria and complete per-case records remain mandatory."
        )
    raw = call_llm(client, model, template, gpt_reasoning, provider=provider, backend=backend)
    return extract_json(raw)


def verification_passed(verification: dict[str, Any]) -> bool:
    summary = verification.get("verification_metadata", {}).get("summary", {})
    rejected = summary.get("rejected", 0)
    corrected = verification.get("corrected_test_cases", {})
    coverage_deficit = corrected.get("coverage_deficit", [])
    return (
        rejected == 0
        and not coverage_deficit
        and verification.get("admission", {}).get("complete") is True
    )


def run_public_review(
    client,
    model,
    test_cases,
    app_logs,
    gpt_reasoning,
    provider="anthropic",
    backend="anthropic-api",
):
    raw_logs = strip_to_raw_logs(app_logs)
    review = {"assessments": []}
    for case in test_cases["test_cases"]:
        single = {**test_cases, "test_cases": [case]}
        template = fill(
            load_prompt(PUBLIC_REVIEW_PROMPT_PATH), "{{PUBLIC_CASES}}", strip_ground_truth(single)
        )
        template = fill(template, "{{PUBLIC_HISTORY}}", raw_logs)
        result = extract_json(
            call_llm(client, model, template, gpt_reasoning, provider=provider, backend=backend)
        )
        admission.public_review(single, result, raw_logs)
        review["assessments"].extend(result["assessments"])
    admission.public_review(test_cases, review, raw_logs)
    return review


def validate_type5_contracts(
    test_cases: dict[str, Any], app_logs: dict[str, Any]
) -> dict[str, list[str]]:
    """Newly generated Type 5 cases must carry usable, log-grounded contracts."""
    source_text = log_strings(app_logs)
    problems = {}
    for case in test_cases.get("test_cases", []):
        typ = str(case.get("type", "")).lower()
        if typ == "type_5_agent_behavior" or (typ.startswith("5") and "_" in typ):
            errors = validate_contract(case, source_text)
            if errors:
                problems[case.get("id", "<missing>")] = errors
    return problems


def enforce_contract_verification(test_cases: dict[str, Any], verification: dict[str, Any]) -> None:
    """A model's summary cannot substitute for an actual contract review."""
    evaluations = verification.get("evaluations")
    evaluations = (
        [e for e in evaluations if isinstance(e, dict)] if isinstance(evaluations, list) else []
    )
    verification["evaluations"] = evaluations
    for case in test_cases.get("test_cases", []):
        if "type_5_contract" not in case:
            continue
        records = [e for e in evaluations if e.get("test_case_id", e.get("id")) == case.get("id")]
        check = records[0].get("behavior_contract_check") if len(records) == 1 else None
        checked = isinstance(check, dict) and check.get("verdict") in ("PASS", "WARN")
        checked = checked and records[0].get("overall_verdict") in (
            "VERIFIED",
            "FLAGGED",
        )
        if not checked:
            if len(records) == 1:
                records[0]["overall_verdict"] = "REJECTED"
                records[0]["revision_note"] = (
                    "Behavior contract review missing, duplicated, malformed or FAIL."
                )
            else:
                evaluations[:] = [e for e in evaluations if e not in records]
                evaluations.append(
                    {
                        "test_case_id": case["id"],
                        "overall_verdict": "REJECTED",
                        "revision_note": "Missing or duplicate behavior contract review.",
                    }
                )
        else:
            # Written by code after the independent review, never by the model.
            records[0]["behavior_case_sha256"] = fingerprint(case)
    rejected = sum(e.get("overall_verdict") == "REJECTED" for e in evaluations)
    summary = verification.setdefault("verification_metadata", {}).setdefault("summary", {})
    summary["rejected"] = max(rejected, summary.get("rejected", 0))


def extract_base_name(profile_path: Path) -> str:
    return profile_path.stem.replace("_verification", "")


@tracked(
    "step5",
    inputs=("profile_path", "app_logs_path", "social_circle_path", "existing_cases_path"),
    outputs=("_test_cases.json", "_test_cases_verification.json"),
    base_arg="profile_path",
    base_suffix="_verification",
)
def run_step(
    profile_path: Path,
    app_logs_path: Path,
    social_circle_path: Path,
    output_dir: Path,
    model: str,
    verifier_model: str,
    max_iterations: int,
    gpt_reasoning: str,
    provider: str = "anthropic",
    backend: str = "anthropic-api",
    allow_legacy_inputs: bool = False,
    min_cases: int = 45,
    max_cases: int = 55,
    existing_cases_path: Path | None = None,
) -> int:
    distinct_models(model, verifier_model)
    if max_iterations < 1 or min_cases < 1 or max_cases < min_cases:
        raise ValueError("Invalid iteration or case coverage limits")
    admission.profile(json.loads(profile_path.read_text(encoding="utf-8")))
    provenance(profile_path, allow_legacy=allow_legacy_inputs)
    circle_manifest = provenance(social_circle_path, allow_legacy=allow_legacy_inputs)
    log_manifest = provenance(app_logs_path, allow_legacy=allow_legacy_inputs)
    for manifest in (circle_manifest, log_manifest):
        if manifest.get("inputs", {}).get("profile_path", {}).get(
            "sha256", file_digest(profile_path)
        ) != file_digest(profile_path):
            raise ValueError("Upstream artifact belongs to a different profile revision")
    if log_manifest.get("inputs", {}).get("social_circle_path", {}).get(
        "sha256", file_digest(social_circle_path)
    ) != file_digest(social_circle_path):
        raise ValueError("App logs belong to a different social circle revision")
    app_logs = json.loads(app_logs_path.read_text(encoding="utf-8"))
    social_circle_file = json.loads(social_circle_path.read_text(encoding="utf-8"))
    corrected_social_circle = admission.social_circle(social_circle_file)

    client = make_client(provider) if backend in API_BACKENDS else None
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = extract_base_name(profile_path)
    test_cases_out = output_dir / f"{base_name}_test_cases.json"
    verification_out = output_dir / f"{base_name}_test_cases_verification.json"

    seen_datasets = set()
    attempt_limit = 1 if existing_cases_path else max_iterations
    for attempt in range(1, attempt_limit + 1):
        print(f"[attempt {attempt}/{max_iterations}] generating test cases for {base_name}")
        test_cases = (
            json.loads(existing_cases_path.read_text(encoding="utf-8"))
            if existing_cases_path
            else run_generation(
                client,
                model,
                app_logs,
                corrected_social_circle,
                gpt_reasoning,
                provider=provider,
                backend=backend,
                min_cases=min_cases,
                max_cases=max_cases,
            )
        )
        publish(test_cases_out, test_cases)
        admission.case_inventory(test_cases)
        identity = fingerprint(test_cases)
        if identity in seen_datasets:
            raise ValueError("An unchanged rejected dataset cannot be rerolled through review")
        seen_datasets.add(identity)

        contract_problems = validate_type5_contracts(test_cases, app_logs)
        if contract_problems:
            # Reject malformed answer keys before spending a verification call.
            # Keep a normal rejection report so later stages cannot consume them.
            verification = {
                "verification_metadata": {"summary": {"rejected": len(contract_problems)}},
                "evaluations": [
                    {
                        "test_case_id": cid,
                        "overall_verdict": "REJECTED",
                        "revision_note": "; ".join(errors),
                    }
                    for cid, errors in contract_problems.items()
                ],
                "corrected_test_cases": {"coverage_deficit": ["Invalid Type 5 contracts"]},
                "contract_validation_errors": contract_problems,
            }
            publish(verification_out, verification)
            print(
                f"[attempt {attempt}/{max_iterations}] invalid Type 5 contracts: {contract_problems}"
            )
            continue

        print(f"[attempt {attempt}/{max_iterations}] verifying test cases for {base_name}")
        public_review = run_public_review(
            client,
            verifier_model,
            test_cases,
            app_logs,
            gpt_reasoning,
            provider=provider,
            backend=backend,
        )
        publish(output_dir / f"{base_name}_public_review.json", public_review)
        verification = run_verification(
            client,
            verifier_model,
            test_cases,
            app_logs,
            gpt_reasoning,
            provider=provider,
            backend=backend,
            public_review=public_review,
            min_cases=min_cases,
            max_cases=max_cases,
        )
        enforce_contract_verification(test_cases, verification)
        publish(verification_out, verification)
        admission.seal_cases(
            test_cases,
            verification,
            app_logs,
            public_review,
            strip_to_raw_logs(app_logs),
            min_cases=min_cases,
            max_cases=max_cases,
        )
        publish(verification_out, verification)

        if verification_passed(verification):
            print(f"[attempt {attempt}/{max_iterations}] passed")
            return 0
        summary = verification.get("verification_metadata", {}).get("summary", {})
        deficit = verification.get("corrected_test_cases", {}).get("coverage_deficit", [])
        print(
            f"[attempt {attempt}/{max_iterations}] rejected={summary.get('rejected', 0)} "
            f"coverage_deficit={len(deficit)}"
        )

    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        required=True,
        help="Path to a corrected profile file ({persona}_verification.json)",
    )
    parser.add_argument(
        "--app-logs",
        type=Path,
        required=True,
        help="Path to the persona's app logs file ({persona}_app_logs.json)",
    )
    parser.add_argument(
        "--social-circle",
        type=Path,
        required=True,
        help="Path to the corrected social circle file ({persona}_social_circle_verification.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=STEP_DIR / "runs",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--verifier-model",
        default=None,
        help="Independent model for the reverse-inferability gate",
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument(
        "--gpt-reasoning", default="high", help="OpenAI model (openai-api, codex) reasoning effort."
    )
    parser.add_argument("--provider", default=None, choices=SUPPORTED_PROVIDERS)
    parser.add_argument("--backend", default="anthropic-api", choices=SUPPORTED_BACKENDS)
    parser.add_argument(
        "--allow-legacy-inputs",
        action="store_true",
        help="Import historical upstream artifacts; cases still require a new complete review.",
    )
    parser.add_argument("--min-cases", type=int, default=45)
    parser.add_argument("--max-cases", type=int, default=55)
    parser.add_argument(
        "--review-existing",
        type=Path,
        help="Review these frozen cases into a separate output directory without regenerating them.",
    )
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
        print(f"API key not set for provider {provider}.", file=sys.stderr)
        sys.exit(2)

    sys.exit(
        run_step(
            args.profile,
            args.app_logs,
            args.social_circle,
            args.output,
            args.model,
            args.verifier_model,
            args.max_iterations,
            args.gpt_reasoning,
            provider=provider,
            backend=args.backend,
            allow_legacy_inputs=args.allow_legacy_inputs,
            min_cases=args.min_cases,
            max_cases=args.max_cases,
            existing_cases_path=args.review_existing,
        )
    )


if __name__ == "__main__":
    main()
