"""Fresh production fragment-generation trials with isolated CLI inference."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from step4_app_log_synthesizer import generator
from type5_protocol.backend import infer
from type5_protocol.protocol import fingerprint

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--workdir", default="_orchestration/type5_protocol/generation_probe_v1"
    )
    a = p.parse_args()
    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    profile = json.loads(
        (
            ROOT / "step2_interview/data_samples/bernadette_gangaram_interview.json"
        ).read_text()
    )["extracted_profile"]
    social = json.loads(
        (
            ROOT
            / "step3_social_circle/data_samples/bernadette_gangaram_social_circle.json"
        ).read_text()
    )
    app = json.loads(
        (
            ROOT
            / "step4_app_log_synthesizer/data_samples/bernadette_gangaram_app_logs.json"
        ).read_text()
    )
    facts = {
        f["fact_id"]: {
            k: f[k]
            for k in (
                "fact_id",
                "claim",
                "ground_truth_label",
                "category",
                "subcategory",
            )
        }
        for f in app["hidden_facts"]
    }
    trace = json.loads(
        (
            ROOT
            / "step4_app_log_synthesizer/data_samples/bernadette_gangaram_app_logs_trace.json"
        ).read_text()
    )
    clusters = [c for c in trace if c["cluster_id"] in ("C1", "C2", "C6")]
    registration = {
        "selected_clusters": ["C1", "C2", "C6"],
        "purpose": "Three deliberately selected fresh generation diagnostics: broad negative health claim, daily routines, insurance/cost. Not a corpus-wide acceptance estimate.",
        "attempts_per_cluster": 1,
        "source_sha256": fingerprint(
            {"profile": profile, "social": social, "facts": facts}
        ),
        "generator": "claude-sonnet-4-6",
        "verifier": "gpt-5.5",
        "gate": "strict",
    }
    (work / "registration.json").write_text(json.dumps(registration, indent=2) + "\n")

    def call(client, model, prompt, reasoning, **kwargs):
        record = infer(
            prompt,
            model=model,
            backend="codex" if model == "gpt-5.5" else "claude",
            output_dir=work / "calls",
            effort=reasoning,
        )
        return record["response_text"]

    def trial(cluster):
        selected = [facts[fid] for fid in cluster["hidden_fact_ids"]]
        base = {
            "cluster_id": cluster["cluster_id"],
            "cluster_status": "valid_cluster",
            "hidden_fact_ids": cluster["hidden_fact_ids"],
        }
        out = {"cluster": base, "facts": selected}
        try:
            bundle = generator.generate_cluster_fragments(
                None,
                "claude-sonnet-4-6",
                base,
                selected,
                social,
                "2026-03-01",
                "2026-03-29",
                {},
                "medium",
                "anthropic",
                "cli",
            )
            fragments = bundle["fragments"]
            out["bundle"] = bundle
            blind = generator.verify_cluster(
                None,
                "gpt-5.5",
                fragments,
                generator.derive_persona_identity(profile),
                len(selected),
                "high",
                "openai",
                "cli",
            )
            out["blind"] = blind
            clean = (
                blind.get("verdict") == "RECOVERED"
                and not generator._has_implicitness_leaks(blind)
                and generator._all_candidates_high_confidence(blind)
                and not generator._shared_evidence_failed(blind)
            )
            out["pre_alignment_gate"] = clean
            if clean:
                blind["fact_alignment"] = generator.verify_fact_alignment(
                    None, "gpt-5.5", fragments, blind, selected, "high", "openai", "cli"
                )
            out["strict_passed"], out["matches"] = generator.cluster_passed(
                blind, selected, policy="strict", fragments=fragments
            )
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            out["error"] = str(exc)
        (work / (cluster["cluster_id"] + ".json")).write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n"
        )
        print(
            json.dumps(
                {
                    "id": cluster["cluster_id"],
                    "strict_passed": out.get("strict_passed"),
                    "pre_alignment_gate": out.get("pre_alignment_gate"),
                    "error": out.get("error"),
                }
            ),
            flush=True,
        )
        return out

    with (
        patch.object(generator, "call_llm", call),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(trial, clusters))
    summary = {
        "intended": 3,
        "strict_passes": sum(r.get("strict_passed") is True for r in results),
        "errors": sum("error" in r for r in results),
        "scope": "Fresh fragment generation -> blind recovery -> conditional semantic alignment -> strict admission. Final filler assembly and population throughput are not measured.",
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
