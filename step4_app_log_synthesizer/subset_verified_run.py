"""Build smaller Step 4 app logs by subsetting verified clusters.

This helper performs no LLM calls. It reuses a larger verified Step 4 run as
the source of truth, selects whole passed clusters, and reassembles a fresh
app log plus matching trace/fragments artifacts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .generator import (
        _build_hidden_facts_registry,
        assemble_final_log,
        assemble_meaningful_log,
        build_filler_with_decoys,
        derive_persona_identity,
        validate_final_log,
        validate_meaningful_preservation,
    )
except ImportError:
    from generator import (
        _build_hidden_facts_registry,
        assemble_final_log,
        assemble_meaningful_log,
        build_filler_with_decoys,
        derive_persona_identity,
        validate_final_log,
        validate_meaningful_preservation,
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fragment_cluster_id(fragment: dict[str, Any]) -> str:
    fragment_id = str(fragment.get("fragment_id", ""))
    if "-F" in fragment_id:
        return fragment_id.split("-F", 1)[0]
    return str(fragment.get("cluster_id") or fragment.get("source_cluster_id") or "")


def _cluster_label(cluster_count: int | None) -> str:
    return "cAll" if cluster_count is None else f"c{cluster_count}"


def parse_cluster_count(value: str) -> int | None:
    if value.lower() == "all":
        return None
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("--cluster-count must be positive or all")
    return parsed


def select_trace_subset(
    trace: list[dict[str, Any]],
    cluster_count: int | None,
) -> list[dict[str, Any]]:
    passed_trace = [entry for entry in trace if entry.get("passed")]
    if cluster_count is None:
        return passed_trace
    if cluster_count > len(passed_trace):
        raise ValueError(
            f"requested {cluster_count} clusters but only "
            f"{len(passed_trace)} passed clusters are available"
        )
    return passed_trace[:cluster_count]


def select_fragment_subset(
    fragments: list[dict[str, Any]],
    selected_trace: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_cluster_ids = {
        str(entry.get("cluster_id", "")) for entry in selected_trace
    }
    selected_fact_ids = {
        fid
        for entry in selected_trace
        for fid in entry.get("hidden_fact_ids", [])
    }

    selected_fragments: list[dict[str, Any]] = []
    leaking_fragments: list[str] = []
    for fragment in fragments:
        cluster_id = _fragment_cluster_id(fragment)
        if cluster_id not in selected_cluster_ids:
            continue
        source_fact_ids = set(fragment.get("source_fact_ids", []))
        if not source_fact_ids <= selected_fact_ids:
            leaking_fragments.append(str(fragment.get("fragment_id", "")))
            continue
        selected_fragments.append(fragment)

    if leaking_fragments:
        raise ValueError(
            "selected cluster fragments reference hidden facts outside the "
            f"cluster subset: {leaking_fragments[:10]}"
        )

    fragment_cluster_ids = {
        _fragment_cluster_id(fragment) for fragment in selected_fragments
    }
    missing_clusters = sorted(selected_cluster_ids - fragment_cluster_ids)
    if missing_clusters:
        raise ValueError(
            f"selected clusters have no verified fragments: {missing_clusters[:10]}"
        )

    covered_fact_ids = {
        fid
        for fragment in selected_fragments
        for fid in fragment.get("source_fact_ids", [])
    }
    missing_fact_ids = sorted(selected_fact_ids - covered_fact_ids)
    if missing_fact_ids:
        raise ValueError(
            "selected clusters have hidden facts with no selected fragment "
            f"coverage: {missing_fact_ids[:10]}"
        )

    return selected_fragments


def build_cluster_subset_app_log(
    *,
    corrected_profile: dict[str, Any],
    corrected_social_circle: dict[str, Any],
    trace: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
    cluster_count: int | None,
    log_start: str,
    log_end: str,
    filler_ratio: float,
    target_context_tokens: int | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    selected_trace = select_trace_subset(trace, cluster_count)
    if not selected_trace:
        raise ValueError("cluster subset is empty")

    selected_fact_ids = {
        fid
        for entry in selected_trace
        for fid in entry.get("hidden_fact_ids", [])
    }
    hidden_facts = [
        hf
        for hf in corrected_profile.get("hidden_facts", [])
        if hf.get("fact_id") in selected_fact_ids
    ]
    if {hf.get("fact_id") for hf in hidden_facts} != selected_fact_ids:
        missing = sorted(selected_fact_ids - {hf.get("fact_id") for hf in hidden_facts})
        raise ValueError(f"profile is missing selected hidden facts: {missing[:10]}")

    selected_fragments = select_fragment_subset(fragments, selected_trace)
    persona = derive_persona_identity(corrected_profile)

    partial_log, provenance, fragment_placement = assemble_meaningful_log(
        selected_fragments, persona, log_start, log_end,
    )
    preservation = validate_meaningful_preservation(
        partial_log, selected_fragments, persona["name"],
    )
    if not preservation["passed"]:
        raise ValueError(f"subset preservation failed: {preservation}")

    meaningful_tokens = len(
        json.dumps(
            partial_log["messenger"]["meaningful_sessions"],
            ensure_ascii=False,
        )
    ) // 4
    filler_sessions, decoy_registry, decoy_tokens, mundane_tokens = (
        build_filler_with_decoys(
            persona,
            corrected_social_circle,
            log_start,
            log_end,
            meaningful_tokens,
            filler_ratio,
            target_context_tokens,
            hidden_facts,
            verified_decoy_pool=[],
            decoy_count=0,
        )
    )

    registry = _build_hidden_facts_registry(hidden_facts, selected_trace)
    app_log = assemble_final_log(
        partial_log,
        filler_sessions,
        registry,
        provenance,
        selected_trace,
        selected_fragments,
        fragment_placement,
        target_filler_ratio=filler_ratio,
        decoy_registry=decoy_registry,
        decoy_filler_token_count=decoy_tokens,
        mundane_filler_token_count=mundane_tokens,
    )
    validation = validate_final_log(
        app_log,
        selected_fragments,
        selected_trace,
        target_filler_ratio=(
            filler_ratio if target_context_tokens is None else None
        ),
    )
    app_log["_validation"] = validation
    app_log["_cluster_subset"] = {
        "cluster_count_requested": (
            "all" if cluster_count is None else cluster_count
        ),
        "cluster_count": len(selected_trace),
        "hidden_fact_count": len(selected_fact_ids),
        "selected_cluster_ids": [
            str(entry.get("cluster_id", "")) for entry in selected_trace
        ],
        "selection_policy": "first_passed_clusters_in_trace_order",
        "llm_calls": 0,
    }
    return app_log, selected_trace, selected_fragments


def write_cluster_subset(
    *,
    corrected_profile: dict[str, Any],
    corrected_social_circle: dict[str, Any],
    trace: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
    cluster_count: int | None,
    output_dir: Path,
    base_name: str,
    log_start: str,
    log_end: str,
    filler_ratio: float,
    target_context_tokens: int | None,
) -> dict[str, Any]:
    app_log, selected_trace, selected_fragments = build_cluster_subset_app_log(
        corrected_profile=corrected_profile,
        corrected_social_circle=corrected_social_circle,
        trace=trace,
        fragments=fragments,
        cluster_count=cluster_count,
        log_start=log_start,
        log_end=log_end,
        filler_ratio=filler_ratio,
        target_context_tokens=target_context_tokens,
    )

    hidden_fact_count = app_log["_cluster_subset"]["hidden_fact_count"]
    label = _cluster_label(cluster_count)
    output_stem = f"{base_name}_{label}_hf{hidden_fact_count}"

    app_log_path = output_dir / f"{output_stem}_app_logs.json"
    trace_path = output_dir / f"{output_stem}_app_logs_trace.json"
    fragments_path = output_dir / f"{output_stem}_verified_fragments.json"

    app_log_path.write_text(
        json.dumps(app_log, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    trace_path.write_text(
        json.dumps(selected_trace, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    fragments_path.write_text(
        json.dumps(selected_fragments, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    validation = app_log.get("_validation", {})
    return {
        "cluster_count_requested": "all" if cluster_count is None else cluster_count,
        "cluster_count": len(selected_trace),
        "hidden_fact_count": hidden_fact_count,
        "approximate_tokens": app_log.get("token_stats", {}).get(
            "approximate_tokens"
        ),
        "validation": validation.get("verdict"),
        "app_log_path": str(app_log_path),
        "trace_path": str(trace_path),
        "fragments_path": str(fragments_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build no-LLM Step 4 app log subsets from whole verified clusters."
        )
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--social-circle", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--fragments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cluster-count",
        action="append",
        type=parse_cluster_count,
        required=True,
        help="Number of passed clusters to keep, or all. Repeat for c10/c20/cAll.",
    )
    parser.add_argument("--base-name", default=None)
    parser.add_argument("--log-start", default="2026-03-01")
    parser.add_argument("--log-end", default="2026-03-31")
    parser.add_argument("--filler-ratio", type=float, default=2.5)
    parser.add_argument("--target-context-tokens", type=int, default=None)
    parser.add_argument("--summary-out", type=Path, default=None)
    args = parser.parse_args()

    profile = _load_json(args.profile)
    circle = _load_json(args.social_circle)
    trace = _load_json(args.trace)
    fragments = _load_json(args.fragments)

    corrected_profile = profile["corrected_extracted_profile"]
    corrected_social_circle = circle["corrected_social_circle"]
    base_name = args.base_name or args.profile.stem.replace("_verification", "")
    args.output.mkdir(parents=True, exist_ok=True)

    summary = []
    for cluster_count in args.cluster_count:
        record = write_cluster_subset(
            corrected_profile=corrected_profile,
            corrected_social_circle=corrected_social_circle,
            trace=trace,
            fragments=fragments,
            cluster_count=cluster_count,
            output_dir=args.output,
            base_name=base_name,
            log_start=args.log_start,
            log_end=args.log_end,
            filler_ratio=args.filler_ratio,
            target_context_tokens=args.target_context_tokens,
        )
        summary.append(record)
        print(
            "[step4/subset] wrote "
            f"{record['app_log_path']} "
            f"({record['cluster_count']} clusters, "
            f"{record['hidden_fact_count']} hidden facts, "
            f"validation={record['validation']})"
        )

    summary_out = args.summary_out or args.output / f"{base_name}_cluster_subsets_summary.json"
    summary_out.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0 if all(record["validation"] == "PASS" for record in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
