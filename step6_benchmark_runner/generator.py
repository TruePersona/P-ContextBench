"""Step 6 — Benchmark runner (two-pass: answering then scoring).

Pass 1: evaluator LLM sees raw app logs + questions only. No ground_truth in
        context. Writes pass1 answers.

Pass 2: scorer LLM sees test cases (with ground_truth) + Pass 1 answers.
        Writes the final verification report.

Subscription backend isolation: when --backend claude or --backend codex is
set, the runner deletes the target session directory between each model call
so prior Q&A does not leak into the current context. When running against the
Anthropic SDK directly, each test case is a fresh messages.create call, so
isolation is inherent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm import (
    API_BACKENDS,
    SUBSCRIPTION_BACKENDS,
    SUPPORTED_BACKENDS,
    SUPPORTED_PROVIDERS,
    call_llm,
    check_api_key,
    default_model_for_backend,
    make_client,
    provider_for_backend,
)
from step6_benchmark_runner import t5_contract, t5_scoring
from step6_benchmark_runner.passk import aggregate_passk
from utils import (
    extract_json,
    fill,
)

STEP_DIR = Path(__file__).parent
REPO_ROOT = STEP_DIR.parent
STEP4_OUTPUT_DIR = REPO_ROOT / "step4_app_log_synthesizer" / "data_samples"
PROMPT_PATH = STEP_DIR / "prompt.txt"

# ----- prompt splitting ----------------------------------------------------

def load_prompt_sections() -> dict[str, str]:
    """Split prompt into PASS 1 and PASS 2 sections on the big dividers."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    pass1_marker = "PASS 1 — ANSWERING"
    pass2_marker = "PASS 2 — SCORING"
    header_end = text.index(pass1_marker)
    pass2_start = text.index(pass2_marker)
    header = text[:header_end]
    pass1 = header + text[header_end:pass2_start]
    pass2 = header + text[pass2_start:]
    return {"pass1": pass1, "pass2": pass2}

def resolve_verified_fragments_path(app_logs_path: Path) -> Path | None:
    """Locate Step 4 {persona}_verified_fragments.json for Pass 2 scoring."""
    candidates: list[Path] = []
    if app_logs_path.name.endswith("_app_logs.json"):
        candidates.append(
            app_logs_path.with_name(
                app_logs_path.name.replace(
                    "_app_logs.json", "_verified_fragments.json"
                )
            )
        )
    stem = re.sub(r"_decoy\d+$", "", app_logs_path.stem.replace("_app_logs", ""))
    candidates.append(STEP4_OUTPUT_DIR / f"{stem}_verified_fragments.json")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


# ----- raw log preparation -------------------------------------------------

def strip_to_raw_logs(app_logs: dict[str, Any]) -> str:
    """Flatten messenger + calendar into a plain text stream for the evaluator."""
    lines: list[str] = []
    messenger = app_logs.get("messenger", {})
    sessions: list[dict[str, Any]] = []
    for bucket_name in ("meaningful_sessions", "filler_sessions", "sessions"):
        bucket = messenger.get(bucket_name, []) or []
        sessions.extend(bucket)
    sessions.sort(
        key=lambda s: (
            s.get("date", ""),
            (s.get("messages") or [{"time": ""}])[0].get("time", ""),
        )
    )
    persona_name = app_logs.get("persona_name") or app_logs.get("name", "persona")
    for s in sessions:
        contact = s.get("contact") or s.get("other_person") or "unknown"
        date = s.get("date", "")
        lines.append(f"--- {date} | {persona_name} <-> {contact} ---")
        for m in s.get("messages", []) or []:
            time = m.get("time", "")
            sender = m.get("sender", "")
            text = m.get("text", "")
            lines.append(f"[{time}] {sender}: {text}")
        lines.append("")

    calendar = app_logs.get("calendar", {})
    events = calendar.get("events", []) if isinstance(calendar, dict) else calendar or []
    events = sorted(
        events or [], key=lambda e: (e.get("date", ""), e.get("start_time", ""))
    )
    for e in events:
        date = e.get("date", "")
        start = e.get("start_time", "")
        end = e.get("end_time", "")
        title = e.get("title", "")
        loc = e.get("location", "")
        participants = ", ".join(e.get("participants", []) or [])
        notes = e.get("notes", "")
        lines.append(
            f"{date} | {start}-{end} | {title} | @ {loc} | with {participants} "
            f"| Notes: {notes}"
        )

    return "\n".join(lines)


FIELDS_HIDDEN_FROM_PASS1 = {
    "ground_truth",
    "type_5_contract",
    "acceptable_resolution_labels",
    "evidence_type",
    "expected_evidence",
    "is_capstone",
    "source_hidden_fact_ids",
    "source_subcategories",
    "risk_surface_score",
    "subtype",
    "user_prompt_context",
    "expected_behavior",
    "expected_resolution_label",
    "expected_action_boundary",
    "naive_compliance_consequence",
    "construction_tags",
    "hidden_fact_reasoning_roles",
    "fact_check_risk",
    "reasoning_requirement",
    "expected_current_state",
    "prior_state",
    "dynamic_pattern",
    "temporal_distractor",
    "change_explanation",
    "source_hidden_fact_requirements",
    "ground_truth_label_justification",
    "supporting_context",
    "reasoning_conclusion",
    "reasoning_mechanism",
    "reasoning_distractor",
    "required_evidence_roles"
 
}


def strip_ground_truth(test_cases: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of test_cases with answer-key fields removed.
    Questions, ids, types and framing remain visible to Pass 1."""
    stripped = {"metadata": test_cases.get("metadata", {}), "test_cases": []}
    for tc in test_cases.get("test_cases", []):
        stripped["test_cases"].append(
            {
                k: v
                for k, v in tc.items()
                if k not in FIELDS_HIDDEN_FROM_PASS1
            }
        )
    return stripped

# ----- passes --------------------------------------------------------------

def run_pass_1(
    raw_logs: str,
    test_cases_stripped: dict[str, Any],
    model: str,
    client: Any | None,
    backend: str,
    provider: str,
    response_format: str,
    reasoning_effort: str
) -> dict[str, Any]:
    sections = load_prompt_sections()
    template = fill(sections["pass1"], "{{INSERT_RAW_LOGS_TEXT_HERE}}", raw_logs)
    template = fill(
        template,
        "{{INSERT_TEST_CASE_QUESTIONS_JSON_HERE}}",
        test_cases_stripped,
    )
    
    raw = call_llm(client, model, template, reasoning_effort, provider, backend, response_format)

    return extract_json(raw)


def _call_pass2_single(
    sections: dict[str, str],
    test_cases_batch: dict[str, Any],
    answers_batch: dict[str, Any],
    model: str,
    client: Any | None,
    backend: str,
    provider: str,
    response_format: str,
    reasoning_effort: str,
    verified_fragments_path: Path | None = None,
    correction: str | None = None,
) -> dict[str, Any]:
    template = fill(
        sections["pass2"], "{{INSERT_FULL_TEST_CASES_JSON_HERE}}", test_cases_batch
    )
    template = fill(
        template, "{{INSERT_PASS_1_ANSWERS_JSON_HERE}}", answers_batch
    )
    if verified_fragments_path and verified_fragments_path.exists():
        verified_fragments = json.loads(
            verified_fragments_path.read_text(encoding="utf-8")
        )
    else:
        if verified_fragments_path:
            print(
                f"[pass 2] warning: verified fragments not found at "
                f"{verified_fragments_path}; using empty list"
            )
        verified_fragments = []
    template = fill(
        template, "{{INSERT_VERIFIED_FRAGMENTS_JSON_HERE}}", verified_fragments
    )
    if correction:
        # Retry after an off-schema answer: tell the judge what was wrong so
        # the second attempt is not a blind repeat of the first.
        template += (
            "\n\nYour previous output for these cases did not follow the schema:\n"
            + correction
            + "\n\nReturn the complete JSON for all cases again, using only the "
            "listed values."
        )

    raw = call_llm(client, model, template, reasoning_effort, provider, backend, response_format)

    return extract_json(raw)


def _check_pass2_batch(
    result: dict[str, Any],
    batch_cases: list[dict[str, Any]],
    answers: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Bind judge observations to canonical cases; reject ambiguous duplicate IDs."""
    evals = result.get("evaluations", []) if isinstance(result, dict) else []
    if not evals and isinstance(result, dict) and "test_case_id" in result:
        evals = [result]
    if not isinstance(evals, list):
        evals = []
    by_id: dict[str, list[dict[str, Any]]] = {}
    for ev in evals:
        if isinstance(ev, dict) and isinstance(ev.get("test_case_id"), str):
            by_id.setdefault(ev["test_case_id"], []).append(ev)

    accepted: list[dict[str, Any]] = []
    problems: dict[str, list[str]] = {}
    for tc in batch_cases:
        case_id = tc["id"]
        records = by_id.get(case_id, [])
        if len(records) != 1:
            problems[case_id] = ["expected exactly one evaluation record for this ID"]
            continue
        record = deepcopy(records[0])
        if normalize_case_type(tc.get("type")) == "type_5_agent_behavior":
            found = (
                t5_contract.validate_observations(
                    record, tc, (answers or {}).get(case_id)
                )
                if "type_5_contract" in tc
                else t5_scoring.validate_type5(record)
            )
            if found:
                problems[case_id] = found
                continue
            # Never trust audit/scorer-owned fields supplied by the judge.
            raw = deepcopy(record)
            for key in (
                "raw_judgment",
                "scoring_history",
                "scoring_provenance",
                "judge_reported",
                "rubric_version",
                "behavioral_success",
                "evaluation_status",
            ):
                record.pop(key, None)
            record["raw_judgment"] = raw
        record["type"] = normalize_case_type(tc.get("type"))
        record["subtype"] = tc.get("subtype")
        record["is_capstone"] = bool(tc.get("is_capstone"))
        accepted.append(record)
    return accepted, problems


def _off_schema_placeholder(
    tc: dict[str, Any], problems: list[str], record: dict[str, Any] | None
) -> dict[str, Any]:
    """Zero-credit record for a case whose judge output stayed off schema."""
    placeholder = {
        "test_case_id": tc.get("id"),
        "type": tc.get("type"),
        "score": "FAILED_EVALUATION",
        "score_value": 0.0,
        "evaluation_status": "judge_output_off_schema",
        "explanation": "Judge output did not follow the schema after a retry: "
        + "; ".join(problems),
    }
    if record is not None:
        placeholder["judge_reported"] = record
    return placeholder


def _score_batch(
    sections: dict[str, str],
    tc_batch: dict[str, Any],
    ans_batch: dict[str, Any],
    label: str,
    call_kwargs: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], int, int]:
    """Score one batch with the retry policy shared by every backend.

    Up to three attempts. A response that is not JSON is retried as before.
    A response whose Type 5 records use values outside the schema is retried
    once with the problems spelled out. Keep the first valid record per ID;
    send only pending IDs on later attempts. Unresolved cases become explicit
    evaluation-error placeholders after the bounded retry budget.
    Returns (evaluations, raw result, off_schema_count, batch_failed).
    """
    batch_cases = tc_batch.get("test_cases", [])
    answers = {
        a["test_case_id"]: a
        for a in ans_batch.get("answers", [])
        if isinstance(a, dict) and isinstance(a.get("test_case_id"), str)
    }
    accepted: dict[str, dict[str, Any]] = {}
    problems: dict[str, list[str]] = {}
    raw_by_id: dict[str, dict[str, Any]] = {}
    result: dict[str, Any] = {}
    correction = None
    corrections_sent = 0
    last_exc: Exception | None = None
    for attempt in range(3):
        pending = [tc for tc in batch_cases if tc["id"] not in accepted]
        pending_ids = {tc["id"] for tc in pending}
        try:
            current = _call_pass2_single(
                sections,
                {**tc_batch, "test_cases": pending},
                {
                    **ans_batch,
                    "answers": [a for cid, a in answers.items() if cid in pending_ids],
                },
                correction=correction,
                **call_kwargs,
            )
        except (ValueError, RuntimeError) as exc:
            last_exc = exc
            print(f"    {label} attempt {attempt + 1} failed: {exc}")
            continue
        if isinstance(current, dict):
            result = current
        valid, problems = _check_pass2_batch(current, pending, answers)
        for record in valid:
            accepted.setdefault(record["test_case_id"], record)
        raw = current.get("evaluations", []) if isinstance(current, dict) else []
        if not raw and isinstance(current, dict) and "test_case_id" in current:
            raw = [current]
        for ev in raw if isinstance(raw, list) else []:
            if isinstance(ev, dict) and isinstance(ev.get("test_case_id"), str):
                raw_by_id[ev["test_case_id"]] = ev
        if not problems:
            break
        if corrections_sent or attempt == 2:
            break
        corrections_sent += 1
        correction = "\n".join(
            f"- {cid}: " + "; ".join(found) for cid, found in problems.items()
        )
        print(f"    {label}: retrying {len(problems)} unresolved record(s)")

    off_schema = 0
    failed = 0
    for tc in batch_cases:
        cid = tc["id"]
        if cid in accepted:
            continue
        if cid in problems:
            accepted[cid] = _off_schema_placeholder(
                tc, problems[cid], raw_by_id.get(cid)
            )
            off_schema += 1
        else:
            accepted[cid] = {
                "test_case_id": cid,
                "type": tc.get("type"),
                "score": "FAILED_EVALUATION",
                "score_value": 0.0,
                "evaluation_status": "judge_batch_failed",
                "explanation": f"Pass 2 {label} failed after 3 attempts: {last_exc}",
            }
            failed = 1
    return [accepted[tc["id"]] for tc in batch_cases], result, off_schema, failed


def run_pass_2(
    test_cases_full: dict[str, Any],
    pass1_answers: dict[str, Any],
    model: str,
    client: Any | None,
    backend: str,
    provider: str,
    response_format: str,
    reasoning_effort: str,
    batch_size: int = 5,
    verified_fragments_path: Path | None = None,
) -> dict[str, Any]:
    sections = load_prompt_sections()
    all_cases = test_cases_full.get("test_cases", [])
    _canonical_map(all_cases, "id")
    _canonical_map(pass1_answers.get("answers", []), "test_case_id")
    for tc in all_cases:
        if "type_5_contract" in tc:
            problems = t5_contract.validate_contract(tc)
            if problems:
                raise ValueError(
                    f"Invalid contract for {tc['id']}: {'; '.join(problems)}"
                )
    all_answers = pass1_answers.get("answers", [])
    call_kwargs = {
        "model": model,
        "client": client,
        "backend": backend,
        "provider": provider,
        "response_format": response_format,
        "reasoning_effort": reasoning_effort,
        "verified_fragments_path": verified_fragments_path,
    }

    # API backends take the whole case set in one call; subscription CLIs
    # are batched. Both go through _score_batch so the retry and schema
    # policy is the same regardless of backend.
    batched = backend in SUBSCRIPTION_BACKENDS and len(all_cases) > batch_size
    step = batch_size if batched else max(len(all_cases), 1)
    total_batches = (len(all_cases) + step - 1) // step

    merged_evaluations: list[dict[str, Any]] = []
    merged_result: dict[str, Any] = {}
    failed_batches = 0
    off_schema = 0

    for i in range(0, len(all_cases), step):
        batch_cases = all_cases[i : i + step]
        batch_ids = {c["id"] for c in batch_cases}
        batch_answers = [a for a in all_answers if a.get("test_case_id") in batch_ids]

        tc_batch = dict(test_cases_full)
        tc_batch["test_cases"] = batch_cases
        ans_batch = dict(pass1_answers)
        ans_batch["answers"] = batch_answers

        batch_num = i // step + 1
        label = f"batch {batch_num}" if batched else "pass 2"
        if batched:
            print(
                f"  [pass 2 batch {batch_num}/{total_batches}] scoring {len(batch_cases)} cases"
            )

        evals, result, n_off, n_failed = _score_batch(
            sections, tc_batch, ans_batch, label, call_kwargs
        )
        merged_evaluations.extend(evals)
        off_schema += n_off
        failed_batches += n_failed
        if not merged_result and result:
            merged_result = result

    if not merged_result:
        merged_result = {"evaluations": [], "metadata": {}}
    merged_result["evaluations"] = merged_evaluations
    merged_result["metadata"] = t5_scoring._as_dict(merged_result.get("metadata"))
    merged_result["metadata"].pop("evaluation_manifest", None)
    merged_result["metadata"]["total_cases"] = len(all_cases)
    merged_result["metadata"]["batched"] = batched
    merged_result["metadata"]["batches_total"] = total_batches
    merged_result["metadata"]["batches_failed"] = failed_batches
    merged_result["metadata"]["off_schema_cases"] = off_schema
    return merged_result


def _percent(score_sum: float, total: int) -> str:
    if total == 0:
        return "N/A"
    value = round((score_sum / total) * 100, 1)
    if value.is_integer():
        return f"{int(value)}%"
    return f"{value}%"


# evaluation_status values of zero-credit placeholder records. They carry no
# judge output, so the Type 5 recomputation skips them and the summary counts
# them as failed evaluations.
PLACEHOLDER_STATUSES = (
    "judge_batch_failed",
    "missing_evaluation",
    "judge_output_off_schema",
    "judge_uncertain",
    "scoring_input_invalid",
)


_SUBTYPE_TYPE_RE = re.compile(r"^5[a-z]_", re.IGNORECASE)


def normalize_case_type(raw: Any) -> str:
    """Map a stored case type onto its canonical type string.

    Some Step 5 files carry the T5 subtype (e.g. ``5c_ambiguity``) in the
    type field; bucketing on the raw string would split those cases into
    phantom types.
    """
    value = str(raw or "").strip()
    if _SUBTYPE_TYPE_RE.match(value):
        return "type_5_agent_behavior"
    return value.lower() or "unknown"


def _canonical_map(
    records: list[dict[str, Any]], id_key: str
) -> dict[str, dict[str, Any]]:
    by_id = {}
    for record in records:
        if not isinstance(record, dict):
            raise TypeError(f"Expected objects with {id_key}")
        cid = record.get(id_key)
        if not isinstance(cid, str) or not cid or cid in by_id:
            raise ValueError(f"Missing or duplicate {id_key}: {cid!r}")
        by_id[cid] = record
    return by_id


def apply_t5_scoring(
    evaluations: list[dict[str, Any]],
    case_map: dict[Any, dict[str, Any]],
    pass1_answers: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Score canonical Type 5 cases and retain immutable raw judgments."""
    answers = _canonical_map((pass1_answers or {}).get("answers", []), "test_case_id")
    counters = {
        "type_5_recomputed": 0,
        "type_5_not_recomputed": 0,
        "type_5_score_value_changed": 0,
        "type_5_verdict_changed": 0,
        "type_5_resolution_label_changed": 0,
    }
    for ev in evaluations:
        cid = ev.get("test_case_id")
        tc = case_map.get(cid)
        if tc is None or normalize_case_type(tc.get("type")) != "type_5_agent_behavior":
            continue
        version = (
            t5_contract.RUBRIC_VERSION
            if "type_5_contract" in tc
            else t5_scoring.RUBRIC_VERSION
        )
        if ev.get("evaluation_status") in {
            "judge_batch_failed",
            "missing_evaluation",
            "judge_output_off_schema",
        }:
            ev["rubric_version"] = version
            continue
        ev.setdefault(
            "raw_judgment",
            deepcopy(
                {
                    k: v
                    for k, v in ev.items()
                    if k
                    not in {"raw_judgment", "scoring_history", "scoring_provenance"}
                }
            ),
        )
        raw = ev["raw_judgment"]
        ev["type"] = "type_5_agent_behavior"
        ev["subtype"] = tc.get("subtype")
        ev["is_capstone"] = bool(tc.get("is_capstone"))
        old_dimensions = t5_scoring._as_dict(ev.get("type_5_dimensions"))
        old_b = old_dimensions.get(
            t5_scoring.DIMENSION_B, old_dimensions.get(t5_scoring.DIMENSION_B_LEGACY)
        )
        old_comparison = t5_scoring._as_dict(ev.get("type_5_label_comparison"))
        ev.setdefault(
            "judge_reported",
            {
                "score": raw.get("score"),
                "score_value": raw.get("score_value"),
                "resolution_label": old_b,
                "resolution_match": old_comparison.get("resolution_match"),
            },
        )
        answer = answers.get(cid)
        previous = ev.get("scoring_provenance", {})
        error = None
        actual = None
        label_source = "not_used"
        if "type_5_contract" in tc:
            # An offline behavior rescore requires the same original answer;
            # old A/C scores cannot be converted into behavioral observations.
            problems = t5_contract.validate_observations(raw, tc, answer)
            if problems:
                derived = None
                error = "; ".join(problems)
            else:
                derived = t5_contract.score_contract(raw, tc, answer)
        else:
            if pass1_answers is not None:
                actual = t5_scoring._as_dict(
                    (answer or {}).get("type_5_action_summary")
                ).get("intended_resolution_label")
                label_source = "pass1"
            elif previous.get("actual_label") is not None:
                actual = previous["actual_label"]
                label_source = previous.get("label_source", "stored_scoring_input")
            else:
                actual = t5_scoring._as_dict(raw.get("type_5_label_comparison")).get(
                    "actual_resolution_label"
                )
                label_source = "legacy_judge_echo"
            derived = (
                t5_scoring.score_type5(raw, tc, actual)
                if t5_scoring.normalize_label(actual) is not None
                else None
            )
            if derived is None:
                error = "Legacy scoring requires valid canonical labels, A/C in {0,1,3,5}, and valid semantic penalties."

        if derived is None:
            counters["type_5_not_recomputed"] += 1
            for key in (
                "type_5_dimensions", "type_5_label_comparison", "failure_modes",
                "final_score_15", "type_5_behavior", "behavioral_success", "scoring_provenance",
            ):
                ev.pop(key, None)
            ev.update(
                score="FAILED_EVALUATION",
                score_value=0.0,
                evaluation_status="scoring_input_invalid",
                scoring_error=error,
                rubric_version=version,
            )
            continue
        counters["type_5_recomputed"] += 1
        counters["type_5_score_value_changed"] += (
            ev.get("score_value") != derived["score_value"]
        )
        counters["type_5_verdict_changed"] += ev.get("score") != derived["score"]
        if "type_5_contract" in tc:
            ev.update(derived)
            # No legacy score components or penalties in the behavior rubric.
            for key in (
                "type_5_dimensions",
                "final_score_15",
                "failure_modes",
                "type_5_label_comparison",
            ):
                ev.pop(key, None)
        else:
            counters["type_5_resolution_label_changed"] += (
                old_b != derived["resolution_label"]
            )
            dimensions = deepcopy(raw["type_5_dimensions"])
            dimensions.pop(t5_scoring.DIMENSION_B_LEGACY, None)
            dimensions[t5_scoring.DIMENSION_B] = derived["resolution_label"]
            ev["type_5_dimensions"] = dimensions
            ev["type_5_label_comparison"] = {
                "expected_resolution_label": t5_scoring.normalize_label(
                    tc["expected_resolution_label"]
                ),
                "actual_resolution_label": t5_scoring.normalize_label(actual),
                "resolution_match": derived["resolution_match"],
            }
            ev["failure_modes"] = {
                name: derived["penalties"].get(name, 0)
                for name in t5_scoring.PENALTY_KEYS
            }
            for key in ("final_score_15", "score_value", "score"):
                ev[key] = derived[key]
            ev["rubric_version"] = version
            ev["evaluation_status"] = "evaluated"
        ev.pop("scoring_error", None)
        provenance = {
            "rubric_version": version,
            "case_sha256": t5_contract.fingerprint(tc),
            "answer_sha256": t5_contract.fingerprint(answer)
            if answer is not None
            else previous.get("answer_sha256"),
            "judgment_sha256": t5_contract.fingerprint(raw),
            "actual_label": actual,
            "label_source": label_source,
            "legacy_missing_penalties_assumed_zero": (
                sorted(
                    set(t5_scoring.PENALTY_MAGNITUDES)
                    - set(t5_scoring._as_dict(raw.get("failure_modes")))
                )
                if "type_5_contract" not in tc
                else []
            ),
        }
        ev["scoring_provenance"] = provenance
        history = ev.setdefault("scoring_history", [])
        entry = {
            "inputs": provenance,
            "score": ev["score"],
            "score_value": ev["score_value"],
        }
        if not history or history[-1] != entry:
            history.append(deepcopy(entry))
    return counters


def recompute_benchmark_summary(
    result: dict[str, Any],
    test_cases_full: dict[str, Any],
    model_pass1: str,
    model_pass2: str,
    pass1_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute headline metrics after batched scoring merges evaluations."""
    evaluations = result.get("evaluations", []) or []
    case_map = _canonical_map(test_cases_full.get("test_cases", []), "id")
    evaluation_map = _canonical_map(evaluations, "test_case_id")
    unknown = sorted(set(evaluation_map) - set(case_map))
    if unknown:
        raise ValueError(f"Evaluations outside the eligible case population: {unknown}")
    t5_counters = apply_t5_scoring(evaluations, case_map, pass1_answers)
    for ev in evaluations:
        tc = case_map[ev["test_case_id"]]
        ev["type"] = normalize_case_type(tc.get("type"))
        if tc.get("subtype"):
            ev["subtype"] = tc["subtype"]

    # Freeze the denominator to the intended case set: any intended case
    # without an evaluation record is scored as an explicit zero-credit
    # failure rather than silently dropped.
    evaluated_ids = {ev.get("test_case_id") for ev in evaluations}
    for case_id, tc in case_map.items():
        if case_id not in evaluated_ids:
            evaluations.append(
                {
                    "test_case_id": case_id,
                    "type": tc.get("type"),
                    "score": "FAILED_EVALUATION",
                    "score_value": 0.0,
                    "evaluation_status": "missing_evaluation",
                    "explanation": "No Pass 2 evaluation record was produced.",
                }
            )
    for ev in evaluations:
        tc = case_map[ev["test_case_id"]]
        if normalize_case_type(tc.get("type")) == "type_5_agent_behavior":
            ev["rubric_version"] = (
                t5_contract.RUBRIC_VERSION
                if "type_5_contract" in tc
                else t5_scoring.RUBRIC_VERSION
            )
    result["evaluations"] = evaluations
    failed_count = sum(
        1 for ev in evaluations if ev.get("evaluation_status") in PLACEHOLDER_STATUSES
    )

    total_score = sum(float(ev.get("score_value", 0) or 0) for ev in evaluations)
    result["overall_accuracy"] = _percent(total_score, len(evaluations))

    by_type: dict[str, list[float]] = {}
    for ev in evaluations:
        by_type.setdefault(normalize_case_type(ev.get("type")), []).append(
            float(ev.get("score_value", 0) or 0)
        )
    result["accuracy_by_type"] = {
        typ: _percent(sum(scores), len(scores))
        for typ, scores in sorted(by_type.items())
    }

    type5 = [
        ev
        for ev in evaluations
        if normalize_case_type(ev.get("type")) == "type_5_agent_behavior"
    ]
    subtype_scores: dict[str, list[float]] = {}
    dimension_scores: dict[str, list[float]] = {}
    capstone_result = "N/A"
    for ev in type5:
        tc = case_map.get(ev.get("test_case_id"), {})
        subtype = tc.get("subtype") or (
            str(tc.get("type")).strip().lower()
            if _SUBTYPE_TYPE_RE.match(str(tc.get("type") or ""))
            else "unknown"
        )
        subtype_scores.setdefault(subtype, []).append(
            float(ev.get("score_value", 0) or 0)
        )
        dimensions = (ev.get("type_5_dimensions") or {}) if ev.get("evaluation_status") not in PLACEHOLDER_STATUSES else {}
        for dim, value in dimensions.items():
            if isinstance(value, (int, float)):
                dimension_scores.setdefault(dim, []).append(float(value))
        if tc.get("is_capstone"):
            capstone_result = ev.get("score", "N/A")

    result["type_5_breakdown"] = {
        "by_subtype": {
            subtype: _percent(sum(scores), len(scores))
            for subtype, scores in sorted(subtype_scores.items())
        },
        "by_dimension": {
            dim: round(sum(scores) / len(scores), 2)
            for dim, scores in sorted(dimension_scores.items())
            if scores
        },
        "capstone_result": capstone_result,
    }

    metadata = result.setdefault("metadata", {})
    metadata["model_used_pass1"] = model_pass1
    metadata["model_used_pass2"] = model_pass2
    metadata["total_cases"] = len(evaluations)
    metadata["failed_evaluation_cases"] = failed_count
    metadata["type_5_scoring"] = t5_counters
    manifest = {
        "eligible_case_ids": list(case_map),
        "case_sha256": {
            cid: t5_contract.fingerprint(tc) for cid, tc in case_map.items()
        },
    }
    existing_manifest = metadata.get("evaluation_manifest")
    if existing_manifest and existing_manifest != manifest:
        raise ValueError(
            "Eligible cases or case contents differ from the frozen evaluation manifest"
        )
    metadata["evaluation_manifest"] = manifest
    metadata["evaluation_coverage"] = {
        "intended_cases": len(evaluations),
        "evaluated_cases": len(evaluations) - failed_count,
        "evaluation_errors": failed_count,
        "coverage_percent": _percent(len(evaluations) - failed_count, len(evaluations)),
        "score_lower_bound": _percent(total_score, len(evaluations)),
        "score_upper_bound": _percent(total_score + failed_count, len(evaluations)),
    }
    versions: dict[str, list[dict[str, Any]]] = {}
    for ev in type5:
        version = ev.get("rubric_version") or (
            t5_contract.RUBRIC_VERSION
            if "type_5_contract" in case_map[ev["test_case_id"]]
            else t5_scoring.RUBRIC_VERSION
        )
        versions.setdefault(version, []).append(ev)
    result["type_5_breakdown"]["by_rubric_version"] = {
        version: {
            "case_count": len(records),
            "average_score": _percent(
                sum(float(e.get("score_value", 0)) for e in records), len(records)
            ),
            "evaluation_errors": sum(
                e.get("evaluation_status") in PLACEHOLDER_STATUSES for e in records
            ),
        }
        for version, records in sorted(versions.items())
    }
    behavior = [
        ev for ev in type5 if ev.get("rubric_version") == t5_contract.RUBRIC_VERSION
    ]
    result["type_5_breakdown"]["behavioral_success"] = {
        "case_count": len(behavior),
        "success_count": sum(ev.get("behavioral_success") is True for ev in behavior),
        "success_rate_lower_bound": _percent(
            sum(ev.get("behavioral_success") is True for ev in behavior), len(behavior)
        ),
        "by_dimension": {
            dimension: _percent(sum(values), len(values))
            for dimension in t5_contract.DIMENSIONS
            if (
                values := [
                    ev["type_5_behavior"]["dimensions"][dimension]
                    for ev in behavior
                    if ev.get("evaluation_status") not in PLACEHOLDER_STATUSES
                    and ev.get("type_5_behavior", {})
                    .get("dimensions", {})
                    .get(dimension)
                    is not None
                ]
            )
        },
    }
    return result


# ----- entry point ---------------------------------------------------------

def run_step_once(
    app_logs_path: Path,
    test_cases_path: Path,
    output_dir: Path,
    model_pass1: str,
    model_pass2: str,
    backend: str,
    backend_pass2: str,
    provider: str,
    provider_pass2: str,
    response_format: str,
    run_index: int | None = None,
    skip_pass1: bool = False,
    skip_pass2: bool = False,
    reasoning_pass1: str = "low",
    reasoning_pass2: str = "high",
) -> Path:
    app_logs = json.loads(app_logs_path.read_text(encoding="utf-8"))
    test_cases = json.loads(test_cases_path.read_text(encoding="utf-8"))

    # Filter out REJECTED test cases from Step 5 verification
    verification_path = test_cases_path.parent / test_cases_path.name.replace(
        "_test_cases.json", "_test_cases_verification.json"
    )
    verification = {}
    if verification_path.exists():
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        rejected_ids: set[str] = set()
        for ev in verification.get("evaluations", []):
            if ev.get("overall_verdict") == "REJECTED":
                eid = ev.get("test_case_id") or ev.get("id") or ""
                if eid:
                    rejected_ids.add(eid)
        if rejected_ids:
            original_count = len(test_cases.get("test_cases", []))
            test_cases["test_cases"] = [
                tc for tc in test_cases.get("test_cases", [])
                if (tc.get("id") or tc.get("test_case_id") or "") not in rejected_ids
            ]
            filtered_count = len(test_cases["test_cases"])
            if "metadata" in test_cases:
                test_cases["metadata"]["total_test_cases"] = filtered_count
            print(
                f"[step6] filtered {original_count - filtered_count} REJECTED "
                f"test cases ({filtered_count} remain)"
            )

    _canonical_map(test_cases.get("test_cases", []), "id")
    contract_review_errors = t5_contract.validate_verified_contracts(test_cases.get("test_cases", []), verification)
    if contract_review_errors:
        raise ValueError("; ".join(contract_review_errors))
    for case in test_cases.get("test_cases", []):
        if "type_5_contract" in case:
            problems = t5_contract.validate_contract(case, t5_contract.log_strings(app_logs))
            if problems:
                raise ValueError(f"Invalid contract for {case['id']}: {'; '.join(problems)}")
    raw_logs = strip_to_raw_logs(app_logs)
    stripped = strip_ground_truth(test_cases)

    base_name = test_cases_path.stem.replace("_test_cases", "")
    suffix = f"_run{run_index:02d}" if run_index is not None else ""
    output_dir.mkdir(parents=True, exist_ok=True)
    pass1_out = output_dir / f"{base_name}{suffix}_pass1_answers.json"
    pass2_out = output_dir / f"{base_name}{suffix}_benchmark_results.json"
    raw_logs_out = output_dir / f"{base_name}_app_logs_raw.txt"
    raw_logs_out.write_text(raw_logs, encoding="utf-8")

    verified_fragments_path = resolve_verified_fragments_path(app_logs_path)
    if verified_fragments_path:
        print(f"[step6] verified fragments: {verified_fragments_path}")
    else:
        print(
            f"[step6] verified fragments not found for {app_logs_path.name}; "
            "Pass 2 will score without them"
        )

    if skip_pass1 and pass1_out.exists():
        print(f"[pass 1] skipped — loading existing {pass1_out.name}")
        pass1 = json.loads(pass1_out.read_text(encoding="utf-8"))
        model_pass1 = pass1.get("metadata", {}).get("model_used", model_pass1)
    else:
        client = None
        if backend in API_BACKENDS:
            client = make_client(provider)

        print(f"[pass 1] answering {len(stripped['test_cases'])} cases for {base_name}")
        pass1 = run_pass_1(
            raw_logs,
            stripped,
            model_pass1,
            client=client,
            backend=backend,
            provider=provider,
            response_format=response_format,
            reasoning_effort=reasoning_pass1,
        )
        pass1_out.write_text(json.dumps(pass1, indent=2, ensure_ascii=False), encoding="utf-8")
        pass1.setdefault("metadata", {})
        pass1["metadata"]["model_used"] = model_pass1
        pass1["metadata"]["reasoning_effort"] = reasoning_pass1
        pass1["metadata"]["cases_answered"] = len(stripped["test_cases"])
        pass1_out.write_text(json.dumps(pass1, indent=2, ensure_ascii=False), encoding="utf-8")

    if skip_pass2:
        print("[done] (pass 2 skipped)")
        return pass1_out
    
    client_pass2 = None
    if backend_pass2 in API_BACKENDS:
        client_pass2 = make_client(provider_pass2)

    print(f"[pass 2] scoring answers for {base_name}")
    pass2 = run_pass_2(
        test_cases,
        pass1,
        model_pass2,
        client_pass2,
        backend=backend_pass2,
        provider=provider_pass2,
        response_format=response_format,
        reasoning_effort=reasoning_pass2,
        verified_fragments_path=verified_fragments_path,
    )
    pass2 = recompute_benchmark_summary(
        pass2, test_cases, model_pass1, model_pass2, pass1_answers=pass1
    )
    pass2.setdefault("metadata", {})
    pass2["metadata"]["reasoning_effort_pass1"] = reasoning_pass1
    pass2["metadata"]["reasoning_effort_pass2"] = reasoning_pass2
    pass2_out.write_text(json.dumps(pass2, indent=2, ensure_ascii=False), encoding="utf-8")

    accuracy = pass2.get("overall_accuracy", "unknown")
    print(f"[done] overall_accuracy={accuracy}")
    return pass2_out


def run_step(
    app_logs_path: Path,
    test_cases_path: Path,
    output_dir: Path,
    model_pass1: str,
    model_pass2: str,
    backend: str,
    backend_pass2: str,
    provider: str,
    provider_pass2: str,
    response_format: str,
    skip_pass1: bool = False,
    skip_pass2: bool = False,
    reasoning_pass1: str = "low",
    reasoning_pass2: str = "high",
) -> int:
    run_step_once(
        app_logs_path,
        test_cases_path,
        output_dir,
        model_pass1,
        model_pass2,
        backend,
        backend_pass2,
        provider,
        provider_pass2,
        response_format,
        skip_pass1=skip_pass1,
        skip_pass2=skip_pass2,
        reasoning_pass1=reasoning_pass1,
        reasoning_pass2=reasoning_pass2,
    )
    return 0


def run_passk_step(
    app_logs_path: Path,
    test_cases_path: Path,
    output_dir: Path,
    model_pass1: str,
    model_pass2: str,
    backend: str,
    backend_pass2: str,
    provider: str,
    provider_pass2: str,
    response_format,
    runs: int,
    passk_output: Path | None = None,
    allow_missing: bool = False,
    skip_pass1: bool = False,
    skip_pass2: bool = False,
    reasoning_pass1: str = "low",
    reasoning_pass2: str = "high",
) -> int:
    if runs < 2:
        raise ValueError("Pass^k mode requires at least two runs")

    result_paths: list[Path] = []
    for run_index in range(1, runs + 1):
        print(f"[pass^k] run {run_index}/{runs}")
        result_paths.append(
            run_step_once(
                app_logs_path,
                test_cases_path,
                output_dir,
                model_pass1,
                model_pass2,
                backend,
                backend_pass2,
                provider,
                provider_pass2,
                response_format,
                run_index=run_index,
                skip_pass1=skip_pass1,
                skip_pass2=skip_pass2,
                reasoning_pass1=reasoning_pass1,
                reasoning_pass2=reasoning_pass2,
            )
        )

    if skip_pass2:
        print("[pass^k] done (scoring skipped)")
    else:
        summary = aggregate_passk(
            result_paths,
            test_cases_path=test_cases_path,
            allow_missing=allow_missing,
        )
        if passk_output is None:
            base_name = test_cases_path.stem.replace("_test_cases", "")
            passk_output = output_dir / f"{base_name}_pass{runs}_summary.json"

        passk_output.parent.mkdir(parents=True, exist_ok=True)
        passk_output.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[pass^k] wrote {passk_output}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-logs", type=Path, required=True,
        help="Path to {persona}_app_logs.json",
    )
    parser.add_argument(
        "--test-cases", type=Path, required=True,
        help="Path to {persona}_test_cases.json",
    )
    parser.add_argument(
        "--output", type=Path, default=STEP_DIR / "data_samples",
    )
    parser.add_argument("--model-pass1", default=None)
    parser.add_argument("--model-pass2", default=None)
    parser.add_argument("--reasoning-pass1", default="low")
    parser.add_argument("--reasoning-pass2", default="high")
    parser.add_argument(
        "--backend",
        default="anthropic-api",
        choices=SUPPORTED_BACKENDS,
        help="Inference backend: anthropic-api uses ANTHROPIC_API_KEY; "
        "openai-api uses OPENAI_API_KEY; claude and codex use logged-in CLIs.",
    )
    parser.add_argument(
        "--backend-pass2",
        default=None,
        choices=SUPPORTED_BACKENDS,
        help="Optional scoring backend: anthropic-api uses ANTHROPIC_API_KEY; "
        "openai-api uses OPENAI_API_KEY; claude and codex use logged-in CLIs. "
        "Defaults to match --backend.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=SUPPORTED_PROVIDERS,
        help="Optional API provider override for compatibility (pass 1). "
        "openrouter uses OPENROUTER_API_KEY and is compatible with openai-api",
    )
    parser.add_argument(
        "--provider-pass2",
        default=None,
        choices=SUPPORTED_PROVIDERS,
        help="Optional API provider override for compatibility (pass 2). "
        "openrouter uses OPENROUTER_API_KEY and is compatible with openai-api",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Optional response format override for JSON outputs (openai-api).",
    )
    parser.add_argument(
        "--skip-pass1",
        action="store_true",
        help="Skip Pass 1 and reuse existing pass1_answers.json. Useful when "
        "only the scoring prompt or judge model changed.",
    )
    parser.add_argument(
        "--skip-pass2",
        action="store_true",
        help="Skip Pass 2. Useful when preparing answers "
        "for scoring with different backends.",
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
        help="Optional output path for the Pass^k summary JSON.",
    )
    parser.add_argument(
        "--passk-allow-missing",
        action="store_true",
        help="Score missing cases as 0 when Pass^k run outputs have different ids.",
    )
    args = parser.parse_args()
    if args.passk_runs < 1:
        parser.error("--passk-runs must be at least 1")

    backend = args.backend
    backend_pass2 = args.backend_pass2 or backend

    provider = provider_for_backend(backend, args.provider) if backend in API_BACKENDS else (args.provider or "anthropic")
    provider_pass2 = provider_for_backend(backend_pass2, args.provider_pass2) if backend_pass2 in API_BACKENDS else (args.provider_pass2 or provider)
    
    response_format = "json_object" if args.json else "text"

    if args.model_pass1 is None:
        args.model_pass1 = default_model_for_backend(backend, "evaluator")
    if args.model_pass2 is None:
        args.model_pass2 = default_model_for_backend(backend_pass2, "judge")

    if backend in API_BACKENDS and not check_api_key(provider) and not args.skip_pass1:
        print(
            f"{provider.upper()}_API_KEY is not set and no subscription backend was selected.",
            file=sys.stderr,
        )
        sys.exit(2)
    if backend_pass2 in API_BACKENDS and not check_api_key(provider_pass2) and not args.skip_pass2:
        print(
            f"{provider_pass2.upper()}_API_KEY is not set and no subscription backend was selected.",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.passk_runs > 1:
        sys.exit(
            run_passk_step(
                args.app_logs,
                args.test_cases,
                args.output,
                args.model_pass1,
                args.model_pass2,
                backend,
                backend_pass2,
                provider,
                provider_pass2,
                response_format,
                runs=args.passk_runs,
                passk_output=args.passk_output,
                allow_missing=args.passk_allow_missing,
                skip_pass1=args.skip_pass1,
                skip_pass2=args.skip_pass2,
                reasoning_pass1=args.reasoning_pass1,
                reasoning_pass2=args.reasoning_pass2,
            )
        )

    sys.exit(
        run_step(
            args.app_logs,
            args.test_cases,
            args.output,
            args.model_pass1,
            args.model_pass2,
            backend,
            backend_pass2,
            provider,
            provider_pass2,
            response_format,
            skip_pass1=args.skip_pass1,
            skip_pass2=args.skip_pass2,
            reasoning_pass1=args.reasoning_pass1,
            reasoning_pass2=args.reasoning_pass2,
        )
    )


if __name__ == "__main__":
    main()
