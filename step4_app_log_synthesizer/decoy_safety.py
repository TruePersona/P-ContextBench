"""Deterministic safety checks for Step 4 decoy candidates."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass
class DecoySafetyResult:
    passed: bool
    verdict: str
    overlapping_hidden_fact_ids: list[str]
    owner: str
    reasons: list[str]


_STOPWORDS = {
    "the", "and", "for", "not", "you", "that", "this", "with", "from",
    "have", "was", "are", "but", "can", "had", "has", "her", "his",
    "how", "its", "may", "she", "too", "use", "who", "did", "get",
    "got", "let", "our", "out", "own", "say", "way", "all", "any",
    "been", "each", "just", "like", "more", "some", "than", "them",
    "then", "very", "when", "will", "about", "could", "into", "also",
    "back", "come", "down", "even", "give", "here", "know", "look",
    "make", "most", "much", "only", "over", "such", "take", "time",
    "well", "what", "year", "please", "thanks", "thank",
}

_FIRST_PERSON_POSSESSIVE = {"my", "mine"}
_SECOND_PERSON_POSSESSIVE = {"your", "yours"}
_THIRD_PERSON_POSSESSIVE = {"her", "hers", "his", "their", "theirs"}
_OTHER_PERSON_TERMS = {
    "mom", "mother", "dad", "father", "sister", "brother", "friend",
    "coworker", "colleague", "neighbor", "requester", "organizer", "client",
    "patient", "child", "kid", "son", "daughter", "partner", "spouse",
    "roommate", "teammate", "aunt", "uncle", "cousin", "grandma",
    "grandpa", "parent", "teacher", "manager", "doctor", "nurse",
}
_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


def validate_decoy_safety(
    decoy: dict[str, Any],
    hidden_facts: list[dict[str, Any]],
    persona_name: str,
    social_circle: dict[str, Any] | None = None,
    overlap_threshold: float = 0.25,
) -> DecoySafetyResult:
    """Return a conservative deterministic safety verdict for one decoy."""
    shape_error = _shape_error(decoy)
    if shape_error:
        return _failed("unsafe_overlap", [], "ambiguous", shape_error)

    if decoy.get("overlap_check") == "unsafe_overlap":
        return _failed(
            "unsafe_overlap", [], "ambiguous", "candidate marked unsafe_overlap"
        )

    overlap = _hidden_fact_overlap(decoy, hidden_facts, overlap_threshold)
    if not overlap:
        return DecoySafetyResult(
            passed=True,
            verdict="none",
            overlapping_hidden_fact_ids=[],
            owner="none",
            reasons=["no deterministic hidden-fact overlap detected"],
        )

    owner = _classify_overlap_owner(
        decoy,
        overlap_terms={term for terms in overlap.values() for term in terms},
        persona_name=persona_name,
        social_circle=social_circle or {},
    )
    overlap_ids = sorted(overlap)
    if owner == "other_person":
        return DecoySafetyResult(
            passed=True,
            verdict="safe_other_person_owned",
            overlapping_hidden_fact_ids=overlap_ids,
            owner=owner,
            reasons=[
                "hidden-fact-like overlap is explicitly owned by someone else"
            ],
        )
    if owner == "persona":
        return _failed(
            "unsafe_overlap",
            overlap_ids,
            owner,
            "hidden-fact-like overlap is attributable to the persona",
        )
    return _failed(
        "unsafe_overlap",
        overlap_ids,
        "ambiguous",
        "hidden-fact-like overlap has unclear ownership",
    )


def _failed(
    verdict: str,
    overlap_ids: list[str],
    owner: str,
    reason: str,
) -> DecoySafetyResult:
    return DecoySafetyResult(
        passed=False,
        verdict=verdict,
        overlapping_hidden_fact_ids=overlap_ids,
        owner=owner,
        reasons=[reason],
    )


def _shape_error(decoy: dict[str, Any]) -> str | None:
    decoy_type = decoy.get("type")
    if decoy_type == "messenger":
        messages = decoy.get("messages")
        if not isinstance(messages, list) or not messages:
            return "messenger decoy has no messages"
        if not any(isinstance(msg, dict) and msg.get("text") for msg in messages):
            return "messenger decoy has no message text"
        return None
    if decoy_type == "calendar":
        event = decoy.get("calendar_event")
        if not isinstance(event, dict) or not event:
            return "calendar decoy has no calendar_event"
        if not any(event.get(field) for field in ("title", "notes", "location")):
            return "calendar decoy has no event text"
        return None
    return "decoy type must be messenger or calendar"


def _hidden_fact_overlap(
    decoy: dict[str, Any],
    hidden_facts: list[dict[str, Any]],
    threshold: float,
) -> dict[str, set[str]]:
    decoy_tokens = set(_content_tokens(_decoy_text(decoy))) - _STOPWORDS
    if not decoy_tokens:
        return {}

    overlap: dict[str, set[str]] = {}
    for idx, hidden_fact in enumerate(hidden_facts, 1):
        fact_tokens = set()
        for field in ("ground_truth_label", "claim"):
            fact_tokens.update(_content_tokens(str(hidden_fact.get(field, ""))))
        fact_tokens -= _STOPWORDS
        if not fact_tokens:
            continue
        shared = decoy_tokens & fact_tokens
        if not shared:
            continue
        decoy_overlap = len(shared) / len(decoy_tokens)
        fact_overlap = len(shared) / len(fact_tokens)
        if decoy_overlap >= threshold or fact_overlap >= threshold:
            fact_id = str(hidden_fact.get("fact_id") or f"HF-{idx:03d}")
            overlap[fact_id] = shared
    return overlap


def _classify_overlap_owner(
    decoy: dict[str, Any],
    overlap_terms: set[str],
    persona_name: str,
    social_circle: dict[str, Any],
) -> str:
    persona_terms = _name_terms(persona_name)
    other_terms = _OTHER_PERSON_TERMS | _social_circle_terms(social_circle)
    found_persona = False
    found_other = False

    for role, text in _segments(decoy, persona_name):
        tokens = _content_tokens(text)
        if not overlap_terms & set(tokens):
            continue

        near_first = _near(tokens, overlap_terms, _FIRST_PERSON_POSSESSIVE)
        near_second = _near(tokens, overlap_terms, _SECOND_PERSON_POSSESSIVE)
        near_third = _near(tokens, overlap_terms, _THIRD_PERSON_POSSESSIVE)
        near_other = _near(tokens, overlap_terms, other_terms)
        near_persona = _near(tokens, overlap_terms, persona_terms)

        if role == "persona":
            found_persona = found_persona or near_first or near_persona
            found_other = found_other or near_second or near_third or near_other
        elif role == "other":
            found_persona = found_persona or near_second or near_persona
            found_other = found_other or near_first or near_third or near_other
        else:
            found_persona = found_persona or near_persona
            found_other = found_other or near_third or near_other

    if found_other and not found_persona:
        return "other_person"
    if found_persona and not found_other:
        return "persona"
    return "ambiguous"


def _segments(decoy: dict[str, Any], persona_name: str) -> list[tuple[str, str]]:
    persona_norm = persona_name.strip().lower()
    persona_first = persona_norm.split()[0] if persona_norm else ""
    segments: list[tuple[str, str]] = []
    for msg in decoy.get("messages", []) or []:
        if not isinstance(msg, dict):
            continue
        sender = str(msg.get("sender", "")).strip().lower()
        role = "other"
        if sender in {"persona", "{{persona_name}}", persona_norm, persona_first}:
            role = "persona"
        segments.append((role, str(msg.get("text", ""))))

    event = decoy.get("calendar_event") or {}
    if isinstance(event, dict):
        text = " ".join(
            str(event.get(field, ""))
            for field in ("title", "notes", "location")
        )
        if text.strip():
            segments.append(("calendar", text))
    return segments


def _decoy_text(decoy: dict[str, Any]) -> str:
    parts = []
    for _, text in _segments(decoy, ""):
        parts.append(text)
    return " ".join(parts)


def _near(
    tokens: list[str],
    terms: set[str],
    cues: set[str],
    window: int = 6,
) -> bool:
    if not tokens or not terms or not cues:
        return False
    term_positions = [idx for idx, token in enumerate(tokens) if token in terms]
    cue_positions = [idx for idx, token in enumerate(tokens) if token in cues]
    return any(
        abs(tpos - cpos) <= window
        for tpos in term_positions
        for cpos in cue_positions
    )


def _content_tokens(text: str) -> list[str]:
    return [_base_token(token) for token in _WORD_RE.findall(text.lower())]


def _base_token(token: str) -> str:
    return token[:-2] if token.endswith("'s") else token


def _name_terms(name: str) -> set[str]:
    return set(_content_tokens(name))


def _social_circle_terms(social_circle: dict[str, Any]) -> set[str]:
    members = social_circle.get("members", social_circle.get("social_circle", []))
    terms: set[str] = set()
    if isinstance(members, list):
        iterable = members
    elif isinstance(members, dict):
        iterable = [value for value in members.values() if isinstance(value, dict)]
    else:
        iterable = []
    for member in iterable:
        if not isinstance(member, dict):
            continue
        for field in ("name", "relationship", "role"):
            terms.update(_content_tokens(str(member.get(field, ""))))
    return terms
