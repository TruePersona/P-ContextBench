from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .decoys import resolve_verified_decoy_pool, _selectable_messenger_count
except ImportError:
    from decoys import resolve_verified_decoy_pool, _selectable_messenger_count


def _messenger_decoy(decoy_id: str, text: str) -> dict:
    return {
        "decoy_id": decoy_id,
        "type": "messenger",
        "contact_policy": "flexible",
        "preferred_contact": None,
        "placement_hint": "separate_filler_session",
        "decoy_type": "one_off",
        "overlap_check": "none",
        "difficulty": "hard",
        "messages": [
            {"sender": "contact", "text": text},
            {"sender": "persona", "text": "I can check that once."},
        ],
    }


def _calendar_decoy(decoy_id: str) -> dict:
    return {
        "decoy_id": decoy_id,
        "type": "calendar",
        "contact_policy": "flexible",
        "preferred_contact": None,
        "placement_hint": "separate_filler_session",
        "decoy_type": "one_off",
        "overlap_check": "none",
        "difficulty": "easy",
        "calendar_event": {
            "title": f"One-time calendar decoy {decoy_id}",
            "location": "front desk",
            "participants": [],
            "notes": "Temporary errand.",
        },
    }


class ResolveVerifiedDecoyPoolTests(unittest.TestCase):
    def test_resume_extends_mixed_pool_until_pool_size_is_messenger_selectable(self) -> None:
        existing = [
            _messenger_decoy(f"M-{idx:03d}", f"existing messenger decoy {idx}")
            for idx in range(50)
        ] + [
            _calendar_decoy(f"C-{idx:03d}")
            for idx in range(150)
        ]

        calls = {"count": 0}

        def fake_model(_: str) -> str:
            calls["count"] += 1
            batch = [
                _messenger_decoy(
                    f"B-{calls['count']:03d}-{idx:03d}",
                    f"new messenger decoy {calls['count']} {idx}",
                )
                for idx in range(50)
            ]
            return json.dumps({"decoys": batch})

        prompt = (
            "{{PERSONA_NAME}} {{PERSONA_AGE}} {{PERSONA_OCCUPATION}} "
            "{{PERSONA_LOCATION}} {{INSERT_HIDDEN_FACTS_JSON_HERE}} "
            "{{INSERT_CORRECTED_SOCIAL_CIRCLE_JSON_HERE}} {{LOG_START_DATE}} "
            "{{LOG_END_DATE}} {{TARGET_DECOY_COUNT}} "
            "{{INSERT_CONTACT_USAGE_COUNTS_JSON_HERE}}"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            decoys_out = Path(tmp_dir) / "verified_decoys.json"
            decoys_out.write_text(json.dumps(existing), encoding="utf-8")

            decoys = resolve_verified_decoy_pool(
                fake_model,
                prompt,
                json.loads,
                {
                    "name": "Test Person",
                    "age": 70,
                    "occupation": "retired",
                    "location": "Michigan",
                },
                [],
                {"members": []},
                "2026-03-01",
                "2026-03-31",
                {},
                [],
                decoys_out,
                decoy_count=50,
                decoy_pool_size=200,
                resume=True,
            )

        self.assertGreater(calls["count"], 0)
        self.assertGreaterEqual(_selectable_messenger_count(decoys), 200)
        self.assertTrue(all(decoy.get("type") == "messenger" for decoy in decoys))


if __name__ == "__main__":
    unittest.main()
