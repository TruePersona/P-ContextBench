"""Regression checks for complete histories and independent human references."""

import unittest
from copy import deepcopy

from type5_protocol.build_pilot import sources
from type5_protocol.full_history import local_timestamp, visible_history
from type5_protocol.human_validation import adjudicate, calibration_report, read_ratings
from type5_protocol.protocol import COMMON_CHECKS, fingerprint
from type5_protocol.review import (
    alignment_input,
    family_review_input,
    validate_family_review,
)
from type5_protocol.test_protocol import family


class HumanValidationTests(unittest.TestCase):
    def setUp(self):
        self.packet = [{"review_id": "A1"}, {"review_id": "A2"}]
        self.reviews = [self.submission("one", True), self.submission("two", False)]

    def submission(self, reviewer, verdict):
        return {
            "reviewer_kind": "human",
            "reviewer_id": reviewer,
            "packet_sha256": fingerprint(self.packet),
            "ratings": [
                {
                    "review_id": "A1",
                    "response_valid": verdict,
                    "reason": "Concrete decision assessment.",
                }
            ],
        }

    def test_disagreement_and_missing_remain_unresolved(self):
        result = adjudicate(self.packet, self.reviews, "answers")
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["unresolved"], 2)
        self.assertEqual(result["independently_comparable"], 1)

    def test_adjudication_binds_both_independent_reviews(self):
        decision = self.submission("adjudicator", True)
        decision["source_reviews_sha256"] = fingerprint(self.reviews)
        result = adjudicate(self.packet, self.reviews, "answers", decision)
        self.assertEqual(result["results"][0]["source"], "adjudicated")
        self.reviews[1]["ratings"][0]["reason"] = "Changed after adjudication"
        with self.assertRaisesRegex(ValueError, "bind"):
            adjudicate(self.packet, self.reviews, "answers", decision)

    def test_model_and_duplicate_reviewers_rejected(self):
        bad = deepcopy(self.reviews[0])
        bad["reviewer_kind"] = "model"
        with self.assertRaisesRegex(ValueError, "human"):
            read_ratings(self.packet, bad, "answers")
        with self.assertRaisesRegex(ValueError, "distinct"):
            adjudicate(self.packet, [self.reviews[0], self.reviews[0]], "answers")

    def test_ratings_cannot_cross_packets_or_repeat_items(self):
        with self.assertRaisesRegex(ValueError, "different packet"):
            read_ratings(
                self.packet + [{"review_id": "A3"}], self.reviews[0], "answers"
            )
        bad = deepcopy(self.reviews[0])
        bad["ratings"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            read_ratings(self.packet, bad, "answers")

    def test_calibration_excludes_invalid_cases_and_keeps_unresolved_visible(self):
        refs = {
            "results": [
                {"review_id": "A1", "reference": False},
                {"review_id": "A2", "reference": True},
            ]
        }
        mapping = [
            {"review_id": "A1", "episode_id": "E1"},
            {"review_id": "A2", "episode_id": "E2"},
        ]
        result = calibration_report(
            refs,
            mapping,
            {"E1": True, "E2": False},
            {"A1": True, "A2": True},
            {"E1": "P1", "E2": "P2"},
        )
        self.assertEqual(result["intended"], 2)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["false_acceptance"]["events"], 1)
        self.assertIsNone(result["false_acceptance"]["persona_bootstrap_95"])
        self.assertEqual(result["excluded_or_unresolved"][0]["reason"], "case_invalid")

    def test_case_approval_requires_independent_substance(self):
        bad = self.submission("one", True)
        bad["ratings"] = [
            {"review_id": "A1", "case_valid": True, "reason": "Looks fine"}
        ]
        with self.assertRaisesRegex(TypeError, "independent"):
            read_ratings(self.packet, bad, "cases")


class HistoryTests(unittest.TestCase):
    def test_full_history_keeps_messages_but_hides_private_classification(self):
        s = {
            "date": "2026-03-02",
            "contact": "Friend",
            "session_id": "SECRET",
            "messages": [
                {
                    "time": "12:00",
                    "sender": "User",
                    "text": "Visible A",
                    "hidden_fact": "SECRET",
                },
                {"time": "12:02", "sender": "Friend", "text": "Visible B"},
            ],
        }
        data = {
            "messenger": {"meaningful_sessions": [s], "filler_sessions": [deepcopy(s)]},
            "calendar": {
                "events": [
                    {
                        "date": "2026-03-03",
                        "start_time": "13:00",
                        "end_time": "14:00",
                        "title": "Visible event",
                        "hidden_fact": "SECRET",
                    }
                ]
            },
            "hidden_facts": ["SECRET"],
        }
        rows = visible_history(data, "America/New_York")
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), 3)
        self.assertNotIn("SECRET", str(rows))
        self.assertNotIn("meaningful", str(rows))
        self.assertIn("Visible B", rows[0]["text"])
        self.assertIn("T12:02:", rows[0]["timestamp"])
        self.assertIn("Visible event", rows[2]["text"])

    def test_dst_gaps_and_ambiguous_clocks_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, "nonexistent"):
            local_timestamp("2026-03-08", "02:30", "America/New_York")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            local_timestamp("2026-11-01", "01:30", "America/New_York")
        self.assertTrue(
            local_timestamp("2026-03-09", "02:30", "America/New_York").endswith(
                "-04:00"
            )
        )

    def test_large_family_compaction_is_lossless(self):
        group = family()
        shared = [
            dict(group[0]["logs"][0], id=f"H{i}", text=f"Background {i}")
            for i in range(101)
        ]
        for e in group:
            e["logs"] += deepcopy(shared)
        payload = family_review_input(group)
        for before, after in zip(group, payload["episodes"], strict=True):
            actual = {l["id"]: l for l in payload["shared_logs"] + after["logs"]}
            self.assertEqual({l["id"]: l for l in before["logs"]}, actual)

    def test_missing_subtype_is_explicit_and_exception_is_auditable(self):
        with self.assertRaisesRegex(ValueError, "no eligible"):
            sources(7)
        selected = sources(7, allow_rejected=True)["sources"][1]
        self.assertFalse(selected["original_case_eligible"])
        self.assertEqual(selected["source_case"]["id"], "TC-40")

    def test_malformed_family_review_can_be_repaired(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_family_review(None)

    def test_current_review_receives_the_complete_scoring_policy(self):
        group = family()
        payload = alignment_input(group[0], {"supported_claims": []}, "material-v3")
        self.assertEqual(payload["common_checks"], COMMON_CHECKS)
        self.assertEqual(
            family_review_input(group, "material-v3")["common_checks"], COMMON_CHECKS
        )
        self.assertNotIn("common_checks", alignment_input(group[0], {}, "material-v2"))


if __name__ == "__main__":
    unittest.main()
