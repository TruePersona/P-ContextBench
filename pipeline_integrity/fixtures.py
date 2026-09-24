"""Synthetic fixtures for offline integrity tests; not benchmark reference data."""

from copy import deepcopy

from pipeline_integrity import admission
from pipeline_integrity.artifacts import read_json, write_json


def review(dataset, quote="coffee before work"):
    assessments = []
    evaluations = []
    for case in dataset["test_cases"]:
        typ = admission.normalize_type(case["type"])
        row = {"test_case_id": case["id"], "overall_verdict": "VERIFIED"}
        for criterion in admission.CRITERIA:
            applies = criterion in (*admission.CRITERIA[:2], "public_evidence_check")
            applies |= (
                criterion in (*admission.CRITERIA[2:4], "behavior_contract_check")
                and typ == admission.TYPES[4]
            )
            applies |= criterion == admission.CRITERIA[4] and typ == admission.TYPES[2]
            row[criterion] = {"verdict": "PASS" if applies else "NOT_APPLICABLE"}
        evaluations.append(row)
        assessments.append(
            {
                "test_case_id": case["id"],
                "answerability": "supported",
                "answer": quote,
                "supporting_quotes": [quote],
            }
        )
    return (
        {"evaluations": evaluations, "corrected_test_cases": {"coverage_deficit": []}},
        {"assessments": assessments},
    )


def seal_fixture(case_path, log_path):
    from step6_benchmark_runner.generator import strip_to_raw_logs

    dataset = read_json(case_path)
    logs = read_json(log_path)
    logs.setdefault(
        "hidden_facts", [{"fact_id": "HF-fixture", "ground_truth_label": "coffee before work"}]
    )
    for case in dataset["test_cases"]:
        case.setdefault("source_hidden_fact_ids", ["HF-fixture"])
        case.setdefault("ground_truth", "coffee before work")
    write_json(case_path, dataset)
    write_json(log_path, logs)
    verification, blind = review(dataset)
    admission.seal_cases(
        dataset, verification, logs, blind, strip_to_raw_logs(logs), min_cases=1, max_cases=55
    )
    write_json(
        case_path.with_name(
            case_path.name.replace("_test_cases.json", "_test_cases_verification.json")
        ),
        verification,
    )


def profile():
    return {
        "participant_id": "fixture-1",
        "name": "Alex Smith",
        "age": 30,
        "occupation": "Teacher",
        "location": "Example City",
        "preferences": {"routine": "Morning exercise"},
        "hidden_facts": [
            {
                "fact_id": "HF-1",
                "ground_truth_label": "Morning exercise routine",
                "claim": "Alex exercises in the morning.",
            }
        ],
    }


def interview():
    return {
        "transcript": [
            {
                "question_id": f"Q{i:02d}",
                "question_text": "Describe your routine.",
                "response": "I exercise before breakfast.",
            }
            for i in range(1, 110)
        ],
        "extracted_profile": profile(),
    }


def profile_review():
    return {"verification": {"overall_verdict": "PASS"}, "corrected_extracted_profile": profile()}


def circle_review():
    return {
        "verification": {"overall_verdict": "PASS"},
        "corrected_social_circle": {
            "social_circle": [{"name": f"Friend {i}", "relationship": "friend"} for i in range(5)]
        },
    }


def fragments():
    return [
        {
            "fragment_id": f"C1-F{i}",
            "fragment_type": "messenger_session",
            "date": f"2026-03-0{i}",
            "source": {"type": "contact", "name": "Friend 0"},
            "messages": [
                {
                    "time": "07:00",
                    "sender": "Alex Smith",
                    "text": "Finished my morning run before breakfast again.",
                }
            ],
            "supports_hidden_facts": [{"hidden_fact_id": "HF-1"}],
        }
        for i in (1, 2)
    ]


def cluster_review():
    return {
        "verdict": "RECOVERED",
        "candidate_facts": [
            {
                "candidate_label": "Morning exercise routine",
                "confidence": "HIGH",
                "supporting_fragments": ["C1-F1", "C1-F2"],
                "implicitness_check": {"fragments_that_leak_labels": []},
            }
        ],
    }


def alignment():
    return {
        "fact_reviews": [
            {
                "fact_id": "HF-1",
                "verdict": "supported",
                "candidate_indices": [0],
                "evidence": [
                    {
                        "fragment_id": "C1-F1",
                        "quote": "Finished my morning run before breakfast again.",
                    }
                ],
                "rationale": "The source supports the stated routine.",
            }
        ]
    }


def dataset():
    return {
        "test_cases": [
            {
                "id": "TC-1",
                "type": admission.TYPES[0],
                "question": "When does Alex run?",
                "ground_truth": "Morning exercise routine",
                "source_hidden_fact_ids": ["HF-1"],
            }
        ]
    }


def queued_pipeline_outputs():
    verification, blind = review(dataset(), "Finished my morning run before breakfast again.")
    return deepcopy(
        [
            interview(),
            profile_review(),
            circle_review()["corrected_social_circle"],
            circle_review(),
            {"clusters": [{"cluster_id": "C1", "hidden_fact_ids": ["HF-1"]}]},
            {"fragments": fragments()},
            cluster_review(),
            alignment(),
            dataset(),
            blind,
            verification,
            {"answers": [{"test_case_id": "TC-1", "answer": "Before breakfast in the morning."}]},
            {"evaluations": [{"test_case_id": "TC-1", "score": "CORRECT", "score_value": 1.0}]},
        ]
    )
