"""Regression and end-to-end tests for artifact, admission, and run integrity."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import llm
from pipeline_integrity import admission, fixtures, runs
from pipeline_integrity.artifacts import (
    CURRENT,
    digest,
    output_lock,
    provenance,
    read_json,
    write_json,
)
from step1_seed import generator as step1
from step2_interview import generator as step2
from step3_social_circle import generator as step3
from step4_app_log_synthesizer import generator as step4
from step5_testcases_synthesis import generator as step5
from step6_benchmark_runner import generator as step6
from step6_benchmark_runner.passk import aggregate_passk


def execute_fixture_pipeline(root):
    """Run all stage implementations, replacing only inference transport."""
    record = dict.fromkeys(step1.REQUIRED_FIELDS, "fixture")
    record.update(uuid="fixture-1", persona="Alex Smith teaches.")
    seed = step1.emit_seed(record, root / "step1")
    base = seed.stem.removesuffix("_seed")
    paths = {
        "seed": seed,
        "profile": root / "step2" / f"{base}_verification.json",
        "interview": root / "step2" / f"{base}_interview.json",
        "circle": root / "step3" / f"{base}_social_circle_verification.json",
        "logs": root / "step4" / f"{base}_app_logs.json",
        "cases": root / "step5" / f"{base}_test_cases.json",
    }
    outputs = [json.dumps(row) for row in fixtures.queued_pipeline_outputs()]
    with patch.object(llm, "call_subscription_cli", side_effect=outputs) as transport:
        assert (
            step2.run_step(
                seed, root / "step2", "generator", "reviewer", 1, "high", backend="claude"
            )
            == 0
        )
        assert (
            step3.run_step(
                paths["profile"],
                paths["interview"],
                root / "step3",
                "generator",
                "reviewer",
                1,
                "high",
                backend="claude",
            )
            == 0
        )
        assert (
            step4.run_step(
                paths["profile"],
                paths["circle"],
                root / "step4",
                "generator",
                "reviewer",
                1,
                "2026-03-01",
                "2026-03-31",
                "high",
                provider="anthropic",
                backend="claude",
                target_context_tokens=2000,
            )
            == 0
        )
        assert (
            step5.run_step(
                paths["profile"],
                paths["logs"],
                paths["circle"],
                root / "step5",
                "generator",
                "reviewer",
                1,
                "high",
                backend="claude",
                min_cases=1,
            )
            == 0
        )
        paths["result"] = step6.run_step_once(
            paths["logs"],
            paths["cases"],
            root / "step6",
            "answerer",
            "judge",
            "claude",
            "codex",
            "anthropic",
            "openai",
            "text",
        )
        assert transport.call_count == len(outputs)
    return paths


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def setup_cases(self):
        logs = self.root / "p_app_logs.json"
        cases = self.root / "p_test_cases.json"
        write_json(
            logs,
            {
                "messenger": {
                    "sessions": [
                        {
                            "date": "2026-03-01",
                            "contact": "Dana",
                            "messages": [
                                {"time": "09:00", "sender": "Alex", "text": "coffee before work"}
                            ],
                        }
                    ]
                }
            },
        )
        write_json(
            cases,
            {
                "test_cases": [
                    {"id": "TC-1", "type": admission.TYPES[0], "question": "What routine?"}
                ]
            },
        )
        fixtures.seal_fixture(cases, logs)
        return logs, cases

    def score(self, *, skip_pass1=False, model="answerer", judge="judge", run_index=None, **kwargs):
        with (
            patch.object(
                step6,
                "run_pass_1",
                return_value={"answers": [{"test_case_id": "TC-1", "answer": "coffee"}]},
            ),
            patch.object(
                step6,
                "run_pass_2",
                return_value={
                    "evaluations": [
                        {"test_case_id": "TC-1", "score": "CORRECT", "score_value": 1.0}
                    ]
                },
            ),
        ):
            return step6.run_step_once(
                self.root / "p_app_logs.json",
                self.root / "p_test_cases.json",
                self.root / "out",
                model,
                judge,
                "claude",
                "codex",
                "anthropic",
                "openai",
                "text",
                allow_legacy_inputs=True,
                skip_pass1=skip_pass1,
                run_index=run_index,
                **kwargs,
            )

    def test_all_stages_preserve_exact_inputs_outputs_and_raw_calls(self):
        paths = execute_fixture_pipeline(self.root)
        self.assertEqual(read_json(paths["result"])["overall_accuracy"], "100%")
        for key in ("profile", "interview", "circle", "logs", "cases", "result"):
            self.assertEqual(provenance(paths[key])["status"], "accepted")
        calls = list(self.root.glob("**/calls/*.json"))
        self.assertEqual(len(calls), 13)
        for call in calls:
            row = read_json(call)
            self.assertEqual(row["prompt_sha256"], digest(row["prompt"]))
            self.assertIsInstance(json.loads(row["raw_response"]), dict)
        inventory = read_json(
            paths["cases"].with_name(
                paths["cases"].name.replace("_test_cases.json", "_test_cases_verification.json")
            )
        )
        self.assertTrue(inventory["admission"]["complete"])

    def test_seed_same_name_has_distinct_identity_and_never_overwrites_revision(self):
        record = dict.fromkeys(step1.REQUIRED_FIELDS, "fixture")
        record.update(uuid="one", persona="Alex Smith teaches.")
        first = step1.emit_seed(record, self.root)
        second = step1.emit_seed(dict(record, uuid="two"), self.root)
        self.assertNotEqual(first, second)
        self.assertEqual(step1.emit_seed(record, self.root), first)
        with self.assertRaisesRegex(ValueError, "different contents"):
            step1.emit_seed(dict(record, age=42), self.root)

    def test_missing_canonical_profile_and_circle_are_rejected(self):
        for validator in (admission.profile, admission.social_circle):
            with self.assertRaises(ValueError):
                validator({"verification": {"overall_verdict": "PASS"}})
        with self.assertRaises(ValueError):
            admission.interview({"transcript": []})

    def test_direct_stage3_rejects_failed_upstream_before_inference(self):
        profile = self.root / "p_verification.json"
        interview = self.root / "p_interview.json"
        write_json(
            profile, {**fixtures.profile_review(), "verification": {"overall_verdict": "FAIL"}}
        )
        write_json(interview, fixtures.interview())
        with (
            patch.object(step3, "run_generation") as generation,
            self.assertRaisesRegex(ValueError, "did not pass"),
        ):
            step3.run_step(
                profile,
                interview,
                self.root / "out",
                "g",
                "v",
                1,
                "high",
                backend="claude",
                allow_legacy_inputs=True,
            )
        generation.assert_not_called()

    def test_empty_step5_review_cannot_pass(self):
        verification = {}
        step5.enforce_contract_verification(fixtures.dataset(), verification)
        self.assertFalse(step5.verification_passed(verification))

    def test_missing_step5_review_blocks_scoring(self):
        self.setup_cases()
        (self.root / "p_test_cases_verification.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing independent"):
            self.score()

    def test_changed_history_requires_fresh_answer_even_after_new_case_review(self):
        logs, cases = self.setup_cases()
        self.score()
        value = read_json(logs)
        value["messenger"]["sessions"][0]["messages"][0]["time"] = "10:00"
        write_json(logs, value)
        fixtures.seal_fixture(cases, logs)
        with self.assertRaisesRegex(ValueError, "Saved answers"):
            self.score(skip_pass1=True)

    def test_changed_question_requires_fresh_answer_even_after_new_case_review(self):
        logs, cases = self.setup_cases()
        self.score()
        value = read_json(cases)
        value["test_cases"][0]["question"] = "Who mentions coffee?"
        write_json(cases, value)
        fixtures.seal_fixture(cases, logs)
        with self.assertRaisesRegex(ValueError, "Saved answers"):
            self.score(skip_pass1=True)

    def test_changed_answering_configuration_cannot_be_relabelled(self):
        self.setup_cases()
        self.score()
        for kwargs in (
            {"model": "different"},
            {"reasoning_pass1": "high"},
            {"answering_layout": "batch"},
        ):
            with self.assertRaisesRegex(ValueError, "Saved answers"):
                self.score(skip_pass1=True, **kwargs)

    def test_rescore_preserves_answer_call_and_archives_old_judgment(self):
        self.setup_cases()
        first = read_json(self.score())
        second = read_json(self.score(skip_pass1=True, judge="second-judge"))
        self.assertEqual(
            first["metadata"]["run_identity"]["answer_run"],
            second["metadata"]["run_identity"]["answer_run"],
        )
        self.assertNotEqual(
            first["metadata"]["run_identity"]["judge"], second["metadata"]["run_identity"]["judge"]
        )
        self.assertEqual(
            len(
                list((self.root / "out").glob(".attempts/step6/*/outputs/*benchmark_results.json"))
            ),
            2,
        )

    def test_missing_resume_file_does_not_silently_call_model(self):
        self.setup_cases()
        with self.assertRaisesRegex(ValueError, "requires an existing"):
            self.score(skip_pass1=True)

    def test_raw_answer_tampering_is_rejected(self):
        self.setup_cases()
        self.score()
        answers = self.root / "out/p_pass1_answers.json"
        value = read_json(answers)
        value["answers"][0]["answer"] = "edited"
        write_json(answers, value)
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.score(skip_pass1=True)

    def test_distinct_calls_with_identical_answers_are_valid_replicates(self):
        self.setup_cases()
        paths = [self.score(run_index=i) for i in (1, 2)]
        result = aggregate_passk(paths)
        self.assertEqual(result["metadata"]["provenance_status"], "bound")
        self.assertEqual(result["overall"]["strict_pass_k_percent"], "100%")

    def test_duplicate_files_and_rescored_calls_are_not_replicates(self):
        self.setup_cases()
        path = self.score()
        with self.assertRaisesRegex(ValueError, "distinct result files"):
            aggregate_passk([path, path])
        first = read_json(path)
        second = read_json(self.score(skip_pass1=True))
        with self.assertRaisesRegex(ValueError, "distinct answer calls"):
            runs.compatible_runs([first, second])

    def test_different_models_or_case_versions_cannot_be_aggregated(self):
        self.setup_cases()
        first = read_json(self.score(run_index=1))
        second = read_json(self.score(run_index=2, model="another-answerer"))
        with self.assertRaisesRegex(ValueError, "incompatible"):
            runs.compatible_runs([first, second])
        second = deepcopy(first)
        identity = second["metadata"]["run_identity"]
        identity["answer_run"]["call_id"] = "another-call"
        identity["answer_run"]["identity"]["dataset_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "incompatible"):
            runs.compatible_runs([first, second])

    def test_historical_reliability_requires_explicit_import(self):
        with self.assertRaisesRegex(ValueError, "bound runs"):
            runs.compatible_runs([{"evaluations": []}, {"evaluations": []}])
        self.assertEqual(runs.compatible_runs([{}, {}], allow_legacy=True), "historical_unbound")
        with self.assertRaisesRegex(ValueError, "different case contents"):
            runs.compatible_runs(
                [
                    {"metadata": {"evaluation_manifest": {"case_sha256": {"a": h}}}}
                    for h in ("old", "new")
                ],
                allow_legacy=True,
            )

    def test_case_review_inventory_and_criteria_fail_closed(self):
        dataset = fixtures.dataset()
        verification, blind = fixtures.review(dataset, "source")
        for mutate in (
            lambda v: v.update(evaluations=[]),
            lambda v: v["evaluations"].append(deepcopy(v["evaluations"][0])),
            lambda v: v["evaluations"][0].pop("public_evidence_check"),
            lambda v: v["evaluations"][0].update(overall_verdict="FLAGGED"),
        ):
            changed = deepcopy(verification)
            mutate(changed)
            with self.assertRaises(ValueError):
                admission.seal_cases(
                    dataset,
                    changed,
                    {"hidden_facts": fixtures.profile()["hidden_facts"]},
                    blind,
                    "source",
                    min_cases=1,
                )

    def test_review_binding_catches_changed_key_or_history(self):
        dataset = fixtures.dataset()
        verification, blind = fixtures.review(dataset, "source")
        source = {"hidden_facts": fixtures.profile()["hidden_facts"]}
        admission.seal_cases(dataset, verification, source, blind, "source", min_cases=1)
        self.assertTrue(admission.admitted_cases(dataset, verification, source, "source"))
        changed = deepcopy(dataset)
        changed["test_cases"][0]["ground_truth"] = "unsupported replacement"
        for data, logs, text in (
            (changed, source, "source"),
            (dataset, {**source, "changed": True}, "source"),
            (dataset, source, "changed source"),
        ):
            with self.assertRaisesRegex(ValueError, "differs"):
                admission.admitted_cases(data, verification, logs, text)

    def test_public_review_never_sees_private_key_or_another_question(self):
        dataset = fixtures.dataset()
        dataset["test_cases"][0]["ground_truth"] = "PRIVATE_CANARY"
        dataset["test_cases"].append(
            {"id": "TC-2", "type": admission.TYPES[0], "question": "SECOND_QUESTION"}
        )
        responses = []
        for case in dataset["test_cases"]:
            _, blind = fixtures.review({"test_cases": [case]}, "source")
            responses.append(json.dumps(blind))
        logs = {"messenger": {"sessions": [{"messages": [{"text": "source"}]}]}}
        with patch.object(step5, "call_llm", side_effect=responses) as call:
            step5.run_public_review(None, "reviewer", dataset, logs, "high", backend="claude")
        self.assertNotIn("PRIVATE_CANARY", str(call.call_args_list))
        self.assertNotIn("SECOND_QUESTION", call.call_args_list[0].args[2])

    def test_source_quotes_cannot_come_from_hidden_annotations(self):
        dataset = fixtures.dataset()
        _, blind = fixtures.review(dataset, "PRIVATE_ONLY")
        with self.assertRaisesRegex(ValueError, "quotes"):
            admission.public_review(dataset, blind, "public history")

    def test_unresolved_fact_ids_cannot_be_certified_by_a_pass_label(self):
        dataset = fixtures.dataset()
        dataset["test_cases"][0]["source_hidden_fact_ids"] = ["HF-does-not-exist"]
        verification, blind = fixtures.review(dataset, "source")
        with self.assertRaisesRegex(ValueError, "unresolved"):
            admission.seal_cases(
                dataset,
                verification,
                {"hidden_facts": fixtures.profile()["hidden_facts"]},
                blind,
                "source",
                min_cases=1,
            )

    def test_no_answer_cannot_receive_credit_from_a_judge(self):
        case = fixtures.dataset()
        result = {"evaluations": [{"test_case_id": "TC-1", "score_value": 1.0, "score": "CORRECT"}]}
        scored = step6.recompute_benchmark_summary(result, case, "a", "j", {"answers": []})
        self.assertEqual(scored["overall_accuracy"], "0%")
        self.assertEqual(scored["evaluations"][0]["evaluation_status"], "missing_answer")

    def test_output_lock_blocks_concurrent_writers_and_releases(self):
        with (
            output_lock(self.root, "example"),
            self.assertRaises(OSError),
            output_lock(self.root, "example"),
        ):
            self.fail("Second writer acquired the same artifact lock")
        with output_lock(self.root, "example"):
            pass

    def test_invalid_json_retains_the_original_call(self):
        token = CURRENT.set(self.root)
        try:
            with patch.object(llm, "call_subscription_cli", return_value="not JSON"):
                raw = llm.call_llm(None, "fixture", "task", "low", backend="claude")
            self.assertEqual(raw, "not JSON")
            call = read_json(next((self.root / "calls").glob("*.json")))
            self.assertEqual(call["parse_status"], "invalid_json")
            self.assertEqual(call["raw_response"], raw)
        finally:
            CURRENT.reset(token)

    def test_cli_uses_text_inference_in_an_empty_working_directory(self):
        from types import SimpleNamespace

        with patch(
            "subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")
        ) as process:
            self.assertEqual(llm.call_claude_cli("task", "fixture"), "{}")
        arguments = process.call_args.args[0]
        self.assertEqual(arguments[arguments.index("--system-prompt") + 1], llm.INFERENCE_SYSTEM)
        self.assertEqual(arguments[arguments.index("--tools") + 1], "")
        self.assertNotIn("ANTHROPIC_API_KEY", process.call_args.kwargs["env"])
        self.assertFalse(Path(process.call_args.kwargs["cwd"]).exists())

    def test_step4_resume_rejects_changed_generation_configuration(self):
        paths = execute_fixture_pipeline(self.root)
        with self.assertRaisesRegex(ValueError, "generation/gate configuration"):
            step4.run_step(
                paths["profile"],
                paths["circle"],
                self.root / "step4",
                "generator",
                "reviewer",
                1,
                "2026-04-01",
                "2026-04-30",
                "high",
                provider="anthropic",
                backend="claude",
                resume=True,
            )

    def test_historical_outputs_are_not_implicitly_imported(self):
        logs, _ = self.setup_cases()
        with self.assertRaisesRegex(ValueError, "no bound provenance"):
            provenance(logs)
        self.assertEqual(provenance(logs, allow_legacy=True)["status"], "historical_unbound")

    def test_anthropic_transport_uses_supported_arguments_and_records_usage(self):
        from contextlib import contextmanager
        from types import SimpleNamespace

        captured = {}

        @contextmanager
        def stream(*, model, system, max_tokens, messages):
            captured.update(model=model, system=system, max_tokens=max_tokens, messages=messages)
            message = SimpleNamespace(
                model=model,
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text='{"ok":true}')],
                usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 10, "output_tokens": 4}),
            )
            yield SimpleNamespace(get_final_message=lambda: message)

        client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
        token = CURRENT.set(self.root)
        try:
            raw = llm.call_llm(client, "fixture", "task", "high", backend="anthropic-api")
            call = read_json(next((self.root / "calls").glob("*.json")))
        finally:
            CURRENT.reset(token)
        self.assertEqual(json.loads(raw), {"ok": True})
        self.assertEqual(captured["system"], llm.INFERENCE_SYSTEM)
        self.assertEqual(call["usage"]["output_tokens"], 4)
        self.assertIsNone(call["transport_attempts"][0]["temperature"])

    def test_api_truncation_is_an_error_with_retained_visible_response(self):
        from contextlib import contextmanager
        from types import SimpleNamespace

        @contextmanager
        def stream(**kwargs):
            yield SimpleNamespace(
                get_final_message=lambda: SimpleNamespace(
                    model="fixture",
                    stop_reason="max_tokens",
                    content=[SimpleNamespace(type="text", text='{"partial":')],
                    usage=SimpleNamespace(model_dump=lambda: {"output_tokens": 64000}),
                )
            )

        token = CURRENT.set(self.root)
        try:
            with self.assertRaisesRegex(ValueError, "completion budget"):
                llm.call_llm(
                    SimpleNamespace(messages=SimpleNamespace(stream=stream)),
                    "fixture",
                    "task",
                    "high",
                )
            call = read_json(next((self.root / "calls").glob("*.json")))
        finally:
            CURRENT.reset(token)
        self.assertEqual(call["status"], "error")
        self.assertEqual(call["transport_attempts"][0]["raw_text"], '{"partial":')

    def test_openai_request_records_system_and_completion_budget(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        create = Mock(
            return_value=SimpleNamespace(
                model="fixture",
                usage=None,
                choices=[
                    SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}"))
                ],
            )
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        self.assertEqual(llm.call_api(client, "fixture", "task", provider="openai"), "{}")
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["messages"][0], {"role": "system", "content": llm.INFERENCE_SYSTEM})
        self.assertEqual(kwargs["extra_body"]["max_completion_tokens"], 64000)
        self.assertNotIn("temperature", kwargs)

    def test_factual_judgments_require_valid_rubric_scores(self):
        case = fixtures.dataset()["test_cases"][0]
        for value in (True, "1.0", None, -1, 2, float("nan"), float("inf"), 0.5):
            with self.subTest(value=value):
                accepted, errors = step6._check_pass2_batch(
                    {
                        "evaluations": [
                            {"test_case_id": case["id"], "score": "CORRECT", "score_value": value}
                        ]
                    },
                    [case],
                )
                self.assertFalse(accepted)
                self.assertIn(case["id"], errors)
        for verdict, value in (("CORRECT", 1.0), ("PARTIAL", 0.5), ("INCORRECT", 0.0)):
            accepted, errors = step6._check_pass2_batch(
                {
                    "evaluations": [
                        {"test_case_id": case["id"], "score": verdict, "score_value": value}
                    ]
                },
                [case],
            )
            self.assertFalse(errors)
            self.assertEqual(accepted[0]["score_value"], value)

    def test_malformed_factual_judgment_can_recover_once(self):
        dataset = fixtures.dataset()
        base = {"test_case_id": "TC-1", "score": "CORRECT"}
        responses = [
            {"evaluations": [{**base, "score_value": 100}]},
            {"evaluations": [{**base, "score_value": 1.0}]},
        ]
        with patch.object(step6, "_call_pass2_single", side_effect=responses) as judge:
            records, _, off_schema, failed = step6._score_batch(
                {}, dataset, {"answers": []}, "fixture", {}
            )
        self.assertEqual(judge.call_count, 2)
        self.assertEqual(records[0]["score_value"], 1.0)
        self.assertEqual((off_schema, failed), (0, 0))

    def test_invalid_reference_is_retained_without_rerolling_the_rubric(self):
        dataset = fixtures.dataset()
        for validity in ("invalid", "uncertain"):
            response = {
                "evaluations": [
                    {
                        "test_case_id": "TC-1",
                        "reference_validity": validity,
                        "score": "CORRECT",
                        "score_value": 1.0,
                    }
                ]
            }
            with patch.object(step6, "_call_pass2_single", return_value=response) as judge:
                records, _, _, _ = step6._score_batch({}, dataset, {"answers": []}, "fixture", {})
            self.assertEqual(judge.call_count, 1)
            self.assertEqual(records[0]["score_value"], 0.0)
            self.assertEqual(records[0]["raw_judgment"]["score_value"], 1.0)
            result = step6.recompute_benchmark_summary(
                {"evaluations": records}, dataset, "answerer", "judge"
            )
            coverage = result["metadata"]["evaluation_coverage"]
            self.assertEqual(coverage["evaluation_errors"], 1)
            self.assertEqual(coverage["score_lower_bound"], "0%")
            self.assertEqual(coverage["score_upper_bound"], "100%")

    def test_factual_judge_cannot_set_scorer_owned_status(self):
        case = fixtures.dataset()["test_cases"][0]
        row = {
            "test_case_id": case["id"],
            "score": "CORRECT",
            "score_value": 1.0,
            "evaluation_status": "missing_evaluation",
        }
        accepted, errors = step6._check_pass2_batch({"evaluations": [row]}, [case])
        self.assertFalse(errors)
        self.assertEqual(accepted[0]["evaluation_status"], "evaluated")
        row["score"] = []
        accepted, errors = step6._check_pass2_batch({"evaluations": [row]}, [case])
        self.assertFalse(accepted)
        self.assertIn(case["id"], errors)


if __name__ == "__main__":
    unittest.main()
