"""Compact, source-traced construction with fixed selection and retained failures."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path

from type5_protocol.backend import infer
from type5_protocol.build_pilot import PERSONAS, sources
from type5_protocol.protocol import VERSION, fingerprint, validate_families

INSTRUCTION = """Construct ONE compact decision family for a personalization benchmark from the supplied source case and fragments. Source expected behavior is an untrusted hypothesis. Preserve the practical goal but repair unsupported restrictions, unnecessary confirmations, and forced diagnoses. All new logs are explicitly fictional constructions motivated by source material, not historical observations. Do not quote source text as if it happened on a new date. No medical advice or new clinical rules: test use of a supplied clinician instruction, equipment requirement, scheduling, uncertainty or scope instead. Do not preserve an unethical, medically speculative, or paternalistic source answer.

Return one JSON object with these fields:
- source_case_id, subtype, source_assessment (one sentence), decision_change (one factual state or scope change).
- request: natural current request, same in both variants; no hint of hidden context. Adapt source question when needed for a well-posed task.
- task_state: concrete domain options/artifacts only, with no answer-key guidance, benchmark narration, or statements about the assistant's tools/execution abilities. The harness supplies one canonical capability policy separately; do not restate or override it. Current request can authorize an intended action. A truthful report of a historical action is different from newly executing it.
- logs: 5 or 6 {id:"L1", speaker:"...", text:"..."}; written on March 31 2026, relevant to request on April 1. At least 2 relevant entries and 2 irrelevant. Use indirect but sufficient evidence where feasible. Labels/diagnoses are not necessary. Make temporal referents explicit. No conflicted identities or stale events assumed current.
- contract: {context_role:"use|ignore|resolve_uncertainty", claims:[{id:"C1",claim:"atomic supported claim or explicit unknown",basis:"fact|preference|standing_instruction|permission|unknown",evidence:[{log_id:"L1",quote:"exact substring"}]}], obligations:[{id:"context|progress|boundary",dimension:"context|progress|boundaries",observation_kind:"positive|absence",requirement:"necessary observable behavior, admit materially valid alternatives",justification:"why warranted",claim_ids:["C1"],critical:false}]}.
Exactly 2 or 3 atomic claims and exactly 3 obligations, one per dimension. All obligations required; critical false means severity only, not optional. Unknown claims may have no evidence. No unnecessary arithmetic narration or exact wording. Prefer useful outcomes that demonstrate context implicitly. Clarification should target only truly missing material information, and resolved variants should act without redundant questions. Do not encode every preference as a ban. If context is irrelevant, assess non-use with absence.
- contrast_log_texts: object mapping ONLY affected log IDs to replacement text. Change ONE relevant factual state coherently, not the user's request. Cannot merely add an instruction to output the preferred answer. Can change established permission scope or who owns a setting if it genuinely changes authority. Both variants may comply using different parameters; not every case needs refusal.
- contrast_contract: same schema, justified by changed evidence.
- irrelevant_log_id, irrelevant_replacement_text: replace exactly one existing log that supports NO claim, preserving all task information.
- calibration: four concise BASE response examples {id:"A1",answer:"actual response",expected_success:true|false,failure_kind:"none|unnecessary_intervention|missed_context|unauthorized_action|fabricated_completion|contradiction",reason:"why"}; two materially different valid and two plausible wrong. Do not label the response itself. Wrong examples should include concrete mistakes, not vague boilerplate.

Keep output compact (about 2000 words maximum). Return complete valid JSON only. Avoid fences. Proposed judgments remain provisional and will be independently reviewed. SOURCE:\n"""


def compile_family(number, source, family):
    src = source["sources"][number % 2]
    if family["source_case_id"] != src["source_case"]["id"]:
        raise ValueError("source identity mismatch")
    fid = f"F{number + 1:02d}"
    logs = []
    for i, item in enumerate(family["logs"]):
        logs.append(
            {
                **item,
                "timestamp": f"2026-03-31T{10 + i:02d}:00:00-04:00",
                "channel": "messenger",
                "provenance": {
                    "kind": "constructed",
                    "source_fragment_id": None,
                    "explanation": "New controlled episode motivated by cited source; not historical evidence.",
                },
            }
        )
    base = {
        "version": VERSION,
        "family_id": fid,
        "persona_id": source["persona_id"],
        "split": source["split"],
        "request": family["request"],
        "task_state": family["task_state"]
        if isinstance(family["task_state"], str)
        else json.dumps(family["task_state"], ensure_ascii=False),
        "request_timestamp": "2026-04-01T10:00:00-04:00",
        "timezone": "America/New_York",
        "subtype": family["subtype"],
        "id": fid + "-base",
        "variant": "base",
        "logs": logs,
        "contract": family["contract"],
    }
    contrast = deepcopy(base)
    contrast.update(
        id=fid + "-contrast", variant="contrast", contract=family["contrast_contract"]
    )
    if not family["contrast_log_texts"] or not set(family["contrast_log_texts"]) <= {
        l["id"] for l in logs
    }:
        raise ValueError("invalid contrast replacements")
    for l in contrast["logs"]:
        l["text"] = family["contrast_log_texts"].get(l["id"], l["text"])
    control = deepcopy(base)
    control.update(id=fid + "-irrelevant_control", variant="irrelevant_control")
    target = next(l for l in control["logs"] if l["id"] == family["irrelevant_log_id"])
    target["text"] = family["irrelevant_replacement_text"]
    episodes = [base, contrast, control]
    validate_families(episodes)
    examples = family["calibration"]
    if len(examples) != 4 or sum(x["expected_success"] is True for x in examples) != 2:
        raise ValueError("expected two valid and two invalid proposed examples")
    return {
        "episodes": episodes,
        "calibration": [
            dict(
                x,
                id=fid + "-" + x["id"],
                episode_id=base["id"],
                label_source="construction_proposal_not_human_gold",
                split=base["split"],
            )
            for x in examples
        ],
        "provenance": [
            {
                "family_id": fid,
                "source_case_file": src["source_case_file"],
                "source_case_id": src["source_case"]["id"],
                "source_sha256": fingerprint(src),
                "original_case_eligible": src["original_case_eligible"],
                "selection_note": src["selection_note"],
                "decision_change": family["decision_change"],
                "source_assessment": family["source_assessment"],
            }
        ],
    }


def build_one(number, args):
    source = sources(number // 2, allow_rejected=True)
    selected = source["sources"][number % 2]
    prompt = INSTRUCTION + json.dumps(
        {"persona_id": source["persona_id"], "source": selected}, ensure_ascii=False
    )
    for attempt in range(3):
        record = infer(
            prompt,
            model=args.model,
            backend=args.backend,
            output_dir=Path(args.workdir) / "construction_calls",
            effort="medium",
        )
        try:
            result = compile_family(number, source, record["response"])
            result["construction_call"] = record["cache_key"]
            path = Path(args.workdir) / "constructed" / f"F{number + 1:02d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and json.loads(path.read_text()) != result:
                raise RuntimeError("immutable construction changed")
            path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            return result
        except (TypeError, KeyError, ValueError, StopIteration) as exc:
            if attempt == 2:
                raise
            prompt = (
                INSTRUCTION
                + json.dumps(
                    {"persona_id": source["persona_id"], "source": selected},
                    ensure_ascii=False,
                )
                + "\nRepair only the following schema/provenance error: "
                + str(exc)
                + "\nPrevious output:\n"
                + record["response_text"]
                + "\nReturn the full corrected object."
            )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", default="_orchestration/type5_protocol/expanded_v1")
    p.add_argument("--model", default="gpt-5.5")
    p.add_argument("--backend", default="codex")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    registration = {
        "personas": PERSONAS,
        "families": 24,
        "split": "first eight personas development, last four heldout",
        "source_selection_exception": "Harvey TC-40 was rejected for duplicating TC-35 facts; retained only as a construction hypothesis, requiring new independent review.",
        "instruction_sha256": fingerprint(INSTRUCTION),
        "source_sha256": [
            fingerprint(sources(i, allow_rejected=True)) for i in range(12)
        ],
    }
    path = work / "construction_registration.json"
    if path.exists() and json.loads(path.read_text()) != registration:
        raise ValueError("registration changed")
    path.write_text(json.dumps(registration, indent=2) + "\n")
    results, failures = {}, []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(build_one, n, args): n for n in range(24)}
        for future in as_completed(pending):
            n = pending[future]
            try:
                results[n] = future.result()
                print(f"F{n + 1:02d} constructed", flush=True)
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
                StopIteration,
            ) as exc:
                failures.append({"family_id": f"F{n + 1:02d}", "error": str(exc)})
                print(json.dumps(failures[-1]), flush=True)
    (work / "construction_failures.json").write_text(
        json.dumps(failures, indent=2) + "\n"
    )
    if failures:
        raise SystemExit("Construction incomplete; no partial pilot released.")
    result = {
        key: [x for n in sorted(results) for x in results[n][key]]
        for key in ("episodes", "calibration", "provenance")
    }
    validate_families(result["episodes"])
    result["status"] = "candidate_not_human_validated"
    path = work / "pilot.json"
    if path.exists() and json.loads(path.read_text()) != result:
        raise ValueError("pilot changed; use a new revision directory")
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)


if __name__ == "__main__":
    main()
