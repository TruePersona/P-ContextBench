from __future__ import annotations

import unittest

try:
    from .decoy_safety import validate_decoy_safety
    from .decoys import normalize_verified_decoys
except ImportError:
    from decoy_safety import validate_decoy_safety
    from decoys import normalize_verified_decoys


PERSONA_NAME = "Alicia Gonzalez"
SOCIAL_CIRCLE = {
    "members": [
        {"name": "Marisol Gonzalez", "relationship": "mom"},
        {"name": "Jordan Lee", "relationship": "coworker"},
    ]
}
HIDDEN_FACTS = [
    {
        "fact_id": "HF-001",
        "claim": "Alicia uses allergy refill reminders.",
        "ground_truth_label": "allergy refill routine",
    }
]


def _messenger(sender: str, text: str, overlap_check: str = "none") -> dict:
    return {
        "decoy_id": "D-001",
        "type": "messenger",
        "overlap_check": overlap_check,
        "messages": [{"sender": sender, "text": text}],
    }


def _calendar(title: str, notes: str, overlap_check: str = "none") -> dict:
    return {
        "decoy_id": "D-001",
        "type": "calendar",
        "overlap_check": overlap_check,
        "calendar_event": {
            "title": title,
            "location": "front desk",
            "participants": [],
            "notes": notes,
        },
    }


class DecoySafetyTests(unittest.TestCase):
    def test_contact_your_overlap_is_persona_owned_and_rejected(self) -> None:
        decoy = _messenger(
            "contact",
            "Did you pick up your allergy refill?",
            "safe_other_person_owned",
        )

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.owner, "persona")
        self.assertEqual(result.overlapping_hidden_fact_ids, ["HF-001"])

    def test_contact_my_overlap_is_other_owned_and_allowed(self) -> None:
        decoy = _messenger(
            "contact",
            "I picked up my allergy refill before lunch.",
            "safe_other_person_owned",
        )

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.verdict, "safe_other_person_owned")
        self.assertEqual(result.owner, "other_person")

    def test_persona_my_overlap_is_rejected(self) -> None:
        decoy = _messenger(
            PERSONA_NAME,
            "I picked up my allergy refill before lunch.",
            "safe_other_person_owned",
        )

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.owner, "persona")

    def test_persona_mom_overlap_is_other_owned_and_allowed(self) -> None:
        decoy = _messenger(
            PERSONA_NAME,
            "Mom asked me to check her allergy refill receipt.",
            "safe_other_person_owned",
        )

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.owner, "other_person")
        self.assertEqual(result.overlapping_hidden_fact_ids, ["HF-001"])

    def test_ambiguous_overlap_is_rejected(self) -> None:
        decoy = _messenger(
            "contact",
            "The allergy refill is ready at the counter.",
            "safe_other_person_owned",
        )

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.owner, "ambiguous")

    def test_no_overlap_is_allowed(self) -> None:
        decoy = _messenger("contact", "The borrowed stapler is downstairs.")

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.verdict, "none")
        self.assertEqual(result.overlapping_hidden_fact_ids, [])

    def test_calendar_mom_overlap_is_other_owned_and_allowed(self) -> None:
        decoy = _calendar(
            "Mom allergy refill receipt",
            "One-time scan cleanup for her clinic upload.",
            "safe_other_person_owned",
        )

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.owner, "other_person")

    def test_calendar_ambiguous_overlap_is_rejected(self) -> None:
        decoy = _calendar(
            "Allergy refill receipt",
            "One-time scan cleanup for clinic upload.",
            "safe_other_person_owned",
        )

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.owner, "ambiguous")

    def test_unsafe_overlap_label_is_rejected(self) -> None:
        decoy = _messenger("contact", "The borrowed stapler is downstairs.")
        decoy["overlap_check"] = "unsafe_overlap"

        result = validate_decoy_safety(
            decoy, HIDDEN_FACTS, PERSONA_NAME, SOCIAL_CIRCLE
        )

        self.assertFalse(result.passed)

    def test_normalize_keeps_safe_other_overlap_with_audit_fields(self) -> None:
        decoy = _messenger(
            "contact",
            "I picked up my allergy refill before lunch.",
            "safe_other_person_owned",
        )

        normalized = normalize_verified_decoys(
            [decoy], PERSONA_NAME, HIDDEN_FACTS, SOCIAL_CIRCLE
        )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["overlap_check"], "safe_other_person_owned")
        self.assertEqual(normalized[0]["overlapping_hidden_fact_ids"], ["HF-001"])
        self.assertTrue(normalized[0]["safety_reasons"])

    def test_normalize_does_not_trust_why_safe_for_ambiguous_overlap(self) -> None:
        decoy = _messenger(
            "contact",
            "The allergy refill is ready at the counter.",
            "safe_other_person_owned",
        )
        decoy["why_safe"] = "This belongs to someone else."

        normalized = normalize_verified_decoys(
            [decoy], PERSONA_NAME, HIDDEN_FACTS, SOCIAL_CIRCLE
        )

        self.assertEqual(normalized, [])


if __name__ == "__main__":
    unittest.main()
