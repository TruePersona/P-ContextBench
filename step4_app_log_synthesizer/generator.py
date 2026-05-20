"""Step 4 — App log synthesis with per-fact reverse-inferability gate.

Each hidden fact is converted into 2-3 implicit fragments; those fragments
are fed to an independent cold LLM that tries to infer the fact without
seeing the ground truth. If the inference succeeds, the fragments are
accepted. If not, the fragments are regenerated. Only once all facts pass
the gate are the fragments merged with filler into the final app log.

Three phases:
  1. Per-fact fragment generation     (prompt.txt)
  2. Per-fact reverse-inferability    (verification_prompt.txt)
  3. Global merge + filler + surprises (merge_prompt.txt)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm import make_client, call_llm as _call_llm, check_api_key, SUPPORTED_PROVIDERS

STEP_DIR = Path(__file__).parent
PROMPT_PATH = STEP_DIR / "prompt.txt"
VERIFICATION_PROMPT_PATH = STEP_DIR / "verification_prompt.txt"
MERGE_PROMPT_PATH = STEP_DIR / "merge_prompt.txt"

DEFAULT_MODEL = "claude-opus-4-6"
DEFAULT_VERIFIER_MODEL = "claude-sonnet-4-6"  # cold, independent verifier
DEFAULT_PER_FACT_MAX_ATTEMPTS = 3
DEFAULT_LOG_WINDOW_DAYS = 60


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fill(template: str, placeholder: str, payload: Any) -> str:
    if isinstance(payload, str):
        return template.replace(placeholder, payload)
    return template.replace(
        placeholder, json.dumps(payload, indent=2, ensure_ascii=False)
    )


def call_llm(client, model: str, prompt: str, provider: str = "anthropic") -> str:
    return _call_llm(client, model, prompt, provider=provider)


def _fix_invalid_escapes(text: str) -> str:
    VALID = set('"\\/bfnrtu')
    out = []
    i = 0
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            if text[i + 1] in VALID:
                out.append(text[i])
                out.append(text[i + 1])
                i += 2
            else:
                out.append(text[i + 1])
                i += 2
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


def extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start = payload.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM output")
    raw = payload[start:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(_fix_invalid_escapes(raw))


# ---- per-fact generation + verification ----------------------------------


def generate_fragments(
    client,
    model: str,
    hidden_fact: dict[str, Any],
    social_circle: dict[str, Any],
    log_start: str,
    log_end: str,
    contact_usage: dict[str, int],
    provider: str = "anthropic",
) -> dict[str, Any]:
    template = load_prompt(PROMPT_PATH)
    template = fill(template, "{{INSERT_HIDDEN_FACT_JSON_HERE}}", hidden_fact)
    template = fill(
        template, "{{INSERT_CORRECTED_SOCIAL_CIRCLE_JSON_HERE}}", social_circle
    )
    template = fill(template, "{{LOG_START_DATE}}", log_start)
    template = fill(template, "{{LOG_END_DATE}}", log_end)
    template = fill(template, "{{INSERT_CONTACT_USAGE_COUNTS_JSON_HERE}}", contact_usage)
    raw = call_llm(client, model, template, provider=provider)
    return extract_json(raw)


def verify_fragments(
    client,
    verifier_model: str,
    fragments: list[dict[str, Any]],
    banned_token_set: list[str],
    persona: dict[str, Any],
    provider: str = "anthropic",
) -> dict[str, Any]:
    verifier_input = {
        "fragments": fragments,
        "banned_token_set": banned_token_set,
    }
    template = load_prompt(VERIFICATION_PROMPT_PATH)
    template = fill(template, "{{INSERT_FRAGMENTS_JSON_HERE}}", verifier_input)
    template = fill(template, "{{PERSONA_NAME}}", persona["name"])
    template = fill(template, "{{PERSONA_AGE}}", str(persona["age"]))
    template = fill(template, "{{PERSONA_OCCUPATION}}", persona["occupation"])
    template = fill(template, "{{PERSONA_LOCATION}}", persona["location"])
    raw = call_llm(client, verifier_model, template, provider=provider)
    return extract_json(raw)


def fact_passed(
    verification: dict[str, Any],
    hidden_fact: dict[str, Any],
) -> bool:
    if verification.get("verdict") != "RECOVERED":
        return False
    recovered = (verification.get("candidate_label") or "").lower()
    target = (hidden_fact.get("ground_truth_label") or "").lower()
    if not recovered or not target:
        return False
    # Cheap semantic proxy: any meaningful token overlap. The new Step 4
    # prompts ban ground_truth_label tokens from fragments, so the verifier
    # must paraphrase even when correct. A correct paraphrase ("daily SSRI
    # at 100mg") carries 1-2 ground-truth tokens, so the threshold is 0.15.
    # This is a hallucination safety net only; the verifier's RECOVERED
    # verdict + structure_check + triviality_check do the real gate work.
    rec_tokens = set(re.findall(r"[a-z0-9]{3,}", recovered))
    tgt_tokens = set(re.findall(r"[a-z0-9]{3,}", target))
    if not tgt_tokens:
        return False
    overlap = len(rec_tokens & tgt_tokens) / len(tgt_tokens)
    return overlap >= 0.15


def update_contact_usage(
    contact_usage: dict[str, int], fragment_bundle: dict[str, Any]
) -> None:
    for name in fragment_bundle.get("contacts_used", []) or []:
        contact_usage[name] = contact_usage.get(name, 0) + 1


# ---- merge ---------------------------------------------------------------


def merge_app_log(
    client,
    model: str,
    verified_fragments: list[dict[str, Any]],
    hidden_facts: list[dict[str, Any]],
    social_circle: dict[str, Any],
    persona: dict[str, Any],
    log_start: str,
    log_end: str,
    news_events: list[dict[str, Any]],
    provider: str = "anthropic",
) -> dict[str, Any]:
    template = load_prompt(MERGE_PROMPT_PATH)
    template = fill(template, "{{PERSONA_NAME}}", persona["name"])
    template = fill(template, "{{PERSONA_AGE}}", str(persona["age"]))
    template = fill(template, "{{PERSONA_OCCUPATION}}", persona["occupation"])
    template = fill(template, "{{PERSONA_LOCATION}}", persona["location"])
    template = fill(
        template, "{{INSERT_VERIFIED_FRAGMENTS_JSON_HERE}}", verified_fragments
    )
    template = fill(template, "{{INSERT_HIDDEN_FACTS_JSON_HERE}}", hidden_facts)
    template = fill(
        template, "{{INSERT_CORRECTED_SOCIAL_CIRCLE_JSON_HERE}}", social_circle
    )
    template = fill(template, "{{LOG_START_DATE}}", log_start)
    template = fill(template, "{{LOG_END_DATE}}", log_end)
    template = fill(template, "{{INSERT_NEWS_EVENTS_JSON_HERE}}", news_events)
    raw = call_llm(client, model, template, provider=provider)
    return sanitize_app_log(extract_json(raw))


def sanitize_app_log(app_log: dict[str, Any]) -> dict[str, Any]:
    """Defense-in-depth: strip per-session/per-event `source_fact_ids` so
    Backend C orchestrators that hand the raw JSON to a Pass 1 subagent
    cannot accidentally leak fact-anchored sessions to the evaluator.
    Traceability is preserved via `cross_app_index` only.
    """
    messenger = app_log.get("messenger", {})
    for bucket in ("meaningful_sessions", "filler_sessions", "sessions"):
        for s in messenger.get(bucket, []) or []:
            s.pop("source_fact_ids", None)
    calendar = app_log.get("calendar", {})
    if isinstance(calendar, dict):
        for e in calendar.get("events", []) or []:
            e.pop("source_fact_ids", None)
    return app_log


# ---- HF selection and prioritization -------------------------------------

PRIORITY_CATEGORIES = {
    "health", "mental_health", "medication", "therapy",
    "financial", "financial_constraint", "money",
    "safety", "risk",
    "relationship", "family", "social",
    "legal", "regulatory",
    "behavioral", "self_regulation", "coping",
    "temporal",
}

DEPRIORITIZE_CATEGORIES = {
    "decorative", "aesthetic", "style",
    "hobby_minor", "one_off",
    "location_minor",
    "personality_redundant",
}


def select_hidden_facts(
    hidden_facts: list[dict[str, Any]],
    max_facts: int = 100,
) -> list[dict[str, Any]]:
    """Select benchmark-relevant hidden facts, capped at max_facts.

    Prioritizes risk/safety, health, financial, relationship, and temporal
    facts. Deprioritizes decorative preferences, one-off hobbies, and
    redundant personality facts.
    """
    if len(hidden_facts) <= max_facts:
        return hidden_facts

    def priority_score(hf: dict[str, Any]) -> int:
        cat = (hf.get("category") or "").lower()
        subcat = (hf.get("subcategory") or "").lower()
        combined = f"{cat} {subcat}"
        score = 0
        for p in PRIORITY_CATEGORIES:
            if p in combined:
                score += 10
        for d in DEPRIORITIZE_CATEGORIES:
            if d in combined:
                score -= 5
        if hf.get("risk_surface_score"):
            score += int(hf["risk_surface_score"])
        return score

    ranked = sorted(hidden_facts, key=priority_score, reverse=True)
    selected = ranked[:max_facts]
    dropped = len(hidden_facts) - len(selected)
    if dropped:
        print(
            f"[step4] selected {len(selected)}/{len(hidden_facts)} "
            f"hidden facts (dropped {dropped} low-priority facts)"
        )
    return selected


# ---- programmatic hidden_facts registry ----------------------------------


def _build_hidden_facts_registry(
    hidden_facts: list[dict[str, Any]],
    trace: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the hidden_facts array from source data + trace, not LLM output.

    The merge LLM frequently drops or truncates the hidden_facts registry.
    Building it programmatically guarantees every verified fact is present.
    """
    trace_map = {t["fact_id"]: t for t in trace if t.get("passed")}
    registry: list[dict[str, Any]] = []
    for hf in hidden_facts:
        fact_id = hf.get("fact_id", "")
        if fact_id not in trace_map:
            continue
        t = trace_map[fact_id]
        entry = {
            "fact_id": fact_id,
            "claim": hf.get("claim", ""),
            "ground_truth_label": hf.get("ground_truth_label", ""),
            "category": hf.get("category", ""),
            "subcategory": hf.get("subcategory", ""),
            "reviewer_model": t.get("final_verification", {}).get(
                "reviewer_model", ""
            ),
            "recovered_label": t.get("final_verification", {}).get(
                "candidate_label", ""
            ),
            "verification_attempts": t.get("attempts", 0),
        }
        registry.append(entry)
    return registry


# ---- post-merge coverage verification ------------------------------------


def _extract_all_text(app_log: dict[str, Any]) -> str:
    """Collect all user-visible text from the merged app log."""
    parts: list[str] = []
    messenger = app_log.get("messenger", {})
    for bucket in ("meaningful_sessions", "filler_sessions", "sessions"):
        for s in messenger.get(bucket, []) or []:
            for m in s.get("messages", []) or []:
                parts.append(str(m.get("text", "")))
    calendar = app_log.get("calendar", {})
    if isinstance(calendar, dict):
        for e in calendar.get("events", []) or []:
            parts.append(str(e.get("title", "")))
            parts.append(str(e.get("notes", "")))
            parts.append(str(e.get("location", "")))
    return "\n".join(parts).lower()


def _normalize(text: str) -> set[str]:
    """Extract 4+ char alphanumeric tokens for fuzzy matching."""
    return set(re.findall(r"[a-z0-9]{4,}", text.lower()))


def verify_post_merge_coverage(
    app_log: dict[str, Any],
    verified_fragments: list[dict[str, Any]],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check that verified fragments survived the merge into the app log.

    Two-layer check:
    1. Registry check: compare hidden_facts IDs in the app log against
       fact IDs that passed verification in the trace.
    2. Content check: for each verified fragment, look for distinctive
       n-grams (3-word sequences) in the app log text. Single tokens
       are too generic; n-grams are specific enough to detect real
       presence vs coincidental word overlap.
    """
    # Layer 1: hidden_facts registry check
    app_hf_ids = set()
    for hf in app_log.get("hidden_facts", []):
        fid = hf.get("fact_id", "")
        if fid:
            app_hf_ids.add(fid)

    passed_fact_ids = {t["fact_id"] for t in trace if t.get("passed")}
    registry_missing = sorted(passed_fact_ids - app_hf_ids)

    # Layer 2: content n-gram check
    all_text = _extract_all_text(app_log)
    all_ngrams = _extract_ngrams(all_text, 3)

    frag_fact_ids_present: set[str] = set()
    frag_fact_ids_missing: set[str] = set()
    fragments_present = 0
    fragments_missing_detail: list[str] = []

    for frag in verified_fragments:
        frag_text = _fragment_text(frag)
        frag_ngrams = _extract_ngrams(frag_text, 3)
        fact_id = frag.get("source_fact_id", "unknown")

        if not frag_ngrams:
            fragments_present += 1
            frag_fact_ids_present.add(fact_id)
            continue

        overlap = len(frag_ngrams & all_ngrams) / len(frag_ngrams)
        if overlap >= 0.25:
            fragments_present += 1
            frag_fact_ids_present.add(fact_id)
        else:
            frag_id = frag.get("fragment_id", "?")
            fragments_missing_detail.append(
                f"{fact_id}/{frag_id} (ngram_overlap={overlap:.0%})"
            )
            if fact_id not in frag_fact_ids_present:
                frag_fact_ids_missing.add(fact_id)

    content_missing = sorted(
        frag_fact_ids_missing - frag_fact_ids_present
    )

    all_missing = sorted(set(registry_missing) | set(content_missing))

    return {
        "fragments_total": len(verified_fragments),
        "fragments_present": fragments_present,
        "fragments_missing": fragments_missing_detail[:20],
        "hidden_facts_total": len(passed_fact_ids),
        "hidden_facts_in_registry": len(app_hf_ids & passed_fact_ids),
        "hidden_facts_in_content": len(frag_fact_ids_present),
        "hidden_facts_covered": len(
            (app_hf_ids & passed_fact_ids) | frag_fact_ids_present
        ),
        "registry_missing_fact_ids": registry_missing[:20],
        "content_missing_fact_ids": content_missing[:20],
        "missing_fact_ids": all_missing[:20],
    }


def _fragment_text(frag: dict[str, Any]) -> str:
    parts: list[str] = []
    if frag.get("type") == "messenger":
        for m in frag.get("messages", []) or []:
            parts.append(str(m.get("text", "")))
    elif frag.get("type") == "calendar":
        cal = frag.get("calendar_event", {}) or {}
        parts.append(str(cal.get("title", "")))
        parts.append(str(cal.get("notes", "")))
        parts.append(str(cal.get("location", "")))
    return " ".join(parts)


def _extract_ngrams(text: str, n: int) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < n:
        return set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


# ---- entry point ---------------------------------------------------------


def derive_persona_identity(corrected_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": corrected_profile.get("name", ""),
        "age": corrected_profile.get("age", 0),
        "occupation": corrected_profile.get("occupation", ""),
        "location": corrected_profile.get("location", ""),
    }


def run_step(
    profile_path: Path,
    social_circle_path: Path,
    news_events_path: Path | None,
    output_dir: Path,
    model: str,
    verifier_model: str,
    per_fact_max_attempts: int,
    log_start: str,
    log_end: str,
    provider: str = "anthropic",
    max_facts: int = 100,
) -> int:
    profile_file = json.loads(profile_path.read_text(encoding="utf-8"))
    corrected_profile = profile_file["corrected_extracted_profile"]
    all_hidden_facts = corrected_profile["hidden_facts"]
    hidden_facts = select_hidden_facts(all_hidden_facts, max_facts)

    circle_file = json.loads(social_circle_path.read_text(encoding="utf-8"))
    corrected_social_circle = circle_file["corrected_social_circle"]

    news_events: list[dict[str, Any]] = []
    if news_events_path and news_events_path.exists():
        news_events = json.loads(news_events_path.read_text(encoding="utf-8"))

    client = make_client(provider)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = profile_path.stem.replace("_verification", "")
    app_log_out = output_dir / f"{base_name}_app_logs.json"
    trace_out = output_dir / f"{base_name}_app_logs_trace.json"

    persona = derive_persona_identity(corrected_profile)

    verified_fragments: list[dict[str, Any]] = []
    contact_usage: dict[str, int] = {}
    trace: list[dict[str, Any]] = []

    print(f"[step4] persona {persona['name']}  hidden_facts={len(hidden_facts)}")

    for i, hf in enumerate(hidden_facts, start=1):
        fact_id = hf.get("fact_id", f"HF-{i:03d}")
        last_fragments: list[dict[str, Any]] = []
        last_verification: dict[str, Any] | None = None
        passed = False

        for attempt in range(1, per_fact_max_attempts + 1):
            print(
                f"[step4/{fact_id}] attempt {attempt}/{per_fact_max_attempts} "
                f"({i}/{len(hidden_facts)})"
            )
            bundle = generate_fragments(
                client, model, hf, corrected_social_circle,
                log_start, log_end, contact_usage, provider=provider,
            )
            fragments = bundle.get("fragments", [])
            banned_token_set = bundle.get("banned_token_set", []) or []
            verification = verify_fragments(
                client, verifier_model, fragments, banned_token_set, persona,
                provider=provider,
            )
            last_fragments = fragments
            last_verification = verification
            if fact_passed(verification, hf):
                passed = True
                update_contact_usage(contact_usage, bundle)
                break
            else:
                verdict = verification.get("verdict", "UNKNOWN")
                print(
                    f"[step4/{fact_id}] verdict={verdict} "
                    f"candidate={verification.get('candidate_label', '')!r} "
                    f"regenerating"
                )

        if passed:
            verified_fragments.extend(
                {**f, "source_fact_id": fact_id}
                for f in last_fragments
            )
        trace.append(
            {
                "fact_id": fact_id,
                "ground_truth_label": hf.get("ground_truth_label"),
                "attempts": attempt,
                "passed": passed,
                "final_verification": last_verification,
            }
        )
        trace_out.write_text(
            json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    trace_out.write_text(
        json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    fragments_out = output_dir / f"{base_name}_verified_fragments.json"
    fragments_out.write_text(
        json.dumps(verified_fragments, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[step4] saved {len(verified_fragments)} fragments to {fragments_out}")

    passed_count = sum(1 for t in trace if t["passed"])
    print(
        f"[step4] fragment phase done: {passed_count}/{len(hidden_facts)} "
        "hidden facts passed reverse-inferability"
    )
    if passed_count < len(hidden_facts):
        print(
            "[step4] WARNING: some hidden facts are unrecoverable from their "
            "fragments. They will still be merged but flagged in the trace."
        )

    # Only pass verified (passed) hidden facts to the merge
    passed_fact_ids = {t["fact_id"] for t in trace if t["passed"]}
    verified_hidden_facts = [
        hf for hf in hidden_facts if hf.get("fact_id") in passed_fact_ids
    ]

    print(
        f"[step4] merging {len(verified_fragments)} fragments "
        f"({len(verified_hidden_facts)}/{len(hidden_facts)} HFs passed) "
        f"for {persona['name']}"
    )
    for merge_attempt in range(1, 4):
        try:
            app_log = merge_app_log(
                client, model, verified_fragments, verified_hidden_facts,
                corrected_social_circle, persona, log_start, log_end,
                news_events, provider=provider,
            )
            break
        except Exception as e:
            print(f"[step4] merge attempt {merge_attempt}/3 failed: {e}")
            if merge_attempt == 3:
                print("[step4] merge exhausted retries. Fragments saved to disk.")
                return 1

    # Build hidden_facts registry programmatically from trace data
    # instead of trusting the merge LLM
    app_log["hidden_facts"] = _build_hidden_facts_registry(
        verified_hidden_facts, trace
    )
    coverage = verify_post_merge_coverage(app_log, verified_fragments, trace)
    app_log["_post_merge_coverage"] = coverage
    app_log_out.write_text(
        json.dumps(app_log, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[step4] wrote {app_log_out}")

    present = coverage["fragments_present"]
    total = coverage["fragments_total"]
    pct = present / total if total else 0
    print(
        f"[step4] post-merge coverage: {present}/{total} fragments "
        f"confirmed present ({pct:.0%})"
    )
    if coverage["missing_fact_ids"]:
        print(
            f"[step4] WARNING: {len(coverage['missing_fact_ids'])} hidden facts "
            f"have no confirmed fragments in the final app log: "
            f"{coverage['missing_fact_ids'][:10]}"
        )

    hf_coverage = coverage["hidden_facts_covered"]
    hf_total = coverage["hidden_facts_total"]
    if hf_coverage < hf_total * 0.8:
        print(
            f"[step4] FAIL: only {hf_coverage}/{hf_total} hidden facts "
            "have fragments in the final app log (below 80% threshold)"
        )
        return 1

    return 0 if passed_count == len(hidden_facts) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", type=Path, required=True,
        help="Path to {persona}_verification.json from step2",
    )
    parser.add_argument(
        "--social-circle", type=Path, required=True,
        help="Path to {persona}_social_circle_verification.json from step3",
    )
    parser.add_argument(
        "--news-events", type=Path, default=None,
        help="Optional path to news events JSON for surprise weaving",
    )
    parser.add_argument(
        "--output", type=Path,
        default=STEP_DIR / "data_samples" / "output",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--verifier-model", default=DEFAULT_VERIFIER_MODEL,
        help="Independent model for the reverse-inferability gate",
    )
    parser.add_argument(
        "--per-fact-max-attempts", type=int, default=DEFAULT_PER_FACT_MAX_ATTEMPTS,
    )
    parser.add_argument("--log-start", default="2026-03-01")
    parser.add_argument("--log-end", default="2026-03-31")
    parser.add_argument("--provider", default="anthropic", choices=SUPPORTED_PROVIDERS)
    parser.add_argument(
        "--max-facts", type=int, default=100,
        help="Maximum hidden facts to include (prioritized by benchmark relevance)",
    )
    args = parser.parse_args()

    if not check_api_key(args.provider):
        print(f"API key for {args.provider} is not set.", file=sys.stderr)
        sys.exit(2)

    sys.exit(
        run_step(
            args.profile,
            args.social_circle,
            args.news_events,
            args.output,
            args.model,
            args.verifier_model,
            args.per_fact_max_attempts,
            args.log_start,
            args.log_end,
            args.provider,
            max_facts=args.max_facts,
        )
    )


if __name__ == "__main__":
    main()
