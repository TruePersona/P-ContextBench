"""Blind recovery must be aligned to every intended fact before acceptance."""

import unittest
from copy import deepcopy

from step4_app_log_synthesizer.evidence_alignment import (
    resume_alignment,
    seal_alignment,
    visible_fragment,
)
from step4_app_log_synthesizer.generator import _strict_resume_passed, cluster_passed


class FactAlignmentTests(unittest.TestCase):
    def test_public_fragment_allowlist_excludes_new_nested_annotations(self):
        fragment = {
            "fragment_id": "F1",
            "date": "2026-03-01",
            "new_answer_key": "SECRET",
            "messages": [
                {
                    "sender": "User",
                    "text": "A visible message.",
                    "private_hint": "SECRET",
                }
            ],
            "source": {"type": "contact", "name": "Lena", "fact_hint": "SECRET"},
            "calendar_event": {
                "title": "An event",
                "start_time": "09:00",
                "private_hint": "SECRET",
            },
        }
        public = visible_fragment(fragment)
        self.assertNotIn("SECRET", str(public))
        self.assertEqual(public["messages"][0]["text"], "A visible message.")
        self.assertEqual(public["calendar_event"]["start_time"], "09:00")

    def setUp(self):
        self.facts = [
            {
                "fact_id": "HF-1",
                "claim": "The roommate's records must remain private.",
                "ground_truth_label": "private roommate records",
            },
            {
                "fact_id": "HF-2",
                "claim": "The roommate is Lena.",
                "ground_truth_label": "roommate Lena",
            },
        ]
        self.fragments = [
            {
                "fragment_id": "F1",
                "messages": [
                    {"text": "Lena is my roommate. Keep her financial records private."}
                ],
            }
        ]
        self.blind = {
            "verdict": "RECOVERED",
            "candidate_facts": [
                {
                    "candidate_label": "Lena is the roommate and her financial records are private.",
                    "confidence": "HIGH",
                    "implicitness_check": {"fragments_that_leak_labels": []},
                }
            ],
        }
        self.review = {
            "fact_reviews": [
                {
                    "fact_id": f["fact_id"],
                    "verdict": "supported",
                    "candidate_indices": [0],
                    "evidence": [
                        {
                            "fragment_id": "F1",
                            "quote": self.fragments[0]["messages"][0]["text"],
                        }
                    ],
                    "rationale": "The recovered claim covers this fact.",
                }
                for f in self.facts
            ]
        }

    def test_unrelated_incomplete_recovery_no_longer_passes_strict_gate(self):
        self.blind["candidate_facts"][0]["candidate_label"] = (
            "Enjoys painting landscapes."
        )
        self.assertFalse(
            cluster_passed(
                self.blind, self.facts, policy="strict", fragments=self.fragments
            )[0]
        )

    def test_one_candidate_may_semantically_cover_multiple_facts(self):
        self.blind["fact_alignment"] = seal_alignment(
            self.review, self.facts, self.blind, self.fragments
        )
        passed, pairs = cluster_passed(
            self.blind, self.facts, policy="strict", fragments=self.fragments
        )
        self.assertTrue(passed)
        self.assertEqual({p["fact_id"] for p in pairs}, {"HF-1", "HF-2"})

    def test_missing_fact_fabricated_quote_or_candidate_fails(self):
        for mutate in (
            lambda r: r["fact_reviews"].pop(),
            lambda r: r["fact_reviews"][0].update(candidate_indices=[99]),
            lambda r: r["fact_reviews"][0]["evidence"][0].update(quote="invented"),
        ):
            r = deepcopy(self.review)
            mutate(r)
            with self.assertRaises(ValueError):
                seal_alignment(r, self.facts, self.blind, self.fragments)

    def test_unsupported_fact_blocks_cluster(self):
        self.review["fact_reviews"][1]["verdict"] = "unsupported"
        self.blind["fact_alignment"] = seal_alignment(
            self.review, self.facts, self.blind, self.fragments
        )
        self.assertFalse(
            cluster_passed(
                self.blind, self.facts, policy="strict", fragments=self.fragments
            )[0]
        )

    def test_changed_fact_blind_recovery_or_alignment_invalidates_review(self):
        self.blind["fact_alignment"] = seal_alignment(
            self.review, self.facts, self.blind, self.fragments
        )
        for target in ("fact", "blind", "review"):
            facts = deepcopy(self.facts)
            blind = deepcopy(self.blind)
            if target == "fact":
                facts[0]["claim"] = "Different claim"
            elif target == "blind":
                blind["candidate_facts"][0]["candidate_label"] = "Different recovery"
            else:
                blind["fact_alignment"]["fact_reviews"][0]["rationale"] = (
                    "Changed review"
                )
            self.assertFalse(
                cluster_passed(blind, facts, policy="strict", fragments=self.fragments)[
                    0
                ]
            )

    def test_current_fragments_required_and_bound_to_acceptance(self):
        self.blind["fact_alignment"] = seal_alignment(
            self.review, self.facts, self.blind, self.fragments
        )
        self.assertFalse(cluster_passed(self.blind, self.facts, policy="strict")[0])
        self.assertTrue(resume_alignment(self.blind, self.facts, self.fragments))
        self.assertFalse(resume_alignment(self.blind, self.facts, []))
        self.fragments[0]["messages"][0]["text"] = "Unrelated replacement."
        self.assertFalse(
            cluster_passed(
                self.blind, self.facts, policy="strict", fragments=self.fragments
            )[0]
        )
        self.assertFalse(resume_alignment(self.blind, self.facts, self.fragments))

    def test_resume_requires_the_full_gate_not_only_alignment(self):
        self.blind["candidate_facts"][0]["confidence"] = "LOW"
        self.blind["fact_alignment"] = seal_alignment(
            self.review, self.facts, self.blind, self.fragments
        )
        self.assertTrue(resume_alignment(self.blind, self.facts, self.fragments))
        self.assertFalse(_strict_resume_passed(self.blind, self.facts, self.fragments))

    def test_lenient_remains_explicitly_historical(self):
        self.assertTrue(cluster_passed(self.blind, self.facts, policy="lenient")[0])


if __name__ == "__main__":
    unittest.main()
