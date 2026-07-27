import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from llm import (
    API_BACKENDS,
    SUPPORTED_BACKENDS,
    SUPPORTED_PROVIDERS,
    check_api_key,
    default_model_for_backend,
    provider_for_backend,
)
from utils import (
    extract_name,
    base
)
from step1_seed.generator import (
    fetch_record,
    emit_seed,
)

REPO_ROOT = Path(__file__).parent
STEP1_DIR = REPO_ROOT / "step1_seed"
STEP2_DIR = REPO_ROOT / "step2_interview"
STEP3_DIR = REPO_ROOT / "step3_social_circle"
STEP4_DIR = REPO_ROOT / "step4_app_log_synthesizer"
STEP5_DIR = REPO_ROOT / "step5_testcases_synthesis"
STEP6_DIR = REPO_ROOT / "step6_benchmark_runner"


class StageError(RuntimeError):
    """A pipeline stage exited with a nonzero return code."""


def run_stage(step: str, cmd: list[str]) -> None:
    """Run one stage subprocess and stop the pipeline if it fails.

    Later stages read the artifacts earlier stages write, so continuing
    past a failed stage would consume missing or stale files and produce
    outputs that look valid but are not.
    """
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise StageError(f"{step} exited with code {result.returncode}")


def run_pipeline(
    seed_path: Path,
    backend: str,
    provider: str,
    model: str,
    verifier_model: str,
    judge_model: str,
    answer_model: str,
    uuid: str | None = None,
    start: int = 1,
    stop: int = 6,
    log_start: str = "2026-03-01",
    log_end: str = "2026-03-31",
    per_cluster_max_attempts: int = 3,
    gpt_reasoning: str = "high",
    gpt_eval_reasoning: str = "low",
    max_facts: int = 100,
    resume: bool = False,
    retry_failed: bool = False,
    filler_ratio: float = 2.5,
    gate_policy: str = "strict",
    target_context_tokens: int | None = None,
    verified_decoys_path: Path | None = None,
    decoy_count: int = 0,
    decoy_pool_size: int = 40,
    passk_runs: int = 1,
    passk_output: Path | None = None,
    passk_allow_missing: bool = False,
    backend_pass2: str | None = None,
    provider_pass2: str | None = None,
    skip_pass1: bool = False,
    skip_pass2: bool = False,
) -> None:
    

    # Step 1: Seed

    if start <= 1 <= stop and uuid:
        record = fetch_record(uuid)
        seed_path = emit_seed(record, STEP1_DIR / "data_samples")
        start = 2
        print(f"Wrote seed: {seed_path}")

    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    name = extract_name(seed)
    n = base(name)

    print(f"=== Pipeline for {name} (steps {start}-{stop}) ===")


    # Step 2: Interview

    if start <= 2 <= stop:
        cmd = [
            sys.executable,
            str(STEP2_DIR / "generator.py"),
            "--seed", str(seed_path),
            "--model", model,
            "--verifier-model", verifier_model,
            "--backend", backend,
            "--provider", provider,
            "--gpt-reasoning", gpt_reasoning
        ]

        run_stage("step2", cmd)

    verification_path = STEP2_DIR / "data_samples" / f"{n}_verification.json"
    interview_path = STEP2_DIR / "data_samples" / f"{n}_interview.json"


    # Step 3: Social Circle

    if start <= 3 <= stop:
        cmd = [
            sys.executable,
            str(STEP3_DIR / "generator.py"),
            "--profile", str(verification_path),
            "--transcript", str(interview_path),
            "--model", model,
            "--verifier-model", verifier_model,
            "--backend", backend,
            "--provider", provider,
            "--gpt-reasoning", gpt_reasoning
        ]

        run_stage("step3", cmd)

    social_circle_path = STEP3_DIR / "data_samples" / f"{n}_social_circle_verification.json"


    # Step 4: App Logs
    
    if start <= 4 <= stop:
        cmd = [
            sys.executable,
            str(STEP4_DIR / "generator.py"),
            "--profile", str(verification_path),
            "--social-circle", str(social_circle_path),
            "--model", model,
            "--verifier-model", verifier_model,
            "--backend", backend,
            "--provider", provider,
            "--gpt-reasoning", gpt_reasoning,
            "--log-start", log_start,
            "--log-end", log_end,
            "--per-cluster-max-attempts", str(per_cluster_max_attempts),
            "--max-facts", str(max_facts),
            "--filler-ratio", str(filler_ratio),
            "--decoy-count", str(decoy_count),
            "--decoy-pool-size", str(decoy_pool_size),
            "--gate-policy", gate_policy
        ]

        if target_context_tokens:
            cmd += ["--target-context-tokens", str(target_context_tokens)]
        if verified_decoys_path:
            cmd += ["--verified-decoys", str(verified_decoys_path)]
        if resume:
            cmd += ["--resume"]
        if retry_failed:
            cmd += ["--retry-failed"]

        run_stage("step4", cmd)

    app_logs_path = STEP4_DIR / "data_samples" / f"{n}_app_logs.json"


    # Step 5: Test Cases

    if start <= 5 <= stop:
        cmd = [
            sys.executable,
            str(STEP5_DIR / "generator.py"),
            "--profile", str(verification_path),
            "--app-logs", str(app_logs_path),
            "--social-circle", str(social_circle_path),
            "--model", model,
            "--verifier-model", verifier_model,
            "--backend", backend,
            "--provider", provider,
            "--gpt-reasoning", gpt_reasoning
        ]

        run_stage("step5", cmd)

    test_cases_path = STEP5_DIR / "data_samples" / f"{n}_test_cases.json"


    # Step 6: Benchmark

    if start <= 6 <= stop:
        cmd = [
            sys.executable,
            str(STEP6_DIR / "generator.py"),
            "--app-logs", str(app_logs_path),
            "--test-cases", str(test_cases_path),
            "--model-pass1", answer_model,
            "--model-pass2", judge_model,
            "--backend", backend,
            "--provider", provider,
            "--reasoning-pass1", gpt_eval_reasoning,
            "--reasoning-pass2", gpt_reasoning
        ]
    
        if backend_pass2:
            cmd += ["--backend-pass2", backend_pass2]
        if provider_pass2:
            cmd += ["--provider-pass2", provider_pass2]
        if skip_pass1:
            cmd += ["--skip-pass1"]
        if skip_pass2:
            cmd += ["--skip-pass2"]
        if passk_runs > 1:
            cmd += ["--passk-runs", str(passk_runs)]
        if passk_output:
            cmd += ["--passk-output", str(passk_output)]
        if passk_allow_missing:
            cmd += ["--passk-allow-missing"]

        run_stage("step6", cmd)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--seed", type=Path, help="Path to a seed JSON")
    parser.add_argument(
        "--uuid", type=str, default=None,
        help="Persona UUID in Nemotron-Personas-USA. "
        "Required for Step 1 (no seed/persona provided)."
    )
    parser.add_argument(
        "--persona", type=str, default=None,
        help="Persona name shorthand (e.g. julio_simmons); resolves to "
        "step1_seed/data_samples/<persona>_seed.json. Mutually "
        "exclusive with --seed and --all.",
    )
    parser.add_argument(
        "--all", action="store_true", help="Run against every seed JSON in step1_seed/"
    )
    parser.add_argument("--start", type=int, default=1, choices=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--stop", type=int, default=6, choices=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--log-start", default="2026-03-01")
    parser.add_argument("--log-end", default="2026-03-31")
    parser.add_argument(
        "--per-cluster-max-attempts",
        type=int,
        default=3,
        help="Maximum Step 4 generation attempts per hidden-fact cluster.",
    )
    parser.add_argument(
        "--per-fact-max-attempts",
        type=int,
        dest="per_cluster_max_attempts",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--max-facts",
        type=int,
        default=100,
        help="Maximum hidden facts selected for Step 4.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing Step 4 trace and verified fragments when compatible.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="With --resume, retry only failed Step 4 clusters.",
    )
    parser.add_argument(
        "--filler-ratio",
        type=float,
        default=2.5,
        help="Step 4 filler-to-meaningful token ratio.",
    )
    parser.add_argument(
        "--gate-policy",
        choices=("strict", "lenient"),
        default="strict",
        help="Step 4 cluster acceptance policy. strict enforces the "
        "documented predicate (RECOVERED, no leak flags); lenient "
        "reproduces the rule the committed data samples were built with.",
    )
    parser.add_argument(
        "--target-context-tokens",
        type=int,
        default=None,
        help="Optional total context token target for Step 4.",
    )
    parser.add_argument(
        "--verified-decoys",
        type=Path,
        default=None,
        help="Optional verified decoy pool JSON for Step 4.",
    )
    parser.add_argument(
        "--decoy-count",
        type=int,
        default=0,
        help="Number of verified messenger decoys to place in Step 4.",
    )
    parser.add_argument(
        "--decoy-pool-size",
        type=int,
        default=40,
        help="Number of Step 4 decoy candidates to generate when no pool is supplied.",
    )
    parser.add_argument(
        "--backend",
        default="anthropic-api",
        choices=SUPPORTED_BACKENDS,
        help="Model backend: claude/codex for subscription CLI, or "
        "anthropic-api/openai-api for metered API calls. `api` uses --provider.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=SUPPORTED_PROVIDERS,
        help="API provider used when --backend api is selected, or as a "
        "backward-compatible shortcut for --backend <provider>-api.",
    )
    parser.add_argument(
        "--model", default=None,
        help="Generator model passed to every backend CLI call. MUST be an "
        "exact pinned string, never an alias. Defaults to claude-opus-4-7 for "
        "the Claude backend and gpt-5.5 for the Codex backend.",
    )
    parser.add_argument(
        "--verifier-model", default=None,
        help="Verifier model for Step 4's reverse-inferability gate. MUST be "
        "an exact pinned string. Should differ from --model when possible so "
        "the verifier is independent.",
    )
    parser.add_argument(
        "--answer-model", default=None,
        help="Answer model for Step 6 Pass 1 answering. MUST be "
        "an exact pinned string.",
    )
    parser.add_argument(
        "--judge-model", default=None,
        help="Judge model for Step 6 Pass 2 scoring. MUST be an exact pinned "
        "string. Should differ from --answer-model when possible to keep the scorer "
        "independent of the answerer.",
    )
    parser.add_argument(
        "--passk-runs",
        type=int,
        default=1,
        help="Run Step 6 this many times, then write a Pass^k reliability summary.",
    )
    parser.add_argument(
        "--passk-output",
        type=Path,
        default=None,
        help="Optional output path for the Step 6 Pass^k summary JSON.",
    )
    parser.add_argument(
        "--passk-allow-missing",
        action="store_true",
        help="Score missing cases as 0 when Pass^k run outputs have different ids.",
    )
    parser.add_argument(
        "--gpt-reasoning",
        default="high",
        help="OpenAI model (openai-api, codex) generation/verification (Steps 2-5, Step 6 Pass 2) reasoning effort."
    )
    parser.add_argument(
        "--gpt-eval-reasoning",
        default="low",
        help="OpenAI model (openai-api, codex) response (Step 6 Pass 1) reasoning effort."
    )
    parser.add_argument(
        "--skip-pass1",
        action="store_true",
        help="Skip Step 6 Pass 1 and reuse existing pass1_answers.json. Useful when "
        "only the scoring prompt or judge model changed.",
    )
    parser.add_argument(
        "--skip-pass2",
        action="store_true",
        help="Skip Step 6 Pass 2. Useful when preparing answers "
        "for scoring with different backends.",
    )
    parser.add_argument(
        "--backend-pass2",
        default=None,
        choices=SUPPORTED_BACKENDS,
        help="(Step 6) Optional scoring backend: anthropic-api uses ANTHROPIC_API_KEY; "
        "openai-api uses OPENAI_API_KEY; claude and codex use logged-in CLIs. "
        "Defaults to match --backend.",
    )
    parser.add_argument(
        "--provider-pass2",
        default=None,
        choices=("anthropic", "openai", "openrouter"),
        help="Optional API provider override for compatibility (Step 6 Pass 2). "
        "openrouter uses OPENROUTER_API_KEY and is compatible with openai-api",
    )
    args = parser.parse_args()

    backend_pass2 = args.backend_pass2 or args.backend

    provider = provider_for_backend(args.backend, args.provider) if args.backend in API_BACKENDS else (args.provider or "anthropic")
    provider_pass2 = provider_for_backend(backend_pass2, args.provider_pass2) if backend_pass2 in API_BACKENDS else (args.provider_pass2 or provider)

    if args.model is None:
        args.model = default_model_for_backend(args.backend, "generator")
    if args.verifier_model is None:
        args.verifier_model = default_model_for_backend(args.backend, "verifier")
    if args.answer_model is None:
        args.answer_model = default_model_for_backend(args.backend, "answer")
    if args.judge_model is None:
        args.judge_model = default_model_for_backend(args.backend, "judge")

    for flag, val in [
        ("--model", args.model),
        ("--verifier-model", args.verifier_model),
        ("--answer-model", args.answer_model),
        ("--judge-model", args.judge_model),
    ]:
        if val in {"opus", "sonnet", "haiku"}:
            parser.error(
                f"{flag} {val!r} is an alias. Use the exact pinned model "
                f"string (e.g. claude-opus-4-7). Aliases drift across CLI "
                f"versions and break reproducibility."
            )

    if args.start > args.stop:
        parser.error("--start must be <= --stop")
    if args.passk_runs < 1:
        parser.error("--passk-runs must be at least 1")

    if args.backend in API_BACKENDS and not check_api_key(provider):
        parser.error(f"{provider.upper()}_API_KEY is not set")

    if (args.start == 1) == (args.uuid is None):
        parser.error("--start 1 and --uuid require each other.")

    if args.seed and args.uuid:
        parser.error("--seed is mutually exclusive with --uuid")

    # Resolve --persona to --seed
    if args.persona:
        if args.seed or args.uuid or args.all:
            parser.error("--persona is mutually exclusive with --seed, --uuid and --all")
        args.seed = STEP1_DIR / "data_samples" / f"{args.persona}_seed.json"
        if not args.seed.exists():
            parser.error(f"Persona seed not found: {args.seed}")

    if args.all and args.start > 1:
        seed_dir = STEP1_DIR / "data_samples"
        failed: list[str] = []
        for seed_file in sorted(seed_dir.glob("*_seed.json")):
            try:
                run_pipeline(
                    seed_file,
                    args.backend,
                    provider,
                    args.model,
                    args.verifier_model,
                    args.judge_model,
                    args.answer_model,
                    args.uuid,
                    args.start,
                    args.stop,
                    args.log_start,
                    args.log_end,
                    args.per_cluster_max_attempts,
                    gpt_reasoning=args.gpt_reasoning,
                    gpt_eval_reasoning=args.gpt_eval_reasoning,
                    max_facts=args.max_facts,
                    resume=args.resume,
                    retry_failed=args.retry_failed,
                    filler_ratio=args.filler_ratio,
                    gate_policy=args.gate_policy,
                    target_context_tokens=args.target_context_tokens,
                    verified_decoys_path=args.verified_decoys,
                    decoy_count=args.decoy_count,
                    decoy_pool_size=args.decoy_pool_size,
                    passk_runs=args.passk_runs,
                    passk_output=args.passk_output,
                    passk_allow_missing=args.passk_allow_missing,
                    backend_pass2=backend_pass2,
                    provider_pass2=provider_pass2,
                    skip_pass1=args.skip_pass1,
                    skip_pass2=args.skip_pass2,
                )
            except StageError as exc:
                # Move on to the next persona but keep the failure visible;
                # a partial batch must not exit 0.
                print(f"[{seed_file.stem}] {exc}", file=sys.stderr)
                failed.append(seed_file.stem)
        if failed:
            print(
                f"{len(failed)} persona(s) failed: {', '.join(failed)}",
                file=sys.stderr,
            )
            sys.exit(1)
    elif args.seed or args.uuid:
        try:
            run_pipeline(
                args.seed,
                args.backend,
                provider,
                args.model,
                args.verifier_model,
                args.judge_model,
                args.answer_model,
                args.uuid,
                args.start,
                args.stop,
                args.log_start,
                args.log_end,
                args.per_cluster_max_attempts,
                gpt_reasoning=args.gpt_reasoning,
                gpt_eval_reasoning=args.gpt_eval_reasoning,
                max_facts=args.max_facts,
                resume=args.resume,
                retry_failed=args.retry_failed,
                filler_ratio=args.filler_ratio,
                gate_policy=args.gate_policy,
                target_context_tokens=args.target_context_tokens,
                verified_decoys_path=args.verified_decoys,
                decoy_count=args.decoy_count,
                decoy_pool_size=args.decoy_pool_size,
                passk_runs=args.passk_runs,
                passk_output=args.passk_output,
                passk_allow_missing=args.passk_allow_missing,
                backend_pass2=backend_pass2,
                provider_pass2=provider_pass2,
                skip_pass1=args.skip_pass1,
                skip_pass2=args.skip_pass2,
            )
        except StageError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
    else:
        parser.error("Provide --persona <name>, --seed <path>, --uuid <uuid> or --all")


if __name__ == "__main__":
    main()