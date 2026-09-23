from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from step6_benchmark_runner import generator  # noqa: E402
from step6_benchmark_runner.passk import (  # noqa: E402
    aggregate_passk,
    load_evaluations,
    score_value,
)
import run as pipeline  # noqa: E402


PASSK_SCRIPT = REPO_ROOT / "step6_benchmark_runner" / "passk.py"


def write_json(path: Path, payload: dict[str, Any], *, bom: bool = False) -> None:
    encoding = "utf-8-sig" if bom else "utf-8"
    path.write_text(json.dumps(payload, indent=2), encoding=encoding)


def result_payload(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"evaluations": evaluations}


def evaluation(
    test_case_id: str,
    score_value_: float | str | None = None,
    *,
    score: str | None = None,
    typ: str = "type_4_reasoning",
    subtype: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "test_case_id": test_case_id,
        "type": typ,
    }
    if score_value_ is not None:
        item["score_value"] = score_value_
    if score is not None:
        item["score"] = score
    if subtype is not None:
        item["subtype"] = subtype
    return item


class PassKTests(unittest.TestCase):
    def test_strict_passk_and_minscorek_by_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run1 = root / "run1.json"
            run2 = root / "run2.json"
            run3 = root / "run3.json"
            cases = root / "cases.json"

            write_json(
                run1,
                result_payload([
                    evaluation("TC-01", 1.0, typ="type_1_simple_fact_check"),
                    evaluation("TC-02", 1.0, typ="type_4_reasoning"),
                    evaluation("TC-03", 0.5, typ="type_5_agent_behavior"),
                ]),
            )
            write_json(
                run2,
                result_payload([
                    evaluation("TC-01", 1.0, typ="type_1_simple_fact_check"),
                    evaluation("TC-02", 0.5, typ="type_4_reasoning"),
                    evaluation("TC-03", 0.5, typ="type_5_agent_behavior"),
                ]),
            )
            write_json(
                run3,
                result_payload([
                    evaluation("TC-01", 1.0, typ="type_1_simple_fact_check"),
                    evaluation("TC-02", 0.0, typ="type_4_reasoning"),
                    evaluation("TC-03", 0.5, typ="type_5_agent_behavior"),
                ]),
            )
            write_json(
                cases,
                {
                    "test_cases": [
                        {"id": "TC-01", "subtype": None},
                        {"id": "TC-02", "subtype": None},
                        {"id": "TC-03", "subtype": "5a_safety"},
                    ]
                },
            )

            summary = aggregate_passk([run1, run2, run3], test_cases_path=cases)

        self.assertEqual(summary["metadata"]["metric"], "Pass^3")
        self.assertEqual(summary["metadata"]["case_alignment"], "exact")
        self.assertEqual(summary["overall"]["case_count"], 3)
        self.assertEqual(summary["overall"]["strict_pass_k_count"], 1)
        self.assertEqual(summary["overall"]["strict_pass_k_percent"], "33.3%")
        self.assertEqual(summary["overall"]["min_score_k_average"], 0.5)
        self.assertEqual(
            summary["overall"]["average_accuracy_across_runs"],
            0.6667,
        )
        self.assertEqual(summary["overall"]["worst_run_accuracy"], 0.5)
        self.assertEqual(
            [run["average_score"] for run in summary["run_accuracy"]],
            [0.8333, 0.6667, 0.5],
        )

        by_type = summary["by_type"]
        self.assertEqual(
            by_type["type_1_simple_fact_check"]["strict_pass_k_percent"],
            "100%",
        )
        self.assertEqual(by_type["type_4_reasoning"]["strict_pass_k_percent"], "0%")
        self.assertEqual(by_type["type_4_reasoning"]["min_score_k_average"], 0.0)
        self.assertEqual(
            by_type["type_5_agent_behavior"]["min_score_k_average"],
            0.5,
        )
        self.assertEqual(summary["by_subtype"]["5a_safety"]["case_count"], 1)
        self.assertEqual(
            summary["unstable_cases"][0]["test_case_id"],
            "TC-02",
        )
        self.assertEqual(summary["hard_failures"][0]["test_case_id"], "TC-02")
        self.assertEqual(len(summary["per_case"]), 3)

    def test_score_value_accepts_numeric_and_verdict_scores(self) -> None:
        self.assertEqual(score_value(evaluation("TC-01", "0.5")), 0.5)
        self.assertEqual(score_value(evaluation("TC-02", score="CORRECT")), 1.0)
        self.assertEqual(score_value(evaluation("TC-03", score="FLAGGED")), 0.5)
        self.assertEqual(score_value(evaluation("TC-04", score="failed")), 0.0)

    def test_invalid_scores_raise(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside 0..1"):
            score_value(evaluation("TC-01", 1.5))
        with self.assertRaisesRegex(ValueError, "invalid score_value"):
            score_value(evaluation("TC-02", "mostly"))
        with self.assertRaisesRegex(ValueError, "not boolean"):
            score_value(evaluation("TC-03", True))
        with self.assertRaisesRegex(ValueError, "no recognized score"):
            score_value(evaluation("TC-04", score="MAYBE"))

    def test_default_alignment_requires_same_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run1 = root / "run1.json"
            run2 = root / "run2.json"
            write_json(
                run1,
                result_payload([
                    evaluation("TC-01", 1.0),
                    evaluation("TC-02", 1.0),
                ]),
            )
            write_json(run2, result_payload([evaluation("TC-01", 1.0)]))

            with self.assertRaisesRegex(ValueError, "same test_case_id set"):
                aggregate_passk([run1, run2])

    def test_allow_missing_scores_missing_cases_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run1 = root / "run1.json"
            run2 = root / "run2.json"
            write_json(
                run1,
                result_payload([
                    evaluation("TC-01", 1.0),
                    evaluation("TC-02", 1.0),
                ]),
            )
            write_json(run2, result_payload([evaluation("TC-01", 1.0)]))

            summary = aggregate_passk([run1, run2], allow_missing=True)

        self.assertEqual(summary["metadata"]["case_alignment"], "union_missing_as_zero")
        self.assertEqual(summary["overall"]["case_count"], 2)
        self.assertEqual(summary["overall"]["strict_pass_k_count"], 1)
        self.assertEqual(summary["missing_cases"][0]["missing_test_case_ids"], ["TC-02"])

        tc2 = [
            record for record in summary["per_case"]
            if record["test_case_id"] == "TC-02"
        ][0]
        self.assertEqual(tc2["scores"], [1.0, 0.0])
        self.assertEqual(tc2["missing_from_runs"], [2])
        self.assertFalse(tc2["hard_failure"])
        self.assertTrue(tc2["evaluation_error_runs"])

    def test_duplicate_evaluation_ids_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            write_json(
                path,
                result_payload([
                    evaluation("TC-01", 1.0),
                    evaluation("TC-01", 0.5),
                ]),
            )

            with self.assertRaisesRegex(ValueError, "duplicate evaluation id TC-01"):
                load_evaluations(path)

    def test_duplicate_test_case_metadata_ids_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run1 = root / "run1.json"
            run2 = root / "run2.json"
            cases = root / "cases.json"
            write_json(run1, result_payload([evaluation("TC-01", 1.0)]))
            write_json(run2, result_payload([evaluation("TC-01", 1.0)]))
            write_json(
                cases,
                {
                    "test_cases": [
                        {"id": "TC-01"},
                        {"id": "TC-01"},
                    ]
                },
            )

            with self.assertRaisesRegex(ValueError, "duplicate test case id TC-01"):
                aggregate_passk([run1, run2], test_cases_path=cases)

    def test_cli_writes_output_and_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run1 = root / "run1.json"
            run2 = root / "run2.json"
            output = root / "pass2_summary.json"
            write_json(run1, result_payload([evaluation("TC-01", 1.0)]), bom=True)
            write_json(run2, result_payload([evaluation("TC-01", 1.0)]))

            proc = subprocess.run(
                [
                    sys.executable,
                    str(PASSK_SCRIPT),
                    str(run1),
                    str(run2),
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["metadata"]["metric"], "Pass^2")
        self.assertEqual(payload["overall"]["strict_pass_k_percent"], "100%")

    def test_generator_passk_mode_writes_repeated_runs_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_logs = root / "sample_app_logs.json"
            test_cases = root / "sample_test_cases.json"
            output_dir = root / "output"

            write_json(
                app_logs,
                {
                    "persona_name": "Sample Persona",
                    "messenger": {
                        "sessions": [
                            {
                                "date": "2026-03-01",
                                "contact": "Dana",
                                "messages": [
                                    {
                                        "time": "09:00",
                                        "sender": "Sample Persona",
                                        "text": "coffee before work",
                                    }
                                ],
                            }
                        ]
                    },
                    "calendar": {"events": []},
                },
            )
            write_json(
                test_cases,
                {
                    "test_cases": [
                        {
                            "id": "TC-01",
                            "question": "What was mentioned?",
                            "type": "type_1_simple_fact_check",
                        },
                        {
                            "id": "TC-02",
                            "question": "What routine is implied?",
                            "type": "type_4_reasoning",
                        },
                    ]
                },
            )

            pass1_runs = [
                {
                    "answers": [
                        {"test_case_id": "TC-01", "answer": "coffee"},
                        {"test_case_id": "TC-02", "answer": "morning routine"},
                    ]
                },
                {
                    "answers": [
                        {"test_case_id": "TC-01", "answer": "coffee"},
                        {"test_case_id": "TC-02", "answer": "unclear"},
                    ]
                },
            ]
            pass2_runs = [
                result_payload([
                    evaluation("TC-01", 1.0, typ="type_1_simple_fact_check"),
                    evaluation("TC-02", 1.0, typ="type_4_reasoning"),
                ]),
                result_payload([
                    evaluation("TC-01", 1.0, typ="type_1_simple_fact_check"),
                    evaluation("TC-02", 0.0, typ="type_4_reasoning"),
                ]),
            ]

            with (
                patch.object(generator, "run_pass_1", side_effect=pass1_runs) as pass1,
                patch.object(generator, "run_pass_2", side_effect=pass2_runs) as pass2,
            ):
                rc = generator.run_passk_step(
                    app_logs,
                    test_cases,
                    output_dir,
                    "model-pass1",
                    "model-pass2",
                    "claude",
                    "anthropic",
                    "claude",
                    "codex",
                    "json",
                    runs=2,
                    reasoning_pass1="low",
                    reasoning_pass2="high",
                )

            summary_path = output_dir / "sample_pass2_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            pass1_calls = pass1.call_count
            pass2_calls = pass2.call_count
            run01_pass1_exists = (
                output_dir / "sample_run01_pass1_answers.json"
            ).exists()
            run02_pass1_exists = (
                output_dir / "sample_run02_pass1_answers.json"
            ).exists()
            run01_results_exists = (
                output_dir / "sample_run01_benchmark_results.json"
            ).exists()
            run02_results_exists = (
                output_dir / "sample_run02_benchmark_results.json"
            ).exists()
            unsuffixed_results_exists = (
                output_dir / "sample_benchmark_results.json"
            ).exists()

        self.assertEqual(rc, 0)
        self.assertEqual(pass1_calls, 2)
        self.assertEqual(pass2_calls, 2)
        self.assertTrue(run01_pass1_exists)
        self.assertTrue(run02_pass1_exists)
        self.assertTrue(run01_results_exists)
        self.assertTrue(run02_results_exists)
        self.assertFalse(unsuffixed_results_exists)
        self.assertEqual(summary["metadata"]["metric"], "Pass^2")
        self.assertEqual(summary["overall"]["strict_pass_k_count"], 1)
        self.assertEqual(summary["hard_failures"][0]["test_case_id"], "TC-02")

    def test_pipeline_forwards_passk_flags_to_step6(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "test_persona_seed.json"
            write_json(seed_path, {"persona": "Test Persona teaches.", "uuid": "u-1"})
            with patch.object(
                pipeline.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as proc:
                pipeline.run_pipeline(
                    seed_path,
                    "codex",
                    "openai",
                    "gpt-5.5",
                    "gpt-5.5",
                    "gpt-5.5",
                    "gpt-5.4-mini",
                    None,
                    6,
                    6,
                    passk_runs=4,
                    passk_output=Path("output/pass4_summary.json"),
                    passk_allow_missing=True,
                )

        cmd = proc.call_args.args[0]
        self.assertIn("--passk-runs", cmd)
        self.assertEqual(cmd[cmd.index("--passk-runs") + 1], "4")
        self.assertIn("--passk-output", cmd)
        self.assertEqual(
            cmd[cmd.index("--passk-output") + 1],
            "output\\pass4_summary.json" if sys.platform == "win32"
            else "output/pass4_summary.json",
        )
        self.assertIn("--passk-allow-missing", cmd)
        # The evaluated model answers Pass 1; the judge scores Pass 2.
        self.assertEqual(cmd[cmd.index("--model-pass1") + 1], "gpt-5.4-mini")
        self.assertEqual(cmd[cmd.index("--model-pass2") + 1], "gpt-5.5")
        # Pass 1 uses the evaluation reasoning effort, Pass 2 the
        # generation/judge effort, matching the documented defaults.
        self.assertEqual(cmd[cmd.index("--reasoning-pass1") + 1], "low")
        self.assertEqual(cmd[cmd.index("--reasoning-pass2") + 1], "high")


if __name__ == "__main__":
    unittest.main()
