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
) -> dict[str, Any]:
    template = load_prompt(PROMPT_PATH)
    logs_for_prompt = strip_filler_for_step5(app_logs)
    template = fill(template, "{{INSERT_APP_LOGS_JSON_HERE}}", logs_for_prompt)
    template = fill(
        template,
        "{{INSERT_CORRECTED_SOCIAL_CIRCLE_JSON_HERE}}",
        corrected_social_circle,
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
) -> dict[str, Any]:
    template = load_prompt(VERIFICATION_PROMPT_PATH)
    template = fill(template, "{{INSERT_TEST_CASES_JSON_HERE}}", test_cases)
    logs_for_prompt = strip_filler_for_step5(app_logs)
    template = fill(template, "{{INSERT_APP_LOGS_JSON_HERE}}", logs_for_prompt)
    raw = call_llm(client, model, template, gpt_reasoning, provider=provider, backend=backend)
    return extract_json(raw)


def verification_passed(verification: dict[str, Any]) -> bool:
    summary = verification.get("verification_metadata", {}).get("summary", {})
    rejected = summary.get("rejected", 0)
    corrected = verification.get("corrected_test_cases", {})
    coverage_deficit = corrected.get("coverage_deficit", [])
    return rejected == 0 and not coverage_deficit


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


def enforce_contract_verification(
    test_cases: dict[str, Any], verification: dict[str, Any]
) -> None:
    """A model's summary cannot substitute for an actual contract review."""
    evaluations = verification.get("evaluations")
    evaluations = (
        [e for e in evaluations if isinstance(e, dict)]
        if isinstance(evaluations, list)
        else []
    )
    verification["evaluations"] = evaluations
    for case in test_cases.get("test_cases", []):
        if "type_5_contract" not in case:
            continue
        records = [
            e
            for e in evaluations
            if e.get("test_case_id", e.get("id")) == case.get("id")
        ]
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
    summary = verification.setdefault("verification_metadata", {}).setdefault(
        "summary", {}
    )
    summary["rejected"] = max(rejected, summary.get("rejected", 0))


def extract_base_name(profile_path: Path) -> str:
    return profile_path.stem.replace("_verification", "")


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
) -> int:
    app_logs = json.loads(app_logs_path.read_text(encoding="utf-8"))
    social_circle_file = json.loads(social_circle_path.read_text(encoding="utf-8"))
    corrected_social_circle = social_circle_file["corrected_social_circle"]

    client = make_client(provider) if backend in API_BACKENDS else None
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = extract_base_name(profile_path)
    test_cases_out = output_dir / f"{base_name}_test_cases.json"
    verification_out = output_dir / f"{base_name}_test_cases_verification.json"

    for attempt in range(1, max_iterations + 1):
        print(
            f"[attempt {attempt}/{max_iterations}] generating test cases for {base_name}"
        )
        test_cases = run_generation(
            client,
            model,
            app_logs,
            corrected_social_circle,
            gpt_reasoning,
            provider=provider,
            backend=backend,
        )
        test_cases_out.write_text(
            json.dumps(test_cases, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        contract_problems = validate_type5_contracts(test_cases, app_logs)
        if contract_problems:
            # Reject malformed answer keys before spending a verification call.
            # Keep a normal rejection report so later stages cannot consume them.
            verification = {
                "verification_metadata": {
                    "summary": {"rejected": len(contract_problems)}
                },
                "evaluations": [
                    {
                        "test_case_id": cid,
                        "overall_verdict": "REJECTED",
                        "revision_note": "; ".join(errors),
                    }
                    for cid, errors in contract_problems.items()
                ],
                "corrected_test_cases": {
                    "coverage_deficit": ["Invalid Type 5 contracts"]
                },
                "contract_validation_errors": contract_problems,
            }
            verification_out.write_text(
                json.dumps(verification, indent=2), encoding="utf-8"
            )
            print(
                f"[attempt {attempt}/{max_iterations}] invalid Type 5 contracts: {contract_problems}"
            )
            continue

        print(
            f"[attempt {attempt}/{max_iterations}] verifying test cases for {base_name}"
        )
        verification = run_verification(
            client,
            verifier_model,
            test_cases,
            app_logs,
            gpt_reasoning,
            provider=provider,
            backend=backend,
        )
        enforce_contract_verification(test_cases, verification)
        verification_out.write_text(
            json.dumps(verification, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        if verification_passed(verification):
            print(f"[attempt {attempt}/{max_iterations}] passed")
            return 0
        summary = verification.get("verification_metadata", {}).get("summary", {})
        deficit = verification.get("corrected_test_cases", {}).get(
            "coverage_deficit", []
        )
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
        help="Path to the corrected social circle file "
        "({persona}_social_circle_verification.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=STEP_DIR / "data_samples",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--verifier-model", default=None,
        help="Independent model for the reverse-inferability gate",
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument(
        "--gpt-reasoning",
        default="high",
        help="OpenAI model (openai-api, codex) reasoning effort."
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
        )
    )


if __name__ == "__main__":
    main()
