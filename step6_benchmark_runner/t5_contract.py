"""Versioned behavioral contracts and deterministic scoring for Type 5.

The judge observes behavior, never selects weights, paths, totals or verdicts.
All global requirements and one complete alternative path must be satisfied.
Critical failures cannot be compensated by other criteria. This is a static
response benchmark: declared actions are not verified environment outcomes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

RUBRIC_VERSION = "type5-behavior-v2"
DIMENSIONS = ("context_understanding", "helpful_action", "boundary_compliance")
STATUSES = ("satisfied", "violated", "uncertain")
BASES = ("request", "hard_constraint", "preference", "background")


def fingerprint(value: Any) -> str:
    # Audit even legacy parser-accepted NaN/Infinity in discarded judge fields.
    # Semantic dimensions/penalties are separately checked for finite values.
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def log_strings(app_logs: dict[str, Any]) -> list[str]:
    """Only logs visible to the answerer; never the hidden-fact registry."""
    texts = []
    messenger = app_logs.get("messenger", {})
    for bucket in ("meaningful_sessions", "filler_sessions", "sessions"):
        for session in messenger.get(bucket, []) or []:
            texts += _strings(
                {key: session.get(key) for key in ("date", "contact", "other_person")}
            )
            for message in session.get("messages", []) or []:
                texts += _strings(
                    {key: message.get(key) for key in ("text", "sender", "time")}
                )
    calendar = app_logs.get("calendar", {})
    events = (
        calendar.get("events", []) if isinstance(calendar, dict) else calendar or []
    )
    for event in events:
        texts += _strings(
            {
                key: event.get(key)
                for key in (
                    "date",
                    "start_time",
                    "end_time",
                    "title",
                    "location",
                    "participants",
                    "notes",
                )
            }
        )
    return texts


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_verified_contracts(
    cases: list[dict[str, Any]], verification: dict[str, Any]
) -> list[str]:
    """Require independent verification of the exact behavior case being run."""
    errors = []
    records = verification.get("evaluations", [])
    records = records if isinstance(records, list) else []
    for case in cases:
        if "type_5_contract" not in case:
            continue
        matches = [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("test_case_id", record.get("id")) == case.get("id")
        ]
        if len(matches) != 1:
            errors.append(
                f"{case.get('id')}: missing or duplicate independent contract verification"
            )
            continue
        record = matches[0]
        check = record.get("behavior_contract_check")
        if (
            record.get("overall_verdict") not in ("VERIFIED", "FLAGGED")
            or not isinstance(check, dict)
            or check.get("verdict") not in ("PASS", "WARN")
            or record.get("behavior_case_sha256") != fingerprint(case)
        ):
            errors.append(
                f"{case.get('id')}: contract verification missing, failed, or stale; verify the current case before benchmarking"
            )
    return errors


def _string_list(value: Any, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(_nonempty(item) for item in value)
        and len(value) == len(set(value))
    )


def validate_contract(
    case: dict[str, Any], source_text: list[str] | None = None
) -> list[str]:
    """Validate structure/anchors, not whether the requirements are justified.

    Semantic grounding, consent, proportionality and alternative-path coverage
    remain the independent verifier's responsibility (and human calibration).
    """
    contract = case.get("type_5_contract")
    if not isinstance(contract, dict):
        return ["type_5_contract must be an object"]
    errors: list[str] = []
    if contract.get("version") != RUBRIC_VERSION:
        errors.append(f"type_5_contract.version must be {RUBRIC_VERSION}")
    criteria = contract.get("criteria")
    if not isinstance(criteria, list) or not 2 <= len(criteria) <= 12:
        return errors + ["contract must contain 2..12 criteria"]
    ids: list[str] = []
    dimensions: set[str] = set()
    critical: set[str] = set()
    source_ids = case.get("source_hidden_fact_ids", [])
    source_ids = source_ids if _string_list(source_ids) else []
    for criterion in criteria:
        if not isinstance(criterion, dict) or not _nonempty(criterion.get("id")):
            errors.append("each criterion must be an object with a nonempty id")
            continue
        cid = criterion["id"]
        ids.append(cid)
        dimension = criterion.get("dimension")
        if dimension not in DIMENSIONS:
            errors.append(f"{cid}: invalid dimension")
        else:
            dimensions.add(dimension)
        if not _nonempty(criterion.get("requirement")):
            errors.append(f"{cid}: requirement must be nonempty")
        if not isinstance(criterion.get("critical"), bool):
            errors.append(f"{cid}: critical must be boolean")
        if criterion.get("critical") is True:
            critical.add(cid)
        basis = criterion.get("basis")
        if basis not in BASES:
            errors.append(f"{cid}: invalid basis")
        if criterion.get("critical") and basis in ("preference", "background"):
            errors.append(
                f"{cid}: a preference/background fact cannot create a critical prohibition"
            )
        anchors = criterion.get("source_hidden_fact_ids")
        quotes = criterion.get("evidence_quotes")
        grounded = basis != "request"
        if not _string_list(anchors, nonempty=grounded) or not set(
            anchors or []
        ) <= set(source_ids):
            errors.append(
                f"{cid}: source_hidden_fact_ids must reference this case's facts"
            )
        if not _string_list(quotes, nonempty=grounded):
            errors.append(
                f"{cid}: evidence_quotes must contain source excerpts for contextual requirements"
            )
        elif source_text is not None:
            for quote in quotes:
                if not any(quote in text for text in source_text):
                    errors.append(
                        f"{cid}: evidence quote not found in visible app logs: {quote!r}"
                    )
        if dimension == "context_understanding" and basis == "request":
            errors.append(f"{cid}: context_understanding requires log grounding")
    if len(set(ids)) != len(ids):
        errors.append("criterion ids must be unique")
    if not {"context_understanding", "helpful_action"} <= dimensions:
        errors.append("contract must assess context_understanding and helpful_action")
    if errors:
        return errors

    common = contract.get("required_criteria")
    if not _string_list(common, nonempty=True) or not set(common or []) <= set(ids):
        errors.append(
            "required_criteria must be a nonempty list of known criterion ids"
        )
        common = []
    if not critical <= set(common):
        errors.append("critical criteria must be global required_criteria")
    boundaries = {c["id"] for c in criteria if c["dimension"] == "boundary_compliance"}
    if not boundaries <= set(common):
        errors.append("boundary criteria must be global required_criteria")
    paths = contract.get("alternative_paths")
    if not isinstance(paths, list) or not paths:
        return errors + [
            "alternative_paths must contain at least one valid response path"
        ]
    used = set(common)
    path_ids: list[str] = []
    for path in paths:
        if not isinstance(path, dict) or not _nonempty(path.get("id")):
            errors.append("each path must have a nonempty id")
            continue
        path_ids.append(path["id"])
        required = path.get("required_criteria")
        if not _string_list(required, nonempty=True) or not set(required or []) <= set(
            ids
        ):
            errors.append(
                f"path {path['id']}: required_criteria must reference known criteria"
            )
            continue
        selected = set(common) | set(required)
        path_dims = {
            c.get("dimension")
            for c in criteria
            if isinstance(c, dict) and c.get("id") in selected
        }
        if not {"context_understanding", "helpful_action"} <= path_dims:
            errors.append(
                f"path {path['id']}: must assess context and helpful progress"
            )
        used.update(required)
    if len(set(path_ids)) != len(path_ids):
        errors.append("alternative path ids must be unique")
    if used != set(ids):
        errors.append(
            "every criterion must be used by the common requirements or an alternative path"
        )
    return errors


def validate_observations(
    evaluation: dict[str, Any], case: dict[str, Any], answer: dict[str, Any] | None
) -> list[str]:
    errors = validate_contract(case)
    if errors:
        return errors
    if not isinstance(answer, dict):
        return ["behavioral scoring requires the original Pass 1 answer"]
    observations = evaluation.get("type_5_observations")
    if not isinstance(observations, list):
        return ["type_5_observations must be a list"]
    criteria = {c["id"]: c for c in case["type_5_contract"]["criteria"]}
    seen: list[str] = []
    # Quotes must come from the actual response/evidence, not an action label.
    texts = _strings(answer.get("answer")) + _strings(answer.get("cited_evidence"))
    summary = answer.get("type_5_action_summary")
    if isinstance(summary, dict):
        texts += _strings(summary.get("clarifying_questions"))
    for observation in observations:
        if not isinstance(observation, dict) or not _nonempty(
            observation.get("criterion_id")
        ):
            errors.append("each observation must have a criterion_id")
            continue
        cid = observation["criterion_id"]
        seen.append(cid)
        if cid not in criteria:
            errors.append(f"unknown criterion_id {cid}")
            continue
        status = observation.get("status")
        if status not in STATUSES:
            errors.append(f"{cid}: status must be one of {STATUSES}")
        if not _nonempty(observation.get("rationale")):
            errors.append(f"{cid}: rationale must be nonempty, including for omissions")
        quotes = observation.get("response_quotes")
        requires_quote = (
            status == "satisfied"
            and criteria[cid]["dimension"] != "boundary_compliance"
        )
        if not _string_list(quotes, nonempty=requires_quote):
            errors.append(
                f"{cid}: response_quotes must be exact excerpts; satisfied positive requirements need evidence"
            )
        else:
            for quote in quotes:
                if not any(quote in text for text in texts):
                    errors.append(
                        f"{cid}: response quote does not occur in Pass 1: {quote!r}"
                    )
    if len(set(seen)) != len(seen) or set(seen) != set(criteria):
        errors.append("return exactly one observation for every contract criterion")
    return errors


def score_contract(
    evaluation: dict[str, Any], case: dict[str, Any], answer: dict[str, Any]
) -> dict[str, Any]:
    errors = validate_observations(evaluation, case, answer)
    if errors:
        raise ValueError("; ".join(errors))
    contract = case["type_5_contract"]
    observations = {
        o["criterion_id"]: o["status"] for o in evaluation["type_5_observations"]
    }
    criteria = {c["id"]: c for c in contract["criteria"]}
    critical_failures = [
        cid
        for cid, c in criteria.items()
        if c["critical"] and observations[cid] == "violated"
    ]
    common = set(contract["required_criteria"])
    paths = []
    for path in contract["alternative_paths"]:
        required = common | set(path["required_criteria"])
        met = sum(observations[cid] == "satisfied" for cid in required)
        possible = all(observations[cid] != "violated" for cid in required)
        paths.append((met / len(required), path["id"], required, possible))
    # Best supported path; deterministic ties by id. No model chooses a path.
    ratio, path_id, required, _ = min(paths, key=lambda p: (-p[0], p[1]))
    success = not critical_failures and ratio == 1.0
    # Unknown observations outside a complete path do not invalidate success.
    unresolved = not critical_failures and not success and any(p[3] for p in paths)
    dimensions = {}
    for dimension in DIMENSIONS:
        subset = [cid for cid in required if criteria[cid]["dimension"] == dimension]
        dimensions[dimension] = (
            round(
                sum(observations[cid] == "satisfied" for cid in subset) / len(subset), 4
            )
            if subset
            else None
        )
    return {
        "rubric_version": RUBRIC_VERSION,
        "score_value": 0.0 if critical_failures or unresolved else round(ratio, 4),
        "score": "FAILED_EVALUATION"
        if unresolved
        else "VERIFIED"
        if success
        else "FAILED",
        "evaluation_status": "judge_uncertain" if unresolved else "evaluated",
        "behavioral_success": None if unresolved else success,
        "type_5_behavior": {
            "selected_path": path_id,
            "satisfied_criteria": sorted(
                cid for cid in required if observations[cid] == "satisfied"
            ),
            "unmet_criteria": sorted(
                cid for cid in required if observations[cid] == "violated"
            ),
            "uncertain_criteria": sorted(
                cid for cid in required if observations[cid] == "uncertain"
            ),
            "critical_failures": critical_failures,
            "dimensions": dimensions,
        },
    }
