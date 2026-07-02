from __future__ import annotations

import unittest

try:
    from .overlap import jaccard, find_overlap_violations, coverage_gap, build_report
except ImportError:
    from overlap import jaccard, find_overlap_violations, coverage_gap, build_report


def _case(cid, ctype, fact_ids):
    return {"id": cid, "type": ctype, "source_hidden_fact_ids": list(fact_ids)}


class JaccardTests(unittest.TestCase):
    def test_identical_sets_are_one(self):
        self.assertEqual(jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint_sets_are_zero(self):
        self.assertEqual(jaccard({"a"}, {"b"}), 0.0)

    def test_three_of_four_shared_is_point_six(self):
        self.assertAlmostEqual(
            jaccard({"18", "22", "79", "95"}, {"17", "22", "79", "95"}), 0.6
        )


class FindOverlapViolationsTests(unittest.TestCase):
    def test_same_type_over_50_percent_is_flagged(self):
        cases = [
            _case(
                "TC-042", "type_4_reasoning", ["HF-018", "HF-022", "HF-079", "HF-095"]
            ),
            _case(
                "TC-052", "type_4_reasoning", ["HF-017", "HF-022", "HF-079", "HF-095"]
            ),
        ]
        viols = find_overlap_violations(cases)
        pairs = {tuple(sorted(v["pair"])) for v in viols}
        self.assertIn(("TC-042", "TC-052"), pairs)

    def test_cross_type_at_60_percent_is_allowed(self):
        cases = [
            _case(
                "TC-042", "type_4_reasoning", ["HF-018", "HF-022", "HF-079", "HF-095"]
            ),
            _case(
                "TC-090",
                "type_5_agent_behavior",
                ["HF-017", "HF-022", "HF-079", "HF-095"],
            ),
        ]
        self.assertEqual(find_overlap_violations(cases), [])

    def test_cross_type_over_75_percent_is_flagged(self):
        cases = [
            _case(
                "TC-01", "type_1_simple_fact_check", ["HF-1", "HF-2", "HF-3", "HF-4"]
            ),
            _case("TC-02", "type_5_agent_behavior", ["HF-1", "HF-2", "HF-3", "HF-4"]),
        ]
        pairs = {tuple(sorted(v["pair"])) for v in find_overlap_violations(cases)}
        self.assertIn(("TC-01", "TC-02"), pairs)

    def test_distinct_cases_are_not_flagged(self):
        cases = [
            _case("TC-01", "type_4_reasoning", ["HF-1", "HF-2"]),
            _case("TC-02", "type_4_reasoning", ["HF-3", "HF-4"]),
        ]
        self.assertEqual(find_overlap_violations(cases), [])


class CoverageGapTests(unittest.TestCase):
    def test_returns_facts_no_case_references(self):
        cases = [_case("TC-01", "type_1_simple_fact_check", ["HF-1"])]
        hidden_facts = [
            {"fact_id": "HF-1"},
            {"fact_id": "HF-2"},
            {"fact_id": "HF-3"},
        ]
        self.assertEqual(set(coverage_gap(cases, hidden_facts)), {"HF-2", "HF-3"})

    def test_duplicate_facts_collapse_to_canonical(self):
        cases = [_case("TC-01", "type_1_simple_fact_check", ["HF-1"])]
        hidden_facts = [
            {"fact_id": "HF-1"},
            {"fact_id": "HF-2", "duplicate_of": "HF-1"},
        ]
        self.assertEqual(coverage_gap(cases, hidden_facts), [])


class BuildReportTests(unittest.TestCase):
    def test_report_summarizes_violations_and_coverage(self):
        cases = [
            _case("TC-01", "type_4_reasoning", ["HF-1", "HF-2", "HF-3", "HF-4"]),
            _case("TC-02", "type_4_reasoning", ["HF-1", "HF-2", "HF-3", "HF-5"]),
        ]
        hidden_facts = [{"fact_id": f"HF-{i}"} for i in range(1, 7)]
        report = build_report("ada_lovelace", cases, hidden_facts)

        self.assertEqual(report["persona"], "ada_lovelace")
        self.assertEqual(report["total_cases"], 2)
        self.assertEqual(report["violation_pairs"], 1)
        self.assertEqual(report["total_facts"], 6)
        self.assertEqual(report["covered_facts"], 5)
        self.assertEqual(report["untested_facts"], ["HF-6"])
        self.assertEqual(report["coverage_pct"], round(100 * 5 / 6))


if __name__ == "__main__":
    unittest.main()
