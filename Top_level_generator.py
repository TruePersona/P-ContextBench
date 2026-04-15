"""Top-level orchestrator for the PersonaBench pipeline.

Runs Step 1 (seed lookup) -> Step 2 (interview + verification) -> Step 3
(social circle + verification) for one or more personas. Each step is executed
in its own subprocess using the step's local generator.py, so the pipeline is
composable and each step remains independently runnable.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
STEP1_DIR = REPO_ROOT / "PersonaEngine" / "step1_seed"
STEP2_DIR = REPO_ROOT / "PersonaEngine" / "step2_interview"
STEP3_DIR = REPO_ROOT / "PersonaEngine" / "step3_social_circle"


def run_subprocess(cmd: list[str]) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode


def run_step1(uuid: str) -> int:
    return run_subprocess(
        [
            sys.executable,
            str(STEP1_DIR / "generator.py"),
            "--uuid",
            uuid,
            "--output",
            str(STEP1_DIR / "data_samples" / "output"),
        ]
    )


def run_step2(seed_path: Path, model: str, max_iterations: int) -> int:
    return run_subprocess(
        [
            sys.executable,
            str(STEP2_DIR / "generator.py"),
            "--seed",
            str(seed_path),
            "--output",
            str(STEP2_DIR / "data_samples" / "output"),
            "--model",
            model,
            "--max-iterations",
            str(max_iterations),
        ]
    )


def run_step3(
    profile_path: Path, transcript_path: Path, model: str, max_iterations: int
) -> int:
    return run_subprocess(
        [
            sys.executable,
            str(STEP3_DIR / "generator.py"),
            "--profile",
            str(profile_path),
            "--transcript",
            str(transcript_path),
            "--output",
            str(STEP3_DIR / "data_samples" / "output"),
            "--model",
            model,
            "--max-iterations",
            str(max_iterations),
        ]
    )


def run_pipeline(
    seed_path: Path, model: str, max_iterations: int, start: int, stop: int
) -> int:
    base = seed_path.stem.replace("_seed", "")
    step2_out = STEP2_DIR / "data_samples" / "output"
    interview_path = step2_out / f"{base}_interview.json"
    verification_path = step2_out / f"{base}_verification.json"

    if start <= 2 <= stop:
        if (rc := run_step2(seed_path, model, max_iterations)) != 0:
            return rc
    if start <= 3 <= stop:
        if (rc := run_step3(verification_path, interview_path, model, max_iterations)) != 0:
            return rc
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        type=Path,
        required=True,
        help="Path to the seed JSON produced by Step 1 (or supplied directly)",
    )
    parser.add_argument("--model", default="claude-opus-4-6")
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument(
        "--start", type=int, default=2, choices=[1, 2, 3], help="First step to run"
    )
    parser.add_argument(
        "--stop", type=int, default=3, choices=[1, 2, 3], help="Last step to run"
    )
    args = parser.parse_args()

    if args.start > args.stop:
        print("--start must be <= --stop", file=sys.stderr)
        sys.exit(2)

    sys.exit(run_pipeline(args.seed, args.model, args.max_iterations, args.start, args.stop))


if __name__ == "__main__":
    main()
