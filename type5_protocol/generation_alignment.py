"""Separate full-claim observability from the existing implicitness gate."""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from step4_app_log_synthesizer import generator
from step4_app_log_synthesizer.evidence_alignment import accepted_alignment
from type5_protocol.backend import infer
from type5_protocol.protocol import fingerprint


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--workdir", default="_orchestration/type5_protocol/generation_probe_v1"
    )
    a = p.parse_args()
    work = Path(a.workdir)

    def call(client, model, prompt, reasoning, **kwargs):
        return infer(
            prompt,
            model=model,
            backend="codex",
            output_dir=work / "alignment_calls",
            effort=reasoning,
        )["response_text"]

    results = []
    with patch.object(generator, "call_llm", call):
        for path in sorted(work.glob("C*.json")):
            source = json.loads(path.read_text())
            blind = deepcopy(source["blind"])
            fragments = source["bundle"]["fragments"]
            facts = source["facts"]
            result = {
                "cluster_id": source["cluster"]["cluster_id"],
                "source_trial_sha256": fingerprint(source),
                "strict_implicit_gate_passed": source["strict_passed"],
            }
            try:
                blind["fact_alignment"] = generator.verify_fact_alignment(
                    None, "gpt-5.5", fragments, blind, facts, "high", "openai", "cli"
                )
                result.update(
                    full_claims_supported=accepted_alignment(blind, facts, fragments),
                    alignment=blind["fact_alignment"],
                )
            except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                result["error"] = str(exc)
            results.append(result)
            print(
                json.dumps(
                    {
                        "id": result["cluster_id"],
                        "full_claims_supported": result.get("full_claims_supported"),
                        "error": result.get("error"),
                    }
                ),
                flush=True,
            )
    payload = {
        "purpose": "Diagnostic only: explicit evidence can be valid even when it is easy. This does not override strict production admission or establish case-action validity.",
        "results": results,
    }
    (work / "observability_diagnostic.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )


if __name__ == "__main__":
    main()
