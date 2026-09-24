"""Judge stress tests on proposed labels; these are not human calibration gold."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from type5_protocol.backend import infer
from type5_protocol.experiment import JUDGE_PROMPT, ensure_reviewed
from type5_protocol.protocol import (
    COMMON_CHECKS,
    VERSION,
    fingerprint,
    public_episode,
    score,
    validate_judgment,
)
from type5_protocol.quotes import judgment_quote_matches


def evaluate(example, episode, args):
    ensure_reviewed(episode, args)
    work = Path(args.workdir)
    path = work / "calibration" / args.run / (example["id"] + ".json")
    payload = {
        "public_episode": public_episode(episode),
        "contract": episode["contract"],
        "common_checks": COMMON_CHECKS,
        "answer": example["answer"],
    }
    binding = fingerprint(
        {
            "protocol": VERSION,
            "example": example,
            "episode": episode,
            "prompt": JUDGE_PROMPT,
            "common_checks": COMMON_CHECKS,
            "model": args.model,
            "backend": args.backend,
        }
    )
    if path.exists():
        result = json.loads(path.read_text())
        if result.get("binding") != binding:
            raise ValueError("calibration run changed; use a new run ID")
        return result
    result = {
        "scoring_protocol": VERSION,
        "id": example["id"],
        "binding": binding,
        "episode_id": episode["id"],
        "expected_success": example["expected_success"],
        "answer": example["answer"],
        "failure_kind": example["failure_kind"],
        "reference_status": "proposal_not_human_gold",
    }
    prompt = JUDGE_PROMPT + json.dumps(payload, ensure_ascii=False)
    try:
        call = infer(
            prompt,
            model=args.model,
            backend=args.backend,
            output_dir=work / "calibration_calls",
            effort="high",
        )
        for attempt in range(3):
            try:
                validate_judgment(episode, example["answer"], call["response"])
                break
            except (ValueError, KeyError, TypeError) as exc:
                if attempt == 2:
                    raise
                call = infer(
                    prompt
                    + "\nCorrect only the schema or quotation error: "
                    + str(exc)
                    + "\nPrevious output:\n"
                    + call["response_text"],
                    model=args.model,
                    backend=args.backend,
                    output_dir=work / "calibration_calls",
                    effort="high",
                )
        result.update(
            call=call["cache_key"],
            judgment=call["response"],
            quote_matches=judgment_quote_matches(example["answer"], call["response"]),
            score=score(episode, example["answer"], call["response"]),
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        result["error"] = str(exc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", default="_orchestration/type5_protocol/curated_v2")
    p.add_argument("--run", required=True)
    p.add_argument("--model", default="gpt-5.5")
    p.add_argument("--backend", choices=("codex", "claude"), default="codex")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument(
        "--swap-run",
        help="Stress-test frozen base/contrast answers under the other context",
    )
    p.add_argument(
        "--swap-labels",
        type=Path,
        help="Explicit predictions bound to each frozen source answer; swapping alone does not imply failure",
    )
    args = p.parse_args()
    args.allow_unreviewed = False
    data = json.loads((Path(args.workdir) / "pilot.json").read_text())
    episodes = {e["id"]: e for e in data["episodes"] if e["split"] == "development"}
    examples = [x for x in data["calibration"] if x["split"] == "development"]
    if args.swap_run:
        if args.swap_labels is None:
            raise ValueError(
                "swap predictions require explicit answer-bound labels; valid approaches can overlap across contexts"
            )
        label_rows = json.loads(args.swap_labels.read_text())
        labels = {r["episode_id"]: r for r in label_rows}
        if len(labels) != len(label_rows) or set(labels) != set(episodes):
            raise ValueError("swap labels must cover the intended targets exactly once")
        examples = []
        for target in episodes.values():
            if target["variant"] == "irrelevant_control":
                source_variant = "base"
            else:
                source_variant = "contrast" if target["variant"] == "base" else "base"
            source = next(
                e
                for e in episodes.values()
                if e["family_id"] == target["family_id"]
                and e["variant"] == source_variant
            )
            path = (
                Path(args.workdir)
                / "runs"
                / args.swap_run
                / "answers"
                / (source["id"] + ".json")
            )
            answer = json.loads(path.read_text())
            if (
                answer.get("episode_sha256") != fingerprint(source)
                or answer.get("public_sha256") != fingerprint(public_episode(source))
                or answer.get("condition") != "full"
                or answer.get("error")
            ):
                raise ValueError("swap answer is missing or has stale provenance")
            label = labels[target["id"]]
            expected = label.get("expected_success")
            if (
                type(expected) is not bool
                or not label.get("reason")
                or label.get("source_answer_sha256") != fingerprint(answer)
            ):
                raise ValueError(
                    "swap prediction is malformed or belongs to a different answer"
                )
            examples.append(
                {
                    "id": target["id"] + "-swapped",
                    "episode_id": target["id"],
                    "answer": answer["answer"],
                    "expected_success": expected,
                    "failure_kind": "none" if expected else "missed_context",
                    "source_answer_sha256": fingerprint(answer),
                    "reference_status": "counterfactual_prediction_requires_adjudication",
                    "prediction_reason": label["reason"],
                }
            )
    if not examples or len({x["id"] for x in examples}) != len(examples):
        raise ValueError("calibration examples must be nonempty and unique")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(evaluate, x, episodes[x["episode_id"]], args): x
            for x in examples
        }
        for future in as_completed(futures):
            example = futures[future]
            try:
                result = future.result()
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                result = {
                    "id": example["id"],
                    "expected_success": example["expected_success"],
                    "error": str(exc),
                }
            results.append(result)
            print(
                json.dumps(
                    {
                        "id": result["id"],
                        "expected": result["expected_success"],
                        "observed": result.get("score", {}).get("case_success"),
                        "error": result.get("error"),
                    }
                ),
                flush=True,
            )
    resolved = [
        r for r in results if r.get("score", {}).get("case_success") is not None
    ]
    summary = {
        "reference_status": "proposed_labels_not_human_gold",
        "intended": len(examples),
        "resolved": len(resolved),
        "unresolved": len(examples) - len(resolved),
        "agreement": sum(
            r["score"]["case_success"] == r["expected_success"] for r in resolved
        ),
        "false_acceptances_against_proposal": sum(
            r["score"]["case_success"] and not r["expected_success"] for r in resolved
        ),
        "false_rejections_against_proposal": sum(
            not r["score"]["case_success"] and r["expected_success"] for r in resolved
        ),
        "results": sorted(results, key=lambda r: r["id"]),
    }
    directory = Path(args.workdir) / "calibration" / args.run
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    if len(resolved) != len(examples):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
