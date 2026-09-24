"""Fail-closed validation of canonical stage outputs and complete case reviews."""

from copy import deepcopy

from pipeline_integrity.artifacts import digest

TYPES = (
    "type_1_simple_fact_check",
    "type_2_cross_log_fact_check",
    "type_3_dynamic_tracking",
    "type_4_reasoning",
    "type_5_agent_behavior",
)
CRITERIA = (
    "criterion_1_ground_truth_sourcing",
    "criterion_2_non_duplication",
    "criterion_3_type_5_risk_validity",
    "criterion_4_resolution_boundary_validity",
    "criterion_5_dynamic_preference_validity",
    "behavior_contract_check",
    "public_evidence_check",
)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def inventory(records, key, label):
    if not isinstance(records, list) or not records:
        raise ValueError(f"{label}: expected a nonempty list")
    result = {}
    for row in records:
        if not isinstance(row, dict) or not nonempty(row.get(key)) or row[key] in result:
            raise ValueError(f"{label}: malformed or duplicate {key}")
        result[row[key]] = row
    return result


def profile(bundle, *, participant_id=None):
    if bundle.get("verification", {}).get("overall_verdict") not in ("PASS", "PASS_WITH_REVISIONS"):
        raise ValueError("Profile verification did not pass")
    value = bundle.get("corrected_extracted_profile")
    if (
        not isinstance(value, dict)
        or not nonempty(value.get("participant_id"))
        or not nonempty(value.get("name"))
    ):
        raise ValueError("Missing canonical profile identity")
    if participant_id and value["participant_id"] != participant_id:
        raise ValueError("Profile identity differs from the seed")
    if not isinstance(value.get("preferences"), dict) or not value["preferences"]:
        raise ValueError("Missing profile preferences")
    facts = inventory(value.get("hidden_facts"), "fact_id", "hidden facts")
    if any(not nonempty(fact.get("ground_truth_label")) for fact in facts.values()):
        raise ValueError("Hidden facts require nonempty claims")
    return value


def interview(bundle, *, participant_id=None):
    transcript = inventory(bundle.get("transcript"), "question_id", "transcript")
    if len(transcript) != 109 or any(
        not nonempty(row.get("question_text")) or not nonempty(row.get("response"))
        for row in transcript.values()
    ):
        raise ValueError("Interview requires 109 complete question/response records")
    draft = bundle.get("extracted_profile")
    if not isinstance(draft, dict) or not draft:
        raise ValueError("Missing extracted profile")
    if participant_id and draft.get("participant_id") != participant_id:
        raise ValueError("Interview identity differs from the seed/profile")
    return bundle["transcript"]


def social_circle(bundle):
    if bundle.get("verification", {}).get("overall_verdict") not in ("PASS", "PASS_WITH_REVISIONS"):
        raise ValueError("Social circle verification did not pass")
    value = bundle.get("corrected_social_circle")
    if not isinstance(value, dict):
        raise ValueError("Missing corrected social circle")  # noqa: TRY004 - malformed serialized input is a validation error
    people = inventory(value.get("social_circle"), "name", "social circle")
    if len(people) != 5 or any(
        not nonempty(person.get("relationship")) for person in people.values()
    ):
        raise ValueError("Social circle requires five identified relationships")
    return value


def normalize_type(value):
    if isinstance(value, str) and value.startswith("5") and "_" in value:
        return TYPES[4]
    return value


def case_inventory(dataset):
    cases = inventory(dataset.get("test_cases"), "id", "test cases")
    for cid, case in cases.items():
        if normalize_type(case.get("type")) not in TYPES or not nonempty(case.get("question")):
            raise ValueError(f"{cid}: missing question or invalid type")
    return cases


def public_review(dataset, review, raw_logs):
    cases = case_inventory(dataset)
    rows = inventory(review.get("assessments"), "test_case_id", "public evidence review")
    if set(cases) != set(rows):
        raise ValueError("Public evidence review must cover every case exactly once")
    for cid, row in rows.items():
        if row.get("answerability") not in (
            "supported",
            "ambiguous",
            "unsupported",
        ) or not nonempty(row.get("answer")):
            raise ValueError(f"{cid}: invalid public evidence review")
        quotes = row.get("supporting_quotes")
        if not isinstance(quotes, list) or any(
            not nonempty(q) or q not in raw_logs for q in quotes
        ):
            raise ValueError(f"{cid}: public evidence quotes do not match the history")
        if row["answerability"] == "supported" and not quotes:
            raise ValueError(f"{cid}: supported answer requires source quotes")
    return rows


def seal_cases(
    dataset, verification, app_logs, blind_review, raw_logs, *, min_cases=45, max_cases=55
):
    cases = case_inventory(dataset)
    facts = inventory(app_logs.get("hidden_facts"), "fact_id", "source fact registry")
    for cid, case in cases.items():
        sources = case.get("source_hidden_fact_ids")
        if (
            not nonempty(case.get("ground_truth"))
            or not isinstance(sources, list)
            or not sources
            or any(not isinstance(source, str) or source not in facts for source in sources)
            or len(set(sources)) != len(sources)
        ):
            raise ValueError(f"{cid}: missing ground truth or unresolved/duplicate source fact IDs")
    blind = public_review(dataset, blind_review, raw_logs)
    rows = inventory(verification.get("evaluations"), "test_case_id", "case verification")
    if set(rows) != set(cases):
        raise ValueError("Independent verification must cover every exact case ID")
    accepted = []
    counts = {"verified": 0, "flagged": 0, "rejected": 0}
    for cid, case in cases.items():
        row = rows[cid]
        typ = normalize_type(case["type"])
        required = set(CRITERIA[:2]) | {"public_evidence_check"}
        if typ == TYPES[4]:
            required.update(CRITERIA[2:4])
            required.add("behavior_contract_check")
        if typ == TYPES[2]:
            required.add(CRITERIA[4])
        statuses = []
        for criterion in CRITERIA:
            check = row.get(criterion)
            status = check.get("verdict") if isinstance(check, dict) else None
            allowed = ("PASS", "WARN", "FAIL") if criterion in required else ("NOT_APPLICABLE",)
            if status not in allowed:
                raise ValueError(f"{cid}: missing or invalid {criterion}")
            statuses.append(status)
        if (
            blind[cid]["answerability"] != "supported"
            and row["public_evidence_check"]["verdict"] != "FAIL"
        ):
            raise ValueError(f"{cid}: unresolved public answerability cannot be admitted")
        verdict = (
            "REJECTED" if "FAIL" in statuses else "FLAGGED" if "WARN" in statuses else "VERIFIED"
        )
        if row.get("overall_verdict") != verdict:
            raise ValueError(f"{cid}: overall verdict disagrees with criterion verdicts")
        counts[{"REJECTED": "rejected", "FLAGGED": "flagged", "VERIFIED": "verified"}[verdict]] += 1
        if verdict != "REJECTED":
            accepted.append(deepcopy(case))
        row["case_sha256"] = digest(case)
    corrected = verification.get("corrected_test_cases")
    if not isinstance(corrected, dict) or not isinstance(corrected.get("coverage_deficit"), list):
        raise ValueError("Missing explicit coverage review")  # noqa: TRY004 - malformed serialized input is a validation error
    deficits = deepcopy(corrected["coverage_deficit"])
    if not min_cases <= len(accepted) <= max_cases:
        deficits.append(f"Expected {min_cases}..{max_cases} admitted cases; got {len(accepted)}")
    if min_cases >= 4:
        present = {normalize_type(case["type"]) for case in accepted}
        for typ in TYPES[:4]:
            if typ not in present:
                deficits.append(f"Missing case type: {typ}")
    verification["corrected_test_cases"] = {
        "metadata": deepcopy(dataset.get("metadata", {})),
        "test_cases": accepted,
        "coverage_deficit": deficits,
    }
    verification.setdefault("verification_metadata", {})["summary"] = counts
    verification["public_review"] = deepcopy(blind_review)
    binding = {
        "schema": "case-admission-v1",
        "dataset_sha256": digest(dataset),
        "scope": "smoke_test" if min_cases < 45 or max_cases < 45 else "benchmark_candidate",
        "app_logs_sha256": digest(app_logs),
        "public_history_sha256": digest(raw_logs),
        "case_sha256": {cid: digest(case) for cid, case in cases.items()},
        "admitted_ids": [case["id"] for case in accepted],
        "complete": counts["rejected"] == 0 and not deficits,
        "coverage": {"min_cases": min_cases, "max_cases": max_cases},
    }
    binding["review_sha256"] = digest({k: v for k, v in verification.items() if k != "admission"})
    verification["admission"] = binding
    return binding


def admitted_cases(dataset, verification, app_logs, raw_logs):
    saved = verification.get("admission")
    if not isinstance(saved, dict) or not saved.get("complete"):
        raise ValueError("Cases lack complete bound admission; re-review before benchmarking")
    rebuilt = deepcopy(verification)
    coverage = saved.get("coverage", {})
    actual = seal_cases(
        dataset,
        rebuilt,
        app_logs,
        verification.get("public_review", {}),
        raw_logs,
        min_cases=coverage.get("min_cases", 45),
        max_cases=coverage.get("max_cases", 55),
    )
    if actual != saved:
        raise ValueError("Case admission differs from current cases, history, or review")
    return deepcopy(rebuilt["corrected_test_cases"])
