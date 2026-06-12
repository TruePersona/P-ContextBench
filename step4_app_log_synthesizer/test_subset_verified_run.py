from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from .subset_verified_run import (
        build_cluster_subset_app_log,
        select_fragment_subset,
        select_trace_subset,
        write_cluster_subset,
    )
except ImportError:
    from subset_verified_run import (
        build_cluster_subset_app_log,
        select_fragment_subset,
        select_trace_subset,
        write_cluster_subset,
    )


def _profile() -> dict:
    return {
        "name": "Test Person",
        "age": 42,
        "occupation": "planner",
        "location": "Michigan",
        "hidden_facts": [
            {
                "fact_id": f"HF-{idx:03d}",
                "claim": f"Test claim {idx}",
                "ground_truth_label": f"test label {idx}",
                "category": "behavioral",
                "subcategory": "routine",
            }
            for idx in range(1, 6)
        ],
    }


def _social_circle() -> dict:
    return {
        "social_circle": [
            {"name": "Taylor Morgan", "relationship": "friend"},
        ]
    }


def _trace() -> list[dict]:
    return [
        {
            "cluster_id": "C1",
            "hidden_fact_ids": ["HF-001", "HF-002"],
            "attempts": 1,
            "passed": True,
            "per_fact_recovery": [],
        },
        {
            "cluster_id": "C2",
            "hidden_fact_ids": ["HF-003", "HF-004"],
            "attempts": 1,
            "passed": True,
            "per_fact_recovery": [],
        },
        {
            "cluster_id": "C3",
            "hidden_fact_ids": ["HF-005"],
            "attempts": 3,
            "passed": False,
            "per_fact_recovery": [],
        },
    ]


def _fragment(cluster: str, idx: int, fact_ids: list[str]) -> dict:
    text = (
        f"Cluster {cluster} fragment {idx} carries a detailed routine signal "
        f"for {' and '.join(fact_ids)} with enough words for stable assembly."
    )
    return {
        "fragment_id": f"{cluster}-F{idx}",
        "fragment_type": "messenger_session",
        "date": f"2026-03-{idx:02d}",
        "source": {"type": "contact", "name": "Taylor Morgan"},
        "messages": [
            {"time": "09:00", "sender": "Taylor Morgan", "text": text},
            {
                "time": "09:03",
                "sender": "Persona",
                "text": (
                    f"I saw the note for {cluster} and will handle the related "
                    "details after lunch today."
                ),
            },
        ],
        "calendar_event": None,
        "supports_hidden_facts": [
            {"hidden_fact_id": fid, "signal_strength": "primary"}
            for fid in fact_ids
        ],
        "pipeline_notes_only": "",
        "source_fact_ids": fact_ids,
    }


def _fragments() -> list[dict]:
    return [
        _fragment("C1", 1, ["HF-001", "HF-002"]),
        _fragment("C1", 2, ["HF-001", "HF-002"]),
        _fragment("C2", 3, ["HF-003", "HF-004"]),
        _fragment("C2", 4, ["HF-003", "HF-004"]),
        _fragment("C3", 5, ["HF-005"]),
    ]


class ClusterSubsetTests(unittest.TestCase):
    def test_select_trace_subset_uses_passed_clusters_only(self) -> None:
        selected = select_trace_subset(_trace(), 2)

        self.assertEqual([entry["cluster_id"] for entry in selected], ["C1", "C2"])

    def test_build_cluster_subset_app_log_is_no_llm_and_valid(self) -> None:
        app_log, selected_trace, selected_fragments = build_cluster_subset_app_log(
            corrected_profile=_profile(),
            corrected_social_circle=_social_circle(),
            trace=_trace(),
            fragments=_fragments(),
            cluster_count=2,
            log_start="2026-03-01",
            log_end="2026-03-31",
            filler_ratio=2.5,
            target_context_tokens=None,
        )

        self.assertEqual(app_log["_validation"]["verdict"], "PASS")
        self.assertEqual(app_log["_cluster_subset"]["cluster_count"], 2)
        self.assertEqual(app_log["_cluster_subset"]["hidden_fact_count"], 4)
        self.assertEqual(len(selected_trace), 2)
        self.assertEqual({f["fragment_id"] for f in selected_fragments}, {
            "C1-F1", "C1-F2", "C2-F3", "C2-F4",
        })
        self.assertEqual(
            {hf["fact_id"] for hf in app_log["hidden_facts"]},
            {"HF-001", "HF-002", "HF-003", "HF-004"},
        )

    def test_write_cluster_subset_outputs_named_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            record = write_cluster_subset(
                corrected_profile=_profile(),
                corrected_social_circle=_social_circle(),
                trace=_trace(),
                fragments=_fragments(),
                cluster_count=1,
                output_dir=Path(tmp_dir),
                base_name="test_person",
                log_start="2026-03-01",
                log_end="2026-03-31",
                filler_ratio=2.5,
                target_context_tokens=None,
            )

            self.assertEqual(record["validation"], "PASS")
            self.assertEqual(record["cluster_count"], 1)
            self.assertEqual(record["hidden_fact_count"], 2)
            self.assertTrue(Path(record["app_log_path"]).name.endswith(
                "test_person_c1_hf2_app_logs.json"
            ))
            self.assertTrue(Path(record["trace_path"]).exists())
            self.assertTrue(Path(record["fragments_path"]).exists())

    def test_fragment_subset_rejects_fact_leakage(self) -> None:
        trace = select_trace_subset(_trace(), 1)
        fragments = [_fragment("C1", 1, ["HF-001", "HF-099"])]

        with self.assertRaises(ValueError):
            select_fragment_subset(fragments, trace)


if __name__ == "__main__":
    unittest.main()
