"""Bind answer reuse and repeated-run aggregation to exact experiments."""

from copy import deepcopy
from uuid import uuid4

from pipeline_integrity.artifacts import CURRENT, digest, file_digest


def answer_identity(raw_logs, questions, dataset, prompt, configuration):
    return {
        "schema": "answer-input-v1",
        "public_history_sha256": digest(raw_logs),
        "questions_sha256": digest(questions),
        "dataset_sha256": digest(dataset),
        "prompt_sha256": digest(prompt),
        "configuration": deepcopy(configuration),
    }


def bind_answers(answers, identity):
    if not isinstance(answers, dict) or not isinstance(answers.get("answers"), list):
        raise ValueError("Answer output must contain an answers list")  # noqa: TRY004 - malformed serialized input is a validation error
    result = deepcopy(answers)
    result.setdefault("metadata", {})["answer_run"] = {
        "schema": "answer-run-v1",
        "call_id": uuid4().hex,
        "identity": deepcopy(identity),
        "answers_sha256": digest(result["answers"]),
    }
    attempt = CURRENT.get()
    if attempt:
        result["metadata"]["answer_run"].update(
            source_attempt_id=attempt.name,
            raw_calls={
                path.name: file_digest(path) for path in sorted((attempt / "calls").glob("*.json"))
            },
        )
    return result


def validate_call_origin(answers, output_dir):
    from pathlib import Path

    run = answers["metadata"]["answer_run"]
    origin = run.get("source_attempt_id", "")
    if not origin or any(character not in "0123456789abcdef" for character in origin):
        raise ValueError("Answer call has no valid source attempt")
    for name, expected in run.get("raw_calls", {}).items():
        if (
            Path(name).name != name
            or file_digest(Path(output_dir) / ".attempts/step6" / origin / "calls" / name)
            != expected
        ):
            raise ValueError("Original raw answer call changed or is missing")


def validate_answers(answers, identity, case_ids):
    run = answers.get("metadata", {}).get("answer_run", {})
    if (
        run.get("schema") != "answer-run-v1"
        or not run.get("call_id")
        or run.get("identity") != identity
        or run.get("answers_sha256") != digest(answers.get("answers"))
    ):
        raise ValueError(
            "Saved answers do not match the current input/configuration or are unbound; rerun Pass 1"
        )
    ids = []
    for row in answers["answers"]:
        if not isinstance(row, dict) or row.get("test_case_id") not in case_ids:
            raise ValueError("Answer contains an unknown case ID")
        ids.append(row["test_case_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Answer contains duplicate case IDs")
    return run


def bind_result(
    result, answers, *, judge_configuration, judge_prompt, admission, fragments, implementation
):
    result.setdefault("metadata", {})["run_identity"] = {
        "schema": "benchmark-run-v1",
        "answer_run": deepcopy(answers["metadata"]["answer_run"]),
        "judge": {
            "configuration": judge_configuration,
            "prompt_sha256": digest(judge_prompt),
            "fragments_sha256": digest(fragments),
            "implementation": implementation,
        },
        "admission_sha256": digest(admission),
        "evaluations_sha256": digest(result["evaluations"]),
    }


def compatible_runs(payloads, *, allow_legacy=False):
    identities = [p.get("metadata", {}).get("run_identity") for p in payloads]
    if not all(identities):
        if any(identities) or not allow_legacy:
            raise ValueError(
                "Reliability requires bound runs; --allow-legacy is only for explicitly historical aggregation"
            )
        models = {
            (
                p.get("metadata", {}).get("model_used_pass1"),
                p.get("metadata", {}).get("model_used_pass2"),
            )
            for p in payloads
        }
        if len(models) > 1:
            raise ValueError("Cannot aggregate different model identities")
        hashes = {}
        for p in payloads:
            for cid, value in (
                p.get("metadata", {}).get("evaluation_manifest", {}).get("case_sha256", {}).items()
            ):
                if cid in hashes and hashes[cid] != value:
                    raise ValueError("Cannot aggregate different case contents")
                hashes[cid] = value
        return "historical_unbound"
    for p, identity in zip(payloads, identities, strict=True):
        if identity.get("schema") != "benchmark-run-v1" or identity.get(
            "evaluations_sha256"
        ) != digest(p.get("evaluations")):
            raise ValueError("Run contents differ from their recorded identity")
    ids = [identity["answer_run"].get("call_id") for identity in identities]
    if not all(ids) or len(set(ids)) != len(ids):
        raise ValueError(
            "Reliability requires distinct answer calls, not copies or rescores of one call"
        )
    comparable = [
        {
            "answer": identity["answer_run"]["identity"],
            "judge": identity["judge"],
            "admission": identity["admission_sha256"],
        }
        for identity in identities
    ]
    if any(row != comparable[0] for row in comparable[1:]):
        raise ValueError(
            "Cannot aggregate incompatible inputs, models, prompts, admission, or scorer versions"
        )
    return "bound"
