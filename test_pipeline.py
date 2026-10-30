"""Regression tests for the pipeline runner and stage gates.

Covers the behaviors that keep results trustworthy: stage failures stop
the pipeline, subprocess arguments are well formed, the Step 4 cluster
gate enforces its documented predicate by default, and the Step 6
summary keeps a frozen denominator.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run as pipeline
from step4_app_log_synthesizer import generator as step4
from step6_benchmark_runner import generator as step6


def _write_seed(tmp: str) -> Path:
    seed_path = Path(tmp) / "test_persona_seed.json"
    seed_path.write_text(
        json.dumps({"persona": "Test Persona teaches.", "uuid": "u-1"}),
        encoding="utf-8",
    )
    return seed_path


def _run_pipeline(seed_path: Path, start: int, stop: int, **kwargs) -> None:
    pipeline.run_pipeline(
        seed_path,
        "codex",
        "openai",
        "gpt-5.5",
        "gpt-5.5",
        "gpt-5.5",
        "gpt-5.4-mini",
        None,
        start,
        stop,
        **kwargs,
    )


class PipelineRunnerTests(unittest.TestCase):
    def test_stage_failure_stops_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = _write_seed(tmp)
            with patch.object(
                pipeline.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1),
            ) as proc:
                with self.assertRaises(pipeline.StageError):
                    _run_pipeline(seed_path, 2, 6)
        # Step 2 failed, so steps 3-6 must not have run.
        self.assertEqual(proc.call_count, 1)

    def test_subprocess_args_are_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = _write_seed(tmp)
            with patch.object(
                pipeline.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as proc:
                _run_pipeline(seed_path, 4, 4, target_context_tokens=500000)
        cmd = proc.call_args.args[0]
        self.assertTrue(all(isinstance(part, str) for part in cmd))
        self.assertEqual(cmd[cmd.index("--target-context-tokens") + 1], "500000")

    def test_gate_policy_is_forwarded_to_step4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = _write_seed(tmp)
            with patch.object(
                pipeline.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as proc:
                _run_pipeline(seed_path, 4, 4)
            cmd = proc.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--gate-policy") + 1], "strict")

            with patch.object(
                pipeline.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as proc:
                _run_pipeline(seed_path, 4, 4, gate_policy="lenient")
            cmd = proc.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--gate-policy") + 1], "lenient")


def _verification(verdict: str, confidence: str, leaks: bool) -> dict:
    check = {"fragments_that_leak_labels": []}
    if leaks:
        check["fragments_that_leak_labels"] = [
            {
                "fragment_id": "C1-F1",
                "leaked_text": "explicit label",
                "leak_type": "too_obvious_single_fragment",
            }
        ]
    return {
        "verdict": verdict,
        "shared_evidence_check": {
            "every_fragment_supports_multiple_candidate_facts": True,
            "each_candidate_supported_by_at_least_2_fragments": True,
        },
        "candidate_facts": [
            {
                "candidate_label": "daily medication routine",
                "confidence": confidence,
                "supporting_fragments": ["C1-F1", "C1-F2"],
                "implicitness_check": check,
            }
        ],
    }


_FACTS = [{"fact_id": "HF-001", "ground_truth_label": "daily medication routine"}]


class ClusterGateTests(unittest.TestCase):
    def test_strict_accepts_clean_recovered(self) -> None:
        verification = _verification("RECOVERED", "HIGH", leaks=False)
        passed, _ = step4.cluster_passed(verification, _FACTS, policy="strict")
        self.assertTrue(passed)
        decision = verification["_gate_decision"]
        self.assertEqual(decision["reason"], "recovered_no_leaks")
        self.assertEqual(decision["policy"], "strict")

    def test_strict_rejects_recovered_with_leaks(self) -> None:
        verification = _verification("RECOVERED", "HIGH", leaks=True)
        passed, _ = step4.cluster_passed(verification, _FACTS, policy="strict")
        self.assertFalse(passed)
        self.assertNotIn("_gate_decision", verification)

    def test_strict_rejects_ambiguous(self) -> None:
        verification = _verification("AMBIGUOUS", "HIGH", leaks=True)
        passed, _ = step4.cluster_passed(verification, _FACTS, policy="strict")
        self.assertFalse(passed)

    def test_lenient_accepts_high_confidence_ambiguous_with_leaks(self) -> None:
        verification = _verification("AMBIGUOUS", "HIGH", leaks=True)
        passed, _ = step4.cluster_passed(verification, _FACTS, policy="lenient")
        self.assertTrue(passed)
        decision = verification["_gate_decision"]
        self.assertEqual(decision["original_verdict"], "AMBIGUOUS")
        self.assertEqual(decision["accepted_as"], "RECOVERED")

    def test_lenient_rejects_medium_confidence_ambiguous(self) -> None:
        verification = _verification("AMBIGUOUS", "MEDIUM", leaks=True)
        passed, _ = step4.cluster_passed(verification, _FACTS, policy="lenient")
        self.assertFalse(passed)


class BenchmarkSummaryTests(unittest.TestCase):
    def test_missing_evaluations_keep_denominator(self) -> None:
        test_cases = {
            "test_cases": [
                {"id": "TC-01", "type": "type_1_simple_fact_check"},
                {"id": "TC-02", "type": "type_1_simple_fact_check"},
                {"id": "TC-03", "type": "type_1_simple_fact_check"},
            ]
        }
        result = {
            "evaluations": [
                {
                    "test_case_id": "TC-01",
                    "type": "type_1_simple_fact_check",
                    "score": "CORRECT",
                    "score_value": 1.0,
                }
            ]
        }
        summary = step6.recompute_benchmark_summary(
            result, test_cases, "model-a", "model-b"
        )
        # One correct case out of three intended, not one out of one.
        self.assertEqual(summary["overall_accuracy"], "33.3%")
        self.assertEqual(summary["metadata"]["total_cases"], 3)
        self.assertEqual(summary["metadata"]["failed_evaluation_cases"], 2)
        statuses = {
            ev.get("evaluation_status")
            for ev in summary["evaluations"]
            if ev.get("score") == "FAILED_EVALUATION"
        }
        self.assertEqual(statuses, {"missing_evaluation"})

    def test_subtype_type_strings_bucket_as_type_5(self) -> None:
        test_cases = {
            "test_cases": [
                {"id": "TC-01", "type": "5c_ambiguity"},
                {"id": "TC-02", "type": "type_5_agent_behavior", "subtype": "5a_safety"},
            ]
        }
        result = {
            "evaluations": [
                {"test_case_id": "TC-01", "type": "5c_ambiguity", "score_value": 1.0},
                {
                    "test_case_id": "TC-02",
                    "type": "type_5_agent_behavior",
                    "score_value": 0.0,
                },
            ]
        }
        summary = step6.recompute_benchmark_summary(
            result, test_cases, "model-a", "model-b"
        )
        self.assertEqual(list(summary["accuracy_by_type"]), ["type_5_agent_behavior"])
        self.assertEqual(summary["accuracy_by_type"]["type_5_agent_behavior"], "50%")
        self.assertIn("5c_ambiguity", summary["type_5_breakdown"]["by_subtype"])

    def test_normalize_case_type(self) -> None:
        self.assertEqual(
            step6.normalize_case_type("5c_ambiguity"), "type_5_agent_behavior"
        )
        self.assertEqual(
            step6.normalize_case_type("type_1_simple_fact_check"),
            "type_1_simple_fact_check",
        )
        self.assertEqual(step6.normalize_case_type(None), "unknown")


if __name__ == "__main__":
    unittest.main()
