"""Decoy generation and placement helpers for Step 4."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Callable

try:
    from .decoy_safety import validate_decoy_safety
except ImportError:
    from decoy_safety import validate_decoy_safety

DECOY_GENERATION_BATCH_SIZE = 50


def load_verified_decoys(decoys_path: Path | str | None) -> list[dict[str, Any]]:
    if not decoys_path:
        return []
    path = Path(decoys_path)
    if not path.exists():
        raise FileNotFoundError(f"Verified decoys file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        decoys = payload.get("decoys", payload.get("verified_decoys", []))
    else:
        decoys = payload
    if not isinstance(decoys, list):
        raise ValueError(f"Verified decoys file must contain a list: {path}")  # noqa: TRY004 - malformed serialized input is a validation error
    return decoys


def _fill(template: str, placeholder: str, payload: Any) -> str:
    if isinstance(payload, str):
        return template.replace(placeholder, payload)
    return template.replace(
        placeholder, json.dumps(payload, indent=2, ensure_ascii=False)
    )


def _decoys_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        decoys = payload.get("decoys", payload.get("verified_decoys", []))
    else:
        decoys = payload
    if not isinstance(decoys, list):
        raise ValueError("Decoy generation output must contain a decoys list")  # noqa: TRY004 - malformed serialized input is a validation error
    return [d for d in decoys if isinstance(d, dict)]


def normalize_verified_decoys(
    payload: Any,
    persona_name: str,
    hidden_facts: list[dict[str, Any]],
    social_circle: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(_decoys_from_payload(payload), 1):
        decoy = dict(raw)
        decoy.setdefault("decoy_id", f"D-{idx:03d}")
        decoy.setdefault("difficulty", "easy")
        decoy.setdefault("overlapping_hidden_fact_ids", [])
        decoy.setdefault("why_safe", "")

        messages = decoy.get("messages")
        if messages:
            clean_messages = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                sender = msg.get("sender", "")
                if sender in {"{{PERSONA_NAME}}", "persona"}:
                    sender = persona_name
                clean_messages.append({
                    "sender": sender,
                    "text": msg.get("text", ""),
                })
            decoy["messages"] = clean_messages

        if decoy.get("type") == "messenger" and not decoy.get("messages"):
            continue
        if decoy.get("type") == "calendar" and not decoy.get("calendar_event"):
            continue

        safety = validate_decoy_safety(
            decoy,
            hidden_facts,
            persona_name,
            social_circle or {},
        )
        if not safety.passed:
            continue
        decoy["overlap_check"] = safety.verdict
        decoy["overlapping_hidden_fact_ids"] = safety.overlapping_hidden_fact_ids
        decoy["safety_reasons"] = safety.reasons

        normalized.append(decoy)
    return normalized


def generate_verified_decoys(
    call_model: Callable[[str], str],
    decoy_prompt: str,
    extract_json: Callable[[str], Any],
    persona: dict[str, Any],
    hidden_facts: list[dict[str, Any]],
    social_circle: dict[str, Any],
    log_start: str,
    log_end: str,
    contact_usage: dict[str, int],
    target_count: int,
) -> list[dict[str, Any]]:
    prompt = decoy_prompt
    prompt = _fill(prompt, "{{PERSONA_NAME}}", persona["name"])
    prompt = _fill(prompt, "{{PERSONA_AGE}}", str(persona["age"]))
    prompt = _fill(prompt, "{{PERSONA_OCCUPATION}}", persona["occupation"])
    prompt = _fill(prompt, "{{PERSONA_LOCATION}}", persona["location"])
    prompt = _fill(prompt, "{{INSERT_HIDDEN_FACTS_JSON_HERE}}", hidden_facts)
    prompt = _fill(
        prompt, "{{INSERT_CORRECTED_SOCIAL_CIRCLE_JSON_HERE}}", social_circle
    )
    prompt = _fill(prompt, "{{LOG_START_DATE}}", log_start)
    prompt = _fill(prompt, "{{LOG_END_DATE}}", log_end)
    prompt = _fill(prompt, "{{TARGET_DECOY_COUNT}}", str(target_count))
    prompt = _fill(
        prompt, "{{INSERT_CONTACT_USAGE_COUNTS_JSON_HERE}}", contact_usage
    )
    return normalize_verified_decoys(
        extract_json(call_model(prompt)),
        persona["name"],
        hidden_facts,
        social_circle,
    )


def _is_selectable_messenger_decoy(decoy: dict[str, Any]) -> bool:
    return (
        decoy.get("type") == "messenger"
        and bool(decoy.get("decoy_id"))
        and decoy.get("overlap_check") != "unsafe_overlap"
        and bool(decoy.get("messages"))
    )


def _selectable_messenger_count(decoys: list[dict[str, Any]]) -> int:
    return sum(1 for decoy in decoys if _is_selectable_messenger_decoy(decoy))


def _decoy_signature(decoy: dict[str, Any]) -> tuple[Any, ...]:
    messages = tuple(
        (
            msg.get("sender", ""),
            msg.get("text", ""),
        )
        for msg in decoy.get("messages", []) or []
        if isinstance(msg, dict)
    )
    cal = decoy.get("calendar_event") or {}
    calendar = tuple(
        cal.get(field, "")
        for field in ("title", "location", "notes")
    )
    return (
        decoy.get("type", ""),
        decoy.get("decoy_type", ""),
        messages,
        calendar,
    )


def _dedupe_decoys(decoys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for decoy in decoys:
        signature = _decoy_signature(decoy)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(decoy)
    return unique


def _renumber_decoys(decoys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    renumbered: list[dict[str, Any]] = []
    for idx, decoy in enumerate(decoys, 1):
        item = dict(decoy)
        item["decoy_id"] = f"D-{idx:03d}"
        renumbered.append(item)
    return renumbered


def _batch_log_windows(
    log_start: str,
    log_end: str,
    batch_count: int,
) -> list[tuple[str, str]]:
    if batch_count <= 1:
        return [(log_start, log_end)]
    try:
        start = datetime.date.fromisoformat(log_start)
        end = datetime.date.fromisoformat(log_end)
    except ValueError:
        return [(log_start, log_end)] * batch_count
    if end < start:
        return [(log_start, log_end)] * batch_count

    total_days = (end - start).days + 1
    windows: list[tuple[str, str]] = []
    for i in range(batch_count):
        start_offset = (i * total_days) // batch_count
        end_offset = ((i + 1) * total_days) // batch_count - 1
        if end_offset < start_offset:
            end_offset = start_offset
        win_start = start + datetime.timedelta(days=start_offset)
        win_end = start + datetime.timedelta(days=end_offset)
        windows.append((win_start.isoformat(), win_end.isoformat()))
    return windows


def _generate_decoys_in_batches(
    call_model: Callable[[str], str],
    decoy_prompt: str,
    extract_json: Callable[[str], Any],
    persona: dict[str, Any],
    hidden_facts: list[dict[str, Any]],
    social_circle: dict[str, Any],
    log_start: str,
    log_end: str,
    contact_usage: dict[str, int],
    target_count: int,
    required_messenger_count: int,
    batch_size: int = DECOY_GENERATION_BATCH_SIZE,
    seed_decoys: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    decoys: list[dict[str, Any]] = _renumber_decoys(
        _dedupe_decoys([
            decoy for decoy in (seed_decoys or [])
            if _is_selectable_messenger_decoy(decoy)
        ])
    )
    batch_count = max(1, (target_count + batch_size - 1) // batch_size)
    max_batches = max(batch_count * 4, batch_count + 4)
    windows = _batch_log_windows(log_start, log_end, batch_count)

    for batch_idx in range(max_batches):
        remaining_messenger = max(
            required_messenger_count - _selectable_messenger_count(decoys),
            0,
        )
        if len(decoys) >= target_count and remaining_messenger == 0:
            break

        request_count = batch_size
        batch_start, batch_end = windows[batch_idx % len(windows)]
        print(
            f"[step4] generating decoy batch {batch_idx + 1} "
            f"({request_count} candidates, {batch_start} to {batch_end})"
        )
        batch = generate_verified_decoys(
            call_model,
            decoy_prompt,
            extract_json,
            persona,
            hidden_facts,
            social_circle,
            batch_start,
            batch_end,
            contact_usage,
            request_count,
        )
        messenger_batch = [
            decoy for decoy in batch
            if decoy.get("type") == "messenger"
        ]
        decoys = _renumber_decoys(_dedupe_decoys(decoys + messenger_batch))
        print(
            f"[step4] decoy batch {batch_idx + 1} kept "
            f"{len(messenger_batch)} messenger decoys "
            f"({len(decoys)} unique total, "
            f"{_selectable_messenger_count(decoys)} selectable)"
        )

    return decoys


def resolve_verified_decoy_pool(
    call_model: Callable[[str], str],
    decoy_prompt: str,
    extract_json: Callable[[str], Any],
    persona: dict[str, Any],
    hidden_facts: list[dict[str, Any]],
    social_circle: dict[str, Any],
    log_start: str,
    log_end: str,
    contact_usage: dict[str, int],
    explicit_pool: list[dict[str, Any]],
    decoys_out: Path,
    decoy_count: int,
    decoy_pool_size: int,
    resume: bool,
) -> list[dict[str, Any]]:
    if decoy_count <= 0:
        return explicit_pool
    target_count = max(decoy_count, decoy_pool_size)
    existing_decoys: list[dict[str, Any]] = []
    if explicit_pool:
        existing_decoys = normalize_verified_decoys(
            explicit_pool,
            persona["name"],
            hidden_facts,
            social_circle,
        )
        existing_messenger = _selectable_messenger_count(existing_decoys)
        if existing_messenger >= target_count:
            return existing_decoys
        print(
            f"[step4] explicit decoy pool has {len(existing_decoys)} candidates "
            f"and {existing_messenger} selectable messenger decoys; "
            f"generating up to {target_count} selectable messenger decoys"
        )
    elif resume and decoys_out.exists():
        existing_decoys = normalize_verified_decoys(
            load_verified_decoys(decoys_out),
            persona["name"],
            hidden_facts,
            social_circle,
        )
        existing_messenger = _selectable_messenger_count(existing_decoys)
        if existing_messenger >= target_count:
            return existing_decoys
        print(
            f"[step4] existing decoy pool has {len(existing_decoys)} candidates "
            f"and {existing_messenger} selectable messenger decoys; "
            f"generating up to {target_count} selectable messenger decoys"
        )

    print(f"[step4] generating {target_count} verified decoy candidates")
    if target_count > DECOY_GENERATION_BATCH_SIZE or existing_decoys:
        decoys = _generate_decoys_in_batches(
            call_model,
            decoy_prompt,
            extract_json,
            persona,
            hidden_facts,
            social_circle,
            log_start,
            log_end,
            contact_usage,
            target_count,
            target_count,
            seed_decoys=existing_decoys,
        )
    else:
        decoys = generate_verified_decoys(
            call_model,
            decoy_prompt,
            extract_json,
            persona,
            hidden_facts,
            social_circle,
            log_start,
            log_end,
            contact_usage,
            target_count,
        )
    decoys_out.write_text(
        json.dumps(decoys, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[step4] wrote {len(decoys)} verified decoys to {decoys_out}")
    return decoys


def _social_circle_contact_names(social_circle: dict[str, Any]) -> list[str]:
    members = social_circle.get("members", social_circle.get("social_circle", []))
    if isinstance(members, list):
        contacts = [m.get("name", "") for m in members if m.get("name")]
    elif isinstance(members, dict):
        contacts = [
            m.get("name", "")
            for m in members.values()
            if isinstance(m, dict) and m.get("name")
        ]
    else:
        contacts = []
    return contacts or ["Contact"]


def select_verified_decoys(
    verified_decoys: list[dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]]:
    if target_count <= 0:
        return []
    difficulty_rank = {"hard": 0, "medium": 1, "easy": 2}
    candidates = [
        d for d in verified_decoys
        if _is_selectable_messenger_decoy(d)
    ]
    candidates.sort(
        key=lambda d: (
            difficulty_rank.get(str(d.get("difficulty", "easy")).lower(), 9),
            d.get("decoy_id", ""),
        )
    )
    return [dict(d) for d in candidates[:target_count]]


def build_decoy_filler_sessions(
    selected_decoys: list[dict[str, Any]],
    persona: dict[str, Any],
    social_circle: dict[str, Any],
    log_start: str,
    log_end: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not selected_decoys:
        return [], []

    start = datetime.date.fromisoformat(log_start)
    end = datetime.date.fromisoformat(log_end)
    total_days = (end - start).days + 1
    contacts = _social_circle_contact_names(social_circle)
    persona_name = persona.get("name", "Persona")

    sessions: list[dict[str, Any]] = []
    registry: list[dict[str, Any]] = []
    for i, decoy in enumerate(selected_decoys):
        preferred = decoy.get("preferred_contact")
        contact = (
            preferred if decoy.get("contact_policy") == "specific" and preferred
            else contacts[i % len(contacts)]
        )
        day_offset = (i * total_days) // max(len(selected_decoys), 1)
        date = (start + datetime.timedelta(days=day_offset)).isoformat()
        hour = 9 + (i * 5) % 11
        minute = (i * 17) % 60

        messages = []
        for j, msg in enumerate(decoy.get("messages", []) or []):
            sender = msg.get("sender", "")
            if sender in {"contact", "{{CONTACT_NAME}}"}:
                sender = contact
            elif sender in {"persona", "{{PERSONA_NAME}}"}:
                sender = persona_name
            messages.append({
                "time": f"{hour:02d}:{(minute + j * 3) % 60:02d}",
                "sender": sender,
                "text": msg.get("text", ""),
            })

        sessions.append({
            "session_id": "",
            "date": date,
            "contact": contact,
            "messages": messages,
        })
        registry.append({
            "decoy_id": decoy.get("decoy_id"),
            "related_item_id": "",
            "placement_type": "filler_session",
            "message_indices": list(range(len(messages))),
            "decoy_type": decoy.get("decoy_type"),
            "difficulty": decoy.get("difficulty", "easy"),
            "overlap_check": decoy.get("overlap_check"),
            "overlapping_hidden_fact_ids": decoy.get(
                "overlapping_hidden_fact_ids", []
            ),
            "why_safe": decoy.get("why_safe", ""),
        })

    return sessions, registry


def finalize_filler_sessions(
    decoy_sessions: list[dict[str, Any]],
    mundane_sessions: list[dict[str, Any]],
    decoy_registry: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int]:
    combined = decoy_sessions + mundane_sessions
    for idx, session in enumerate(combined, 1):
        session["session_id"] = f"F-{idx:03d}"
    for idx, registry_entry in enumerate(decoy_registry):
        registry_entry["related_item_id"] = combined[idx]["session_id"]
    decoy_tokens = len(json.dumps(decoy_sessions, ensure_ascii=False)) // 4
    mundane_tokens = len(json.dumps(mundane_sessions, ensure_ascii=False)) // 4
    return combined, decoy_registry, decoy_tokens, mundane_tokens
