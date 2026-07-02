from __future__ import annotations

from itertools import combinations
from typing import Any


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _base_type(case: dict[str, Any]) -> str:
    return "_".join((case.get("type") or "").split("_")[:2])


def find_overlap_violations(
    cases: list[dict[str, Any]],
    any_type_threshold: float = 0.75,
    same_type_threshold: float = 0.50,
) -> list[dict[str, Any]]:
    fact_sets = {c["id"]: set(c.get("source_hidden_fact_ids") or []) for c in cases}
    types = {c["id"]: _base_type(c) for c in cases}
    violations: list[dict[str, Any]] = []
    for a, b in combinations(cases, 2):
        ia, ib = a["id"], b["id"]
        j = jaccard(fact_sets[ia], fact_sets[ib])
        same_type = types[ia] == types[ib]
        if j > any_type_threshold or (same_type and j > same_type_threshold):
            violations.append(
                {"pair": [ia, ib], "overlap": round(j * 100), "same_type": same_type}
            )
    return violations


def _canonical_fact_ids(hidden_facts: list[dict[str, Any]]) -> set[str]:
    return {h["fact_id"] for h in hidden_facts if not h.get("duplicate_of")}


def coverage_gap(
    cases: list[dict[str, Any]], hidden_facts: list[dict[str, Any]]
) -> list[str]:
    covered: set[str] = set()
    for c in cases:
        covered |= set(c.get("source_hidden_fact_ids") or [])
    return sorted(_canonical_fact_ids(hidden_facts) - covered)


def build_report(
    persona: str, cases: list[dict[str, Any]], hidden_facts: list[dict[str, Any]]
) -> dict[str, Any]:
    violations = find_overlap_violations(cases)
    untested = coverage_gap(cases, hidden_facts)
    total_facts = len(_canonical_fact_ids(hidden_facts))
    covered = total_facts - len(untested)
    flagged_ids = {cid for v in violations for cid in v["pair"]}
    return {
        "persona": persona,
        "total_cases": len(cases),
        "violation_pairs": len(violations),
        "overlapping_cases": len(flagged_ids),
        "violations": violations,
        "total_facts": total_facts,
        "covered_facts": covered,
        "untested_facts": untested,
        "coverage_pct": round(100 * covered / total_facts) if total_facts else 0,
    }
