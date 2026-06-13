from __future__ import annotations

import unittest
from pathlib import Path

import openclaw_pipeline
from output_naming import (
    experiment_suffix,
    step4_app_logs_filename,
    step4_fragments_filename,
    step4_trace_filename,
    step5_test_cases_filename,
    step5_verification_filename,
    step6_output_names,
    step6_passk_summary_filename,
    verification_path_for_test_cases,
)


class OutputNamingTests(unittest.TestCase):
    def test_step4_names_include_decoy_filler_and_hidden_fact_count(self) -> None:
        self.assertEqual(
            openclaw_pipeline.app_log_base("Alice Gonzalez", 0, 2.5, 100),
            "alice_gonzalez_decoy0_filler2.5_hf100",
        )
        self.assertEqual(
            step4_app_logs_filename("Alice Gonzalez", 0, 2.5, 100),
            "alice_gonzalez_decoy0_filler2.5_hf100_app_logs.json",
        )
        self.assertEqual(
            step4_app_logs_filename("Alice Gonzalez", 75, 2.5, 100),
            "alice_gonzalez_decoy75_filler2.5_hf100_app_logs.json",
        )
        self.assertEqual(
            step4_trace_filename("Alice Gonzalez", 100),
            "alice_gonzalez_app_logs_trace_hf100.json",
        )
        self.assertEqual(
            step4_fragments_filename("Alice Gonzalez", 100),
            "alice_gonzalez_verified_fragments_hf100.json",
        )

    def test_step5_names_only_include_hidden_fact_count(self) -> None:
        self.assertEqual(
            step5_test_cases_filename("Alice Gonzalez", 100),
            "alice_gonzalez_test_cases_hf100.json",
        )
        self.assertEqual(
            step5_verification_filename("Alice Gonzalez", 100),
            "alice_gonzalez_test_cases_verification_hf100.json",
        )

    def test_step6_names_derive_config_from_app_logs(self) -> None:
        app_logs = {
            "persona_name": "Alice Gonzalez",
            "hidden_facts": [{"fact_id": f"HF-{i:03d}"} for i in range(100)],
            "token_stats": {"target_filler_ratio": "2.5:1"},
            "decoy_check": {"selected_decoy_count": 0},
        }

        names = step6_output_names(app_logs)

        self.assertEqual(
            names.benchmark_results,
            "alice_gonzalez_test_case_benchmark_results_decoy0_filler2.5_hf100.json",
        )
        self.assertEqual(
            names.raw_logs,
            "alice_gonzalez_app_logs_raw_decoy0_filler2.5_hf100.txt",
        )
        self.assertEqual(
            names.pass1_answers,
            "alice_gonzalez_app_logs_pass1_answers_decoy0_filler2.5_hf100.json",
        )
        self.assertEqual(
            step6_passk_summary_filename(app_logs, 3),
            "alice_gonzalez_pass3_summary_decoy0_filler2.5_hf100.json",
        )

    def test_run_suffix_is_added_after_experiment_config(self) -> None:
        app_logs = {
            "persona_name": "Alice Gonzalez",
            "hidden_facts": [{"fact_id": "HF-001"}],
            "token_stats": {"ratio_filler_to_meaningful": "2.5:1"},
            "decoy_check": {"selected_decoy_count": 12},
        }

        names = step6_output_names(app_logs, run_index=2)

        self.assertEqual(
            names.pass1_answers,
            "alice_gonzalez_app_logs_pass1_answers_decoy12_filler2.5_hf1_run02.json",
        )
        self.assertEqual(
            names.benchmark_results,
            "alice_gonzalez_test_case_benchmark_results_decoy12_filler2.5_hf1_run02.json",
        )

    def test_verification_path_for_hidden_fact_suffixed_test_cases(self) -> None:
        self.assertEqual(
            verification_path_for_test_cases(Path("alice_gonzalez_test_cases_hf100.json")),
            Path("alice_gonzalez_test_cases_verification_hf100.json"),
        )
        self.assertEqual(
            verification_path_for_test_cases(Path("alice_gonzalez_test_cases.json")),
            Path("alice_gonzalez_test_cases_verification.json"),
        )

    def test_suffix_formats_whole_number_filler_ratio_compactly(self) -> None:
        self.assertEqual(experiment_suffix(0, 2.0, 100), "decoy0_filler2_hf100")


if __name__ == "__main__":
    unittest.main()
