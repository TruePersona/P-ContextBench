from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_FILLER_RATIO = 2.5


def persona_base(name: str) -> str:
    return name.lower().replace(" ", "_")


def format_filler_ratio(filler_ratio: float | int | str) -> str:
    if isinstance(filler_ratio, str):
        value = filler_ratio.strip()
        if value.endswith(":1"):
            value = value[:-2]
        return value
    return f"{float(filler_ratio):g}"


def experiment_suffix(
    decoy_count: int,
    filler_ratio: float | int | str,
    hidden_fact_count: int,
) -> str:
    return (
        f"decoy{int(decoy_count)}"
        f"_filler{format_filler_ratio(filler_ratio)}"
        f"_hf{int(hidden_fact_count)}"
    )


def step4_app_logs_stem(
    name: str,
    decoy_count: int,
    filler_ratio: float | int | str,
    hidden_fact_count: int,
) -> str:
    return f"{persona_base(name)}_{experiment_suffix(decoy_count, filler_ratio, hidden_fact_count)}"


def step4_app_logs_filename(
    name: str,
    decoy_count: int,
    filler_ratio: float | int | str,
    hidden_fact_count: int,
) -> str:
    return f"{step4_app_logs_stem(name, decoy_count, filler_ratio, hidden_fact_count)}_app_logs.json"


def step4_trace_filename(name: str, hidden_fact_count: int) -> str:
    return f"{persona_base(name)}_app_logs_trace_hf{int(hidden_fact_count)}.json"


def step4_fragments_filename(name: str, hidden_fact_count: int) -> str:
    return f"{persona_base(name)}_verified_fragments_hf{int(hidden_fact_count)}.json"


def step5_test_cases_filename(name: str, hidden_fact_count: int) -> str:
    return f"{persona_base(name)}_test_cases_hf{int(hidden_fact_count)}.json"


def step5_verification_filename(name: str, hidden_fact_count: int) -> str:
    return f"{persona_base(name)}_test_cases_verification_hf{int(hidden_fact_count)}.json"


def hidden_fact_count_from_app_logs(app_logs: dict[str, Any]) -> int:
    hidden_facts = app_logs.get("hidden_facts")
    return len(hidden_facts) if isinstance(hidden_facts, list) else 0


def decoy_count_from_app_logs(app_logs: dict[str, Any]) -> int:
    decoy_check = app_logs.get("decoy_check")
    if isinstance(decoy_check, dict):
        selected = decoy_check.get("selected_decoy_count")
        if selected is not None:
            return int(selected)

    token_stats = app_logs.get("token_stats")
    if isinstance(token_stats, dict):
        selected = token_stats.get("target_selected_decoy_count")
        if selected is not None:
            return int(selected)

    decoy_registry = app_logs.get("decoy_registry")
    if isinstance(decoy_registry, list):
        return len(decoy_registry)
    return 0


def filler_ratio_from_app_logs(app_logs: dict[str, Any]) -> str:
    token_stats = app_logs.get("token_stats")
    if isinstance(token_stats, dict):
        for key in ("target_filler_ratio", "ratio_filler_to_meaningful"):
            value = token_stats.get(key)
            if value is not None:
                return format_filler_ratio(value)
    return format_filler_ratio(DEFAULT_FILLER_RATIO)


def persona_base_from_app_logs(app_logs: dict[str, Any], fallback_path: Path | None = None) -> str:
    persona_name = app_logs.get("persona_name") or app_logs.get("name")
    if isinstance(persona_name, str) and persona_name.strip():
        return persona_base(persona_name)
    if fallback_path is not None:
        stem = fallback_path.stem
        stem = re.sub(r"_decoy\d+(_filler[^_]+)?_hf\d+_app_logs$", "", stem)
        stem = re.sub(r"_app_logs$", "", stem)
        return stem
    return "persona"


@dataclass(frozen=True)
class Step6OutputNames:
    raw_logs: str
    pass1_answers: str
    benchmark_results: str


def step6_output_names(
    app_logs: dict[str, Any],
    app_logs_path: Path | None = None,
    run_index: int | None = None,
) -> Step6OutputNames:
    base_name = persona_base_from_app_logs(app_logs, app_logs_path)
    config = experiment_suffix(
        decoy_count_from_app_logs(app_logs),
        filler_ratio_from_app_logs(app_logs),
        hidden_fact_count_from_app_logs(app_logs),
    )
    run_suffix = f"_run{run_index:02d}" if run_index is not None else ""
    return Step6OutputNames(
        raw_logs=f"{base_name}_app_logs_raw_{config}.txt",
        pass1_answers=f"{base_name}_app_logs_pass1_answers_{config}{run_suffix}.json",
        benchmark_results=f"{base_name}_test_case_benchmark_results_{config}{run_suffix}.json",
    )


def verification_path_for_test_cases(test_cases_path: Path) -> Path:
    stem = test_cases_path.stem
    match = re.match(r"^(?P<base>.+)_test_cases_hf(?P<hf>\d+)$", stem)
    if match:
        return test_cases_path.with_name(
            f"{match.group('base')}_test_cases_verification_hf{match.group('hf')}"
            f"{test_cases_path.suffix}"
        )
    if stem.endswith("_test_cases"):
        return test_cases_path.with_name(
            f"{stem.removesuffix('_test_cases')}_test_cases_verification"
            f"{test_cases_path.suffix}"
        )
    return test_cases_path.parent / test_cases_path.name.replace(
        "_test_cases.json", "_test_cases_verification.json"
    )
