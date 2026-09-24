"""Registered context-policy comparisons under the unchanged T5 evaluator.

Only built-in, reviewed selectors run here. Arbitrary code search needs an OS
sandbox and a separate budget broker; this runner does not claim to provide one.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import platform
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from type5_protocol.backend import SYSTEM, infer
from type5_protocol.context_policy import (
    POLICIES,
    logs_cost,
    render_context,
    select_context,
)
from type5_protocol.experiment import (
    ANSWER_PROMPT,
    JUDGE_PROMPT,
    ensure_reviewed,
    freeze_payload,
)
from type5_protocol.protocol import (
    COMMON_CHECKS,
    VERSION,
    fingerprint,
    public_episode,
    score,
    summarize,
    validate_families,
    validate_judgment,
)
from type5_protocol.quotes import judgment_quote_matches
from utils import extract_json

STUDY_VERSION = "t5-context-policy-1"
ROOT = Path(__file__).resolve().parents[1]
ERRORS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    StopIteration,
)
HYPOTHESES = {
    "full": {"parent": None, "hypothesis": "Canonical complete-history baseline."},
    "lexical": {
        "parent": "full",
        "hypothesis": "Public lexical retrieval may reduce distraction and input cost without losing necessary evidence.",
    },
    "linked": {
        "parent": "lexical",
        "hypothesis": "Related recent records may recover updates omitted by direct query matching while retaining earlier instructions.",
    },
}
MODELS = {
    "haiku": {"model": "claude-haiku-4-5-20251001", "backend": "claude"},
    "sonnet": {"model": "claude-sonnet-4-6", "backend": "claude"},
}


def read(path):
    return json.loads(Path(path).read_text())


def frozen_write(path, value):
    """Write once; callers serialize concurrent writes using the study lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read(path) != value:
            raise ValueError(f"immutable artifact changed: {path}")
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    temporary.replace(path)


def code_snapshot():
    core = freeze_payload({})["code_sha256"]
    paths = ["type5_protocol/" + name for name in core]
    paths += [
        "type5_protocol/context_policy.py",
        "type5_protocol/policy_study.py",
        "utils.py",
    ]
    return {name: (ROOT / name).read_text() for name in paths}


def review_inventory(source, data):
    groups = validate_families(data["episodes"])
    if any(e["split"] != "development" for e in data["episodes"]):
        raise ValueError("policy search accepts development episodes only")
    inventory, admitted = [], []
    args = Namespace(workdir=source, allow_unreviewed=False)
    for fid, group in groups.items():
        required = [source / "family_reviews" / (fid + ".json")] + [
            source / "reviews" / (e["id"] + ".json")
            for e in group
            if e["variant"] != "irrelevant_control"
        ]
        if any(not p.exists() for p in required):
            raise ValueError(f"complete the registered review inventory first: {fid}")
        reason = None
        try:
            for episode in group:
                ensure_reviewed(episode, args)
        except ERRORS as exc:
            reason = str(exc)
        inventory.append(
            {
                "family_id": fid,
                "admitted": reason is None,
                "reason": reason,
                "reviews": [read(p) for p in required],
            }
        )
        if reason is None:
            admitted.extend(group)
    if not admitted:
        raise ValueError("no fully reviewed families")
    return inventory, admitted


def register(
    source, work, *, budget=12000, models=("haiku", "sonnet"), replicates=("r1",)
):
    source, work = Path(source), Path(work)
    if type(budget) is not int or budget < 2:
        raise ValueError("invalid retrieval budget")
    if (
        not models
        or len(set(models)) != len(models)
        or not set(models) <= MODELS.keys()
    ):
        raise ValueError("choose distinct supported model configurations")
    if (
        not replicates
        or len(set(replicates)) != len(replicates)
        or any(not r.isalnum() for r in replicates)
    ):
        raise ValueError("replicate IDs must be distinct nonempty alphanumeric strings")
    data = read(source / "pilot.json")
    inventory, episodes = review_inventory(source, data)
    review_files = {
        str(path.relative_to(source)): read(path)
        for directory in ("reviews", "family_reviews", "review_calls")
        for path in sorted((source / directory).glob("*.json"))
    }
    if (source / "construction_history.json").exists():
        review_files["construction_history.json"] = read(
            source / "construction_history.json"
        )
    code = code_snapshot()
    plans = [
        {
            "run": f"{model}-{policy}-{replicate}",
            "policy": policy,
            "budget_chars": None if policy == "full" else budget,
            "answerer": MODELS[model],
            "replicate": replicate,
        }
        for model in models
        for replicate in replicates
        for policy in POLICIES
    ]
    registration = {
        "study_version": STUDY_VERSION,
        "purpose": "Engineering development comparison; all scenarios previously exposed; no human validity or generalization claim.",
        "validation_status": "candidate_not_human_validated",
        "source_dataset_sha256": fingerprint(data),
        "dataset_sha256": fingerprint({"episodes": episodes}),
        "admission_sha256": fingerprint(inventory),
        "review_artifacts_sha256": {
            name: fingerprint(value) for name, value in review_files.items()
        },
        "evaluator": freeze_payload({"episodes": episodes}),
        "code_sha256": {name: fingerprint(text) for name, text in code.items()},
        "dependencies": {
            "python": platform.python_version(),
            "retrieval": "standard library only",
            "transport": "installed CLI; exact decoding controls unavailable",
        },
        "policies": HYPOTHESES,
        "runs": plans,
        "judge": {"model": "gpt-5.5", "backend": "codex"},
        "answer_effort": "low",
        "judge_effort": "high",
        "call_budget": {
            "answer_max": len(plans) * len(episodes),
            "judge_max": 3 * len(plans) * len(episodes),
            "judge_attempts_per_answer": 3,
        },
        "selection_rule": "Keep full history as canonical. No policy promotion from this small, previously exposed, model-judged sample. Report all paired changes and costs; any gain is exploratory until fresh persona/scenario testing and human calibration.",
        "cache_rule": "Identical public prompts within a replicate share calls. Shared calls are not independent draws. Replicate IDs change both answer and judge cache configurations.",
        "scoring_rule": "Every policy is judged against the original complete public episode and unchanged contract. Omitted evidence never relaxes the rubric. Errors remain in the intended denominator.",
        "candidate_execution": "Trusted built-in policies only; no arbitrary candidate execution or sandbox claim.",
    }
    work.mkdir(parents=True, exist_ok=True)
    with (work / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Registration is written last; an incomplete setup cannot run inference.
        frozen_write(work / "source_dataset.json", data)
        frozen_write(work / "pilot.json", {"episodes": episodes})
        frozen_write(work / "admission.json", inventory)
        frozen_write(work / "source_code.json", code)
        for name, value in review_files.items():
            frozen_write(work / "case_review" / name, value)
        frozen_write(work / "registration.json", registration)
    return registration


def load_study(work):
    work = Path(work)
    registration = read(work / "registration.json")
    data = read(work / "pilot.json")
    validate_families(data["episodes"])
    expected = {name: fingerprint(text) for name, text in code_snapshot().items()}
    if (
        registration.get("study_version") != STUDY_VERSION
        or registration.get("code_sha256") != expected
    ):
        raise ValueError(
            "registered code changed; preserve the frozen study and use a new revision"
        )
    if registration["dependencies"]["python"] != platform.python_version():
        raise ValueError("registered Python runtime changed")
    if registration["dataset_sha256"] != fingerprint(data) or registration[
        "evaluator"
    ] != freeze_payload(data):
        raise ValueError("registered dataset or evaluator changed")
    if registration["source_dataset_sha256"] != fingerprint(
        read(work / "source_dataset.json")
    ):
        raise ValueError("source dataset changed")
    if registration["admission_sha256"] != fingerprint(read(work / "admission.json")):
        raise ValueError("admission inventory changed")
    review_hashes = {
        str(path.relative_to(work / "case_review")): fingerprint(read(path))
        for path in sorted((work / "case_review").rglob("*.json"))
    }
    if registration["review_artifacts_sha256"] != review_hashes:
        raise ValueError("case review artifacts changed")
    if {
        name: fingerprint(text)
        for name, text in read(work / "source_code.json").items()
    } != expected:
        raise ValueError("frozen code snapshot changed")
    return registration, data["episodes"]


def selection(episode, plan):
    public = public_episode(episode, "full")
    started = time.perf_counter()
    spans = select_context(public, plan["budget_chars"], plan["policy"])
    visible = render_context(public, spans, plan["budget_chars"])
    selected = {span["log_id"] for span in spans}
    trace = {
        "spans": spans,
        "omitted_log_ids": [
            log["id"] for log in public["logs"] if log["id"] not in selected
        ],
        "full_public_sha256": fingerprint(public),
        "answer_public_sha256": fingerprint(visible),
        "full_log_characters": logs_cost(public["logs"]),
        "selected_log_characters": logs_cost(visible["logs"]),
        "retrieval_seconds": time.perf_counter() - started,
    }
    return public, visible, trace


def judge_input(public, episode, answer):
    return JUDGE_PROMPT + json.dumps(
        {
            "public_episode": public,
            "contract": episode["contract"],
            "common_checks": COMMON_CHECKS,
            "answer": answer,
        },
        ensure_ascii=False,
    )


def repair_prompt(original, call, error):
    return (
        original
        + "\nPrevious output failed validation: "
        + str(error)
        + "\nPrevious output:\n"
        + call["response_text"]
        + "\nReturn the complete corrected observations."
    )


def evaluate_one(work, registration, episode, plan):
    work = Path(work)
    path = work / "runs" / plan["run"] / (episode["id"] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            return read(path)
        row = {
            "episode_id": episode["id"],
            "episode_sha256": fingerprint(episode),
            "registration_sha256": fingerprint(registration),
            "run": plan["run"],
            "scoring_protocol": VERSION,
            "answer_call": None,
            "judge_calls": [],
        }
        try:
            public, visible, trace = selection(episode, plan)
            row["selection"] = trace
            call = infer(
                ANSWER_PROMPT + json.dumps(visible, ensure_ascii=False),
                **plan["answerer"],
                output_dir=work / "answer_calls",
                effort=registration["answer_effort"],
                response_format="text",
                replicate=plan["replicate"],
            )
            row["answer_call"] = call["cache_key"]
            answer = call["response"]["answer"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("missing user-facing answer")
            row["answer"] = answer
            original = judge_input(public, episode, answer)
            prompt = original
            for attempt in range(
                registration["call_budget"]["judge_attempts_per_answer"]
            ):
                call = infer(
                    prompt,
                    **registration["judge"],
                    output_dir=work / "judge_calls",
                    effort=registration["judge_effort"],
                    replicate=plan["replicate"],
                )
                row["judge_calls"].append(call["cache_key"])
                try:
                    validate_judgment(episode, answer, call["response"])
                    break
                except (ValueError, KeyError, TypeError) as exc:
                    if (
                        attempt
                        == registration["call_budget"]["judge_attempts_per_answer"] - 1
                    ):
                        raise
                    prompt = repair_prompt(original, call, exc)
            row.update(
                judgment=call["response"],
                quote_matches=judgment_quote_matches(answer, call["response"]),
                score=score(episode, answer, call["response"]),
            )
        except ERRORS as exc:
            row["error"] = str(exc)
        frozen_write(path, row)
        return row


def checked_call(work, kind, key, prompt, config, effort, replicate):
    call = read(Path(work) / kind / (key + ".json"))
    system = (
        SYSTEM
        if kind == "judge_calls"
        else SYSTEM.replace(
            "Return only the requested JSON.",
            "Return only the requested user-facing response as plain text.",
        )
    )
    configuration = {
        **config,
        "effort": effort,
        "system": system,
        "transport_version": "isolated-1",
    }
    if replicate != "first":
        configuration["replicate"] = replicate
    expected_key = fingerprint({"configuration": configuration, "prompt": prompt})
    if (
        key != expected_key
        or call.get("cache_key") != key
        or call.get("configuration") != configuration
        or call.get("prompt") != prompt
        or call.get("prompt_sha256") != fingerprint(prompt)
    ):
        raise ValueError("raw inference input/configuration binding changed")
    if call.get("status") not in ("ok", "invalid_json"):
        raise ValueError("raw inference did not complete")
    try:
        parsed = (
            {"answer": call["response_text"]}
            if kind == "answer_calls"
            else extract_json(call["response_text"])
        )
    except (ValueError, json.JSONDecodeError):
        parsed = None
    if parsed != call.get("response"):
        raise ValueError("raw response text differs from parsed response")
    return call


def audit_row(work, registration, episode, plan, row):
    if (
        row.get("episode_id") != episode["id"]
        or row.get("episode_sha256") != fingerprint(episode)
        or row.get("registration_sha256") != fingerprint(registration)
        or row.get("run") != plan["run"]
        or row.get("scoring_protocol") != VERSION
    ):
        raise ValueError("result provenance mismatch")
    public, visible, trace = selection(episode, plan)
    saved = row.get("selection", {})
    if {k: v for k, v in saved.items() if k != "retrieval_seconds"} != {
        k: v for k, v in trace.items() if k != "retrieval_seconds"
    }:
        raise ValueError("selected/omitted evidence binding changed")
    if row.get("answer_call"):
        call = checked_call(
            work,
            "answer_calls",
            row["answer_call"],
            ANSWER_PROMPT + json.dumps(visible, ensure_ascii=False),
            plan["answerer"],
            registration["answer_effort"],
            plan["replicate"],
        )
        if call["response"]["answer"] != row.get("answer"):
            raise ValueError("answer differs from raw call")
    elif not row.get("error"):
        raise ValueError("missing answer call")
    attempts = row.get("judge_calls", [])
    if len(attempts) > registration["call_budget"]["judge_attempts_per_answer"]:
        raise ValueError("judge repair budget exceeded")
    if attempts:
        original = judge_input(public, episode, row["answer"])
        prompt = original
        for i, key in enumerate(attempts):
            call = checked_call(
                work,
                "judge_calls",
                key,
                prompt,
                registration["judge"],
                registration["judge_effort"],
                plan["replicate"],
            )
            try:
                validate_judgment(episode, row["answer"], call["response"])
            except (ValueError, KeyError, TypeError) as exc:
                if i == len(attempts) - 1 and not row.get("error"):
                    raise
                prompt = repair_prompt(original, call, exc)
            else:
                if i != len(attempts) - 1:
                    raise ValueError(
                        "unnecessary judge reroll after a valid observation set"
                    )
        if not row.get("error") and (
            call["response"] != row.get("judgment")
            or row.get("score") != score(episode, row["answer"], call["response"])
            or row.get("quote_matches")
            != judgment_quote_matches(row["answer"], call["response"])
        ):
            raise ValueError("judgment/score/quote binding changed")
    elif not row.get("error"):
        raise ValueError("missing judge call")


def usage_summary(calls):
    def tokens_for(call):
        usage = call.get("usage", {})
        entries = usage if isinstance(usage, list) else usage.values()
        result = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for entry in entries:
            result["input"] += entry.get("input_tokens", entry.get("inputTokens", 0))
            result["output"] += entry.get("output_tokens", entry.get("outputTokens", 0))
            result["cache_read"] += entry.get(
                "cached_input_tokens", entry.get("cacheReadInputTokens", 0)
            )
            result["cache_write"] += entry.get("cacheCreationInputTokens", 0)
        return result

    tokens = [tokens_for(c) for c in calls]
    return {
        "distinct_calls": len(calls),
        "reported_usage": {
            k: sum(t[k] for t in tokens)
            for k in ("input", "output", "cache_read", "cache_write")
        },
        "usage_note": "Provider-native counters; cache-read tokens may be a subset of input. Do not sum categories across providers as billed tokens.",
        "reported_cost_usd": sum(c.get("reported_cost_usd") or 0 for c in calls),
        "calls_without_reported_cost": sum(
            c.get("reported_cost_usd") is None for c in calls
        ),
        "summed_call_seconds": sum(c.get("elapsed_seconds", 0) for c in calls),
    }


def compare(work):
    work = Path(work)
    registration, episodes = load_study(work)
    result = {
        "registration_sha256": fingerprint(registration),
        "validation_status": registration["validation_status"],
        "runs": {},
        "paired_changes": [],
        "integrity_issues": [],
    }
    rows = {}
    for plan in registration["runs"]:
        current = []
        directory = work / "runs" / plan["run"]
        expected_files = {e["id"] + ".json" for e in episodes}
        if {p.name for p in directory.glob("*.json")} - expected_files:
            raise ValueError("unexpected result outside registered population")
        for episode in episodes:
            path = directory / (episode["id"] + ".json")
            row = (
                read(path)
                if path.exists()
                else {"episode_id": episode["id"], "error": "missing result"}
            )
            try:
                audit_row(work, registration, episode, plan, row)
            except ERRORS as exc:
                result["integrity_issues"].append(
                    {"run": plan["run"], "episode_id": episode["id"], "issue": str(exc)}
                )
                row = {
                    "episode_id": episode["id"],
                    "error": "artifact integrity: " + str(exc),
                }
            current.append(row)
        rows[plan["run"]] = {r["episode_id"]: r for r in current}
        report = summarize(episodes, current)
        report["components"] = {
            name: summarize(
                [
                    e
                    for e in episodes
                    if e.get("study_component", "unspecified") == name
                ],
                [
                    r
                    for r in current
                    if r["episode_id"]
                    in {
                        e["id"]
                        for e in episodes
                        if e.get("study_component", "unspecified") == name
                    }
                ],
            )
            for name in sorted(
                {e.get("study_component", "unspecified") for e in episodes}
            )
        }
        answer_keys = {r["answer_call"] for r in current if r.get("answer_call")}
        judge_keys = {key for r in current for key in r.get("judge_calls", [])}
        report["answer_cost"] = usage_summary(
            [
                read(work / "answer_calls" / (key + ".json"))
                for key in sorted(answer_keys)
            ]
        )
        report["judge_cost"] = usage_summary(
            [read(work / "judge_calls" / (key + ".json")) for key in sorted(judge_keys)]
        )
        report["context"] = {
            "full_log_characters": sum(
                r.get("selection", {}).get("full_log_characters", 0) for r in current
            ),
            "selected_log_characters": sum(
                r.get("selection", {}).get("selected_log_characters", 0)
                for r in current
            ),
            "retrieval_seconds": sum(
                r.get("selection", {}).get("retrieval_seconds", 0) for r in current
            ),
        }
        result["runs"][plan["run"]] = report
    for plan in registration["runs"]:
        if plan["policy"] == "full":
            continue
        baseline = next(
            p
            for p in registration["runs"]
            if p["policy"] == "full"
            and p["answerer"] == plan["answerer"]
            and p["replicate"] == plan["replicate"]
        )
        for episode in episodes:
            a = rows[baseline["run"]][episode["id"]]
            b = rows[plan["run"]][episode["id"]]
            oa = {
                o["id"]: o["status"]
                for o in a.get("judgment", {}).get("observations", [])
            }
            ob = {
                o["id"]: o["status"]
                for o in b.get("judgment", {}).get("observations", [])
            }
            result["paired_changes"].append(
                {
                    "baseline": baseline["run"],
                    "candidate": plan["run"],
                    "episode_id": episode["id"],
                    "baseline_success": a.get("score", {}).get("case_success"),
                    "candidate_success": b.get("score", {}).get("case_success"),
                    "changed_criteria": {
                        k: [oa.get(k), ob.get(k)]
                        for k in oa.keys() | ob.keys()
                        if oa.get(k) != ob.get(k)
                    },
                    "shared_answer_call": bool(a.get("answer_call"))
                    and a.get("answer_call") == b.get("answer_call"),
                    "selected_log_ids": [
                        s["log_id"] for s in b.get("selection", {}).get("spans", [])
                    ],
                    "omitted_log_ids": b.get("selection", {}).get(
                        "omitted_log_ids", []
                    ),
                }
            )
    result["total_inference"] = {
        kind: usage_summary([read(p) for p in sorted((work / kind).glob("*.json"))])
        for kind in ("answer_calls", "judge_calls")
    }
    result["case_review_inference"] = usage_summary(
        [
            read(path)
            for path in sorted((work / "case_review" / "review_calls").glob("*.json"))
        ]
    )
    for kind, limit in (("answer_calls", "answer_max"), ("judge_calls", "judge_max")):
        if (
            result["total_inference"][kind]["distinct_calls"]
            > registration["call_budget"][limit]
        ):
            raise ValueError("registered inference budget exceeded")
    result["artifact_integrity_passed"] = not result["integrity_issues"]
    return result


def run(work, workers):
    work = Path(work)
    registration, episodes = load_study(work)
    # Hold the study lock through inference; another CLI cannot start a second
    # matrix or export a partial comparison as a completed experiment.
    with (work / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = [
                pool.submit(evaluate_one, work, registration, e, plan)
                for plan in registration["runs"]
                for e in episodes
            ]
            for future in as_completed(jobs):
                row = future.result()
                print(
                    json.dumps(
                        {
                            "run": row["run"],
                            "episode": row["episode_id"],
                            "success": row.get("score", {}).get("case_success"),
                            "error": row.get("error"),
                        }
                    ),
                    flush=True,
                )
        report = compare(work)
        frozen_write(work / "comparison.json", report)
    return report


def export(work, destination):
    """Portable, complete evidence with shared source history and raw calls once."""
    work, destination = Path(work), Path(destination)
    with (work / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        report = compare(work)
        if not report["artifact_integrity_passed"]:
            raise ValueError(
                "cannot export a completed study with broken or missing artifacts"
            )
        bundle = {"format": STUDY_VERSION, "comparison": report, "files": {}}
        for path in sorted(work.rglob("*.json")):
            if path.name == "comparison.json":
                continue
            bundle["files"][str(path.relative_to(work))] = read(path)
        # Source episodes and full judge prompts intentionally remain auditable.
        # gzip avoids many copies of the same long history in a repository blob.
        import gzip

        payload = gzip.compress(
            json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode(), mtime=0
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != payload:
            raise ValueError("immutable export changed")
        destination.write_bytes(payload)
        return {
            "path": str(destination),
            "bundle_sha256": fingerprint(bundle),
            "bytes": len(payload),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("register", "run", "compare", "export"))
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--budget-chars", type=int, default=12000)
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument("--replicates", nargs="+", default=["r1"])
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.stage == "register":
        if not args.source:
            parser.error("register requires --source")
        result = register(
            args.source,
            args.workdir,
            budget=args.budget_chars,
            models=args.models,
            replicates=args.replicates,
        )
    elif args.stage == "run":
        result = run(args.workdir, args.workers)
    elif args.stage == "export":
        if not args.output:
            parser.error("export requires --output")
        result = export(args.workdir, args.output)
    else:
        result = compare(args.workdir)
    if args.output and args.stage != "export":
        frozen_write(args.output, result)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("runs", "paired_changes", "policies")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
