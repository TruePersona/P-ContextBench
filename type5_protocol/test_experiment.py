"""Run isolation, review provenance, and diagnostic scoring regressions."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from type5_protocol.backend import infer
from type5_protocol.curated_pilot import build
from type5_protocol.experiment import (
    JUDGE_PROMPT,
    dataset,
    ensure_reviewed,
    freeze_payload,
    no_history_contract,
    packet,
    summary,
)
from type5_protocol.protocol import (
    COMMON_CHECKS,
    fingerprint,
    public_episode,
    validate_episode,
    validate_families,
)
from type5_protocol.review import ALIGN, BLIND, FAMILY, validate_blind
from type5_protocol.test_protocol import family, result


class RunIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.data = {"episodes": family()}
        self.write("pilot.json", self.data)
        self.args = Namespace(
            workdir=str(self.work),
            run="test",
            split="development",
            condition="full",
            answer_model="answerer",
            answer_backend="claude",
            judge_model="judge",
            judge_backend="codex",
            allow_unreviewed=False,
            stage="answer",
        )

    def write(self, name, data):
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_case_packet_cannot_overwrite_a_reviewed_public_episode(self):
        packet(self.data["episodes"], self.args)
        path = self.work / "human_review/development/blind_cases.json"
        original = path.read_text()
        self.data["episodes"][0]["request"] = "Change the call."
        with self.assertRaisesRegex(ValueError, "review packet changed"):
            packet(self.data["episodes"], self.args)
        self.assertEqual(path.read_text(), original)

    def approve(self):
        group = self.data["episodes"]
        for e in group[:2]:
            public = public_episode(e)
            blind = {
                "supported_claims": [
                    {
                        "id": "B1",
                        "claim": e["contract"]["claims"][0]["claim"],
                        "evidence": e["contract"]["claims"][0]["evidence"],
                    }
                ],
                "material_unknowns": [],
                "acceptable_behaviors": ["Pick the available slot."],
                "unjustified_interventions": [],
                "unresolved_case_ambiguities": [],
            }
            alignment = {
                "claim_reviews": [
                    {
                        "id": "C1",
                        "verdict": "supported",
                        "blind_claim_ids": ["B1"],
                        "rationale": "Direct calendar evidence.",
                    }
                ],
                "obligation_reviews": [
                    {
                        "id": o["id"],
                        "verdict": "supported",
                        "rationale": "Task and calendar justify it.",
                    }
                    for o in e["contract"]["obligations"]
                ],
                "excluded_valid_alternatives": [],
                "case_issues": [],
            }
            self.write(
                "review_calls/" + e["id"] + "-blind.json",
                {
                    "prompt": BLIND + json.dumps(public, ensure_ascii=False),
                    "response": blind,
                },
            )
            payload = {
                "public_episode": public,
                "frozen_blind_interpretation": blind,
                "proposed_contract": e["contract"],
            }
            self.write(
                "review_calls/" + e["id"] + "-align.json",
                {
                    "prompt": ALIGN + json.dumps(payload, ensure_ascii=False),
                    "response": alignment,
                },
            )
            self.write(
                "reviews/" + e["id"] + ".json",
                {
                    "episode_sha256": fingerprint(e),
                    "accepted": True,
                    "blind": blind,
                    "alignment": alignment,
                    "blind_call": e["id"] + "-blind",
                    "alignment_call": e["id"] + "-align",
                },
            )
        self.write(
            "review_calls/family.json",
            {
                "prompt": FAMILY + json.dumps(group, ensure_ascii=False),
                "response": {
                    "verdict": "pass",
                    "issues": [],
                    "irrelevant_change_is_inert": True,
                },
            },
        )
        self.write(
            "family_reviews/F1.json",
            {
                "accepted": True,
                "family_sha256": fingerprint(group),
                "call": "family",
                "review": {
                    "verdict": "pass",
                    "issues": [],
                    "irrelevant_change_is_inert": True,
                },
            },
        )

    def test_cross_condition_run_reuse_rejected(self):
        dataset(self.args)
        self.args.condition = "no_history"
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            dataset(self.args)

    def test_bypass_is_recorded_and_cannot_silently_change(self):
        _, _, manifest = dataset(self.args)
        self.assertFalse(manifest["allow_unreviewed"])
        self.args.allow_unreviewed = True
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            dataset(self.args)

    def test_filtering_a_split_does_not_hide_persona_overlap(self):
        other = deepcopy(self.data["episodes"])
        for e in other:
            e.update(id=e["id"].replace("F1", "F2"), family_id="F2", split="heldout")
        self.data["episodes"] += other
        self.write("pilot.json", self.data)
        with self.assertRaisesRegex(ValueError, "both development and heldout"):
            dataset(self.args)

    def test_heldout_requires_data_and_code_freeze(self):
        for e in self.data["episodes"]:
            e["split"] = "heldout"
        self.write("pilot.json", self.data)
        self.args.split = "heldout"
        with self.assertRaisesRegex(ValueError, "freeze"):
            dataset(self.args)
        self.write("heldout_freeze.json", freeze_payload(self.data))
        dataset(self.args)
        self.data["revision"] = "changed"
        self.write("pilot.json", self.data)
        with self.assertRaisesRegex(ValueError, "freeze"):
            dataset(self.args)

    def test_control_review_must_bind_current_family(self):
        self.approve()
        control = self.data["episodes"][2]
        ensure_reviewed(control, self.args)
        control["logs"][1]["text"] = "The carpet is yellow."
        self.write("pilot.json", self.data)
        with self.assertRaisesRegex(ValueError, "family review failed or is stale"):
            ensure_reviewed(control, self.args)

    def test_review_cannot_reuse_a_changed_prompt(self):
        self.approve()
        path = self.work / "review_calls/F1-base-blind.json"
        record = json.loads(path.read_text())
        record["prompt"] = "old prompt"
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "prompt or response is stale"):
            ensure_reviewed(self.data["episodes"][0], self.args)

    def test_no_history_contract_does_not_score_unavailable_facts(self):
        e = no_history_contract(self.data["episodes"][0])
        validate_episode(e)
        self.assertEqual(e["logs"], [])
        self.assertNotIn("Dentist", json.dumps(e["contract"]))

    def test_overwritten_raw_judgment_remains_unresolved_in_denominator(self):
        for e in self.data["episodes"]:
            row = result(e)
            row.update(
                judge_prompt_sha256=fingerprint(JUDGE_PROMPT),
                common_checks_sha256=fingerprint(COMMON_CHECKS),
                public_sha256=fingerprint(public_episode(e)),
                condition="full",
                answer_sha256=fingerprint(row["answer"]),
                call=e["id"],
            )
            self.write("runs/test/judgments/" + e["id"] + ".json", row)
            self.write(
                "runs/test/answers/" + e["id"] + ".json",
                {"answer": row["answer"], "call": None},
            )
            self.write(
                "judge_calls/" + e["id"] + ".json",
                {
                    "cache_key": e["id"],
                    "prompt": "frozen",
                    "prompt_sha256": fingerprint("frozen"),
                    "response": row["judgment"],
                },
            )
        path = self.work / "judge_calls/F1-base.json"
        raw = json.loads(path.read_text())
        raw["response"]["observations"][0]["rationale"] = (
            "A different draw overwrote the cached call."
        )
        path.write_text(json.dumps(raw))
        with patch("builtins.print"):
            summary(self.data["episodes"], self.args)
        report = json.loads((self.work / "runs/test/summary.json").read_text())
        self.assertEqual(report["case_success"]["count"], 3)
        self.assertEqual(report["case_success"]["unresolved"], 1)
        self.assertFalse(report["artifact_integrity"]["passed"])


class SourceBoundaryTests(unittest.TestCase):
    def test_identical_concurrent_requests_share_one_frozen_output(self):
        def respond(*args, **kwargs):
            time.sleep(0.03)
            return Namespace(
                returncode=0,
                stdout=json.dumps({"result": "One answer.", "is_error": False}),
                stderr="",
            )

        with (
            tempfile.TemporaryDirectory() as work,
            patch("type5_protocol.backend.subprocess.run", side_effect=respond) as run,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):

            def request(_):
                return infer(
                    "Same request.",
                    model="test",
                    backend="claude",
                    output_dir=work,
                    response_format="text",
                )

            results = list(pool.map(request, range(2)))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(results[0], results[1])

    def test_cached_prompt_cannot_be_substituted(self):
        output = Namespace(
            returncode=0,
            stdout=json.dumps({"result": "Answer.", "is_error": False}),
            stderr="",
        )
        with (
            tempfile.TemporaryDirectory() as work,
            patch("type5_protocol.backend.subprocess.run", return_value=output),
        ):
            row = infer(
                "Original.",
                model="test",
                backend="claude",
                output_dir=work,
                response_format="text",
            )
            row["prompt"] = "Changed."
            (Path(work) / (row["cache_key"] + ".json")).write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "provenance"):
                infer(
                    "Original.",
                    model="test",
                    backend="claude",
                    output_dir=work,
                    response_format="text",
                )

    def test_answer_text_does_not_need_a_json_wrapper(self):
        text = 'Reserve $300 as "trip money". Do not book anything.'
        output = Namespace(
            returncode=0,
            stdout=json.dumps({"result": text, "is_error": False}),
            stderr="",
        )
        with (
            tempfile.TemporaryDirectory() as work,
            patch("type5_protocol.backend.subprocess.run", return_value=output),
        ):
            result = infer(
                "Respond to the user.",
                model="test",
                backend="claude",
                output_dir=work,
                response_format="text",
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["response"]["answer"], text)
        self.assertEqual(result["response_text"], text)

    def test_replicate_id_makes_a_new_call_without_leaking_into_prompt(self):
        output = Namespace(
            returncode=0,
            stdout=json.dumps({"result": "A response.", "is_error": False}),
            stderr="",
        )
        with (
            tempfile.TemporaryDirectory() as work,
            patch("type5_protocol.backend.subprocess.run", return_value=output) as run,
        ):
            first = infer(
                "Respond.",
                model="test",
                backend="claude",
                output_dir=work,
                response_format="text",
            )
            repeated = infer(
                "Respond.",
                model="test",
                backend="claude",
                output_dir=work,
                response_format="text",
                replicate="second",
            )
        self.assertEqual(run.call_count, 2)
        self.assertNotEqual(first["cache_key"], repeated["cache_key"])
        self.assertEqual(
            run.call_args_list[0].kwargs["input"], run.call_args_list[1].kwargs["input"]
        )

    def test_blind_recovery_can_cite_public_task_state(self):
        public = public_episode(family()[0])
        response = {
            "supported_claims": [
                {
                    "id": "B1",
                    "claim": "Two slots are offered.",
                    "evidence": [
                        {"log_id": "task_state", "quote": public["task_state"]}
                    ],
                }
            ],
            "material_unknowns": [],
            "acceptable_behaviors": [],
            "unjustified_interventions": [],
            "unresolved_case_ambiguities": [],
        }
        validate_blind(public, response)
        response["supported_claims"][0]["evidence"][0]["quote"] = "Made up option"
        with self.assertRaises(ValueError):
            validate_blind(public, response)

    def test_curated_cases_have_complete_families_and_no_human_gold_claim(self):
        data = build()
        self.assertEqual(len(validate_families(data["episodes"])), 2)
        self.assertEqual(len(data["calibration"]), 8)
        self.assertTrue(
            all(
                x["label_source"] == "authored_proposal_not_human_gold"
                for x in data["calibration"]
            )
        )

    def test_invalid_transport_json_is_preserved_without_silent_retry(self):
        output = Namespace(
            returncode=0,
            stdout=json.dumps({"result": "{broken", "is_error": False}),
            stderr="",
        )
        with (
            tempfile.TemporaryDirectory() as work,
            patch("type5_protocol.backend.subprocess.run", return_value=output) as run,
        ):
            first = infer(
                "Return a JSON object.", model="test", backend="claude", output_dir=work
            )
            second = infer(
                "Return a JSON object.", model="test", backend="claude", output_dir=work
            )
        self.assertEqual(run.call_count, 1)
        self.assertEqual(first["status"], "invalid_json")
        self.assertIsNone(second["response"])
        self.assertEqual(first["response_text"], "{broken")
        self.assertNotIn("ANTHROPIC_API_KEY", run.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
