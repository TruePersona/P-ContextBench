"""Step 4B — regenerate app-log filler while preserving fact evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm import (
    API_BACKENDS,
    SUBSCRIPTION_BACKENDS,
    SUPPORTED_BACKENDS,
    SUPPORTED_PROVIDERS,
    call_llm as call_api_llm,
    call_subscription_cli,
    check_api_key,
    default_model_for_backend,
    make_client,
    provider_for_backend,
)

STEP_DIR = Path(__file__).parent
REPO_ROOT = STEP_DIR.parent
PROMPT_PATH = STEP_DIR / "prompt.txt"
NEWS_BRIEF_PROMPT_PATH = STEP_DIR / "news_brief_prompt.txt"
DEFAULT_BATCH_SIZE = 40
DEFAULT_SURPRISE_RATE = 0.50
DEFAULT_MAX_SURPRISES = 10_000
DEFAULT_NEWS_EVENT_COUNT = 20
DEFAULT_MIN_NEWS_EVENTS = 12
DEFAULT_GDELT_MAX_RECORDS = 6
DEFAULT_GDELT_DELAY_SECONDS = 1.5
DEFAULT_GDELT_MAX_QUERIES = 12
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
US_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

CLAUDE_CMD = os.environ.get(
    "CLAUDE_CMD", "claude.cmd" if sys.platform == "win32" else "claude"
)
CODEX_CMD = os.environ.get(
    "CODEX_CMD", "codex.exe" if sys.platform == "win32" else "codex"
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def fill_json(template: str, placeholder: str, payload: Any) -> str:
    return template.replace(placeholder, json.dumps(payload, indent=2, ensure_ascii=False))


def call_model(
    client,
    model: str,
    prompt: str,
    provider: str,
    backend: str,
) -> str:
    if backend in SUBSCRIPTION_BACKENDS:
        return call_subscription_cli(
            prompt,
            model,
            backend,
            claude_cmd=CLAUDE_CMD,
            codex_cmd=CODEX_CMD,
        )
    return call_api_llm(client, model, prompt, provider=provider)


def fix_invalid_escapes(text: str) -> str:
    valid = set('"\\/bfnrtu')
    out: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            if text[index + 1] in valid:
                out.append(text[index])
                out.append(text[index + 1])
                index += 2
            else:
                out.append(text[index + 1])
                index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start = payload.find("{")
    end = payload.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model output")
    raw = payload[start : end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(fix_invalid_escapes(raw))


def token_estimate(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False)) // 4


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return cleaned or "model"


def output_path_for(input_path: Path, output_dir: Path, variant: str, model: str) -> Path:
    model_label = "gpt" if model.startswith("gpt-") else sanitize_name(model)
    return output_dir / f"{input_path.stem}_{model_label}_{variant}_filler.json"


def load_news_events(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError("--news-events must point to a JSON array")
    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Every news event must be a JSON object")
        if not item.get("date") or not item.get("summary"):
            raise ValueError("Every news event must include date and summary")
        date.fromisoformat(str(item["date"]))
        normalized.append(item)
    return normalized


def profile_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return bundle.get("corrected_extracted_profile", bundle)


def social_circle_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return bundle.get("corrected_social_circle", bundle)


def contacts_from_social_circle(social_circle: dict[str, Any]) -> list[dict[str, Any]]:
    contacts = social_circle.get("social_circle", social_circle.get("contacts", []))
    return contacts if isinstance(contacts, list) else []


def default_profile_path(persona: str) -> Path:
    return REPO_ROOT / "step2_interview" / "data_samples" / "output" / f"{persona}_verification.json"


def default_social_circle_path(persona: str) -> Path:
    return (
        REPO_ROOT
        / "step3_social_circle"
        / "data_samples"
        / "output"
        / f"{persona}_social_circle_verification.json"
    )


def default_news_events_path(persona: str) -> Path:
    return STEP_DIR / "data_samples" / "input" / f"{persona}_news_events.json"


def default_news_brief_path(persona: str) -> Path:
    return STEP_DIR / "data_samples" / "input" / f"{persona}_news_brief.json"


def resolve_app_logs_path(persona: str, explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        return explicit_path

    local_input = STEP_DIR / "data_samples" / "input" / f"{persona}_app_logs.json"
    if local_input.exists():
        return local_input

    canonical_output = REPO_ROOT / "step4_app_log_synthesizer" / "data_samples" / "output"
    candidates = sorted(canonical_output.glob(f"{persona}*_app_logs.json"))
    candidates = [
        path
        for path in candidates
        if not path.name.endswith("_trace.json") and "verified_fragments" not in path.name
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(
            f"No app log found for {persona}. Expected {local_input} or "
            f"{canonical_output / (persona + '*_app_logs.json')}"
        )
    raise ValueError(
        f"Multiple app logs found for {persona}; pass --app-logs explicitly: "
        + ", ".join(str(path) for path in candidates)
    )


def resolve_profile_path(persona: str | None, explicit_path: Path | None) -> Path | None:
    if explicit_path is not None:
        return explicit_path
    if persona:
        return default_profile_path(persona)
    return None


def resolve_social_circle_path(persona: str | None, explicit_path: Path | None) -> Path | None:
    if explicit_path is not None:
        return explicit_path
    if persona:
        return default_social_circle_path(persona)
    return None


def text_blob(*values: Any) -> str:
    return json.dumps(values, ensure_ascii=False).lower()


def likely_contacts_for_terms(
    contacts: list[dict[str, Any]], terms: list[str], fallback_count: int = 2
) -> list[str]:
    matches = []
    lowered_terms = [term.lower() for term in terms]
    for contact in contacts:
        haystack = text_blob(
            contact.get("name", ""),
            contact.get("relationship", ""),
            contact.get("recent_text_topics", []),
            contact.get("personality_mini_profile", {}),
        )
        if any(term in haystack for term in lowered_terms):
            matches.append(str(contact.get("name", "")))
    if matches:
        return [name for name in matches if name]
    return [
        str(contact.get("name", ""))
        for contact in contacts[:fallback_count]
        if contact.get("name")
    ]


def city_and_state(profile: dict[str, Any]) -> tuple[str, str]:
    location = str(profile.get("location", "") or "")
    city = str(profile.get("city", "") or "")
    state = str(profile.get("state", "") or "")
    if not city and location:
        match = re.match(r"\s*([^,]+),\s*([A-Z]{2}|[A-Za-z ]+)", location)
        if match:
            city = match.group(1).strip()
            state = state or match.group(2).strip()
    return city, state


def state_search_term(state: str) -> str:
    cleaned = state.strip()
    return US_STATE_NAMES.get(cleaned.upper(), cleaned)


def tokenize_for_anchors(value: str) -> list[str]:
    stopwords = {
        "about",
        "after",
        "also",
        "and",
        "are",
        "because",
        "been",
        "being",
        "between",
        "but",
        "can",
        "for",
        "from",
        "has",
        "have",
        "her",
        "his",
        "into",
        "its",
        "latest",
        "near",
        "not",
        "one",
        "our",
        "out",
        "over",
        "own",
        "she",
        "that",
        "the",
        "their",
        "them",
        "they",
        "this",
        "through",
        "with",
        "would",
        "you",
    }
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{3,}", value.lower())
        if token not in stopwords
    ]


def anchor_phrases_from_context(
    profile: dict[str, Any],
    social_circle: dict[str, Any],
    max_phrases: int = 10,
) -> list[str]:
    city, state = city_and_state(profile)
    state_term = state_search_term(state)
    contacts = contacts_from_social_circle(social_circle)
    source_texts: list[str] = []

    def add_source(value: Any) -> None:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) >= 4:
            source_texts.append(text)

    add_source(profile.get("occupation", ""))
    add_source(profile.get("location", ""))

    preferences = profile.get("preferences", {})
    if isinstance(preferences, dict):
        for _key, value in preferences.items():
            if isinstance(value, str):
                add_source(value)
            elif isinstance(value, dict):
                add_source(value.get("summary", ""))
                for detail in value.get("details", [])[:4]:
                    add_source(detail)

    for contact in contacts:
        for topic in contact.get("recent_text_topics", [])[:3]:
            add_source(topic)

    scored: dict[str, int] = {}
    if city:
        scored[city] = 100
    if state_term:
        scored[state_term] = 50

    for source in source_texts:
        for phrase in extract_named_anchors(source):
            lowered = phrase.lower()
            if lowered in {city.lower(), state_term.lower()}:
                continue
            score = 5 + sum(source.lower().count(word) for word in tokenize_for_anchors(phrase))
            if city and city.lower() in source.lower():
                score += 2
            scored[phrase] = max(scored.get(phrase, 0), score)

    return [
        phrase
        for phrase, _score in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[
            :max_phrases
        ]
    ]


def extract_named_anchors(text: str) -> list[str]:
    blocked = {
        "Q",
        "The",
        "This",
        "That",
        "She",
        "He",
        "They",
        "Her",
        "His",
        "Their",
        "Tuesday",
        "Thursday",
        "Saturday",
        "Sunday",
        "Monday",
        "Friday",
        "Wednesday",
        "Weekend",
        "Planning",
        "Comparing",
        "Processing",
        "Coordinating",
        "Scheduling",
        "Recruiting",
        "Updates",
        "News",
    }
    blocked_lower = {word.lower() for word in blocked}
    anchors: list[str] = []
    pattern = re.compile(
        r"\b(?:[A-Z][a-zA-Z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-zA-Z]+|[A-Z]{2,}|of|and|for|the|de|del|la|los|las)){0,5}"
    )
    for match in pattern.finditer(text):
        phrase = re.sub(r"\s+", " ", match.group(0)).strip()
        words = phrase.split()
        if not words or words[0] in blocked:
            continue
        while words and words[-1].lower() in {"of", "and", "for", "the", "de", "del", "la"}:
            words.pop()
        words = [word for word in words if word.lower() not in blocked_lower]
        while words and words[-1].lower() in {"of", "and", "for", "the", "de", "del", "la"}:
            words.pop()
        phrase = " ".join(words)
        if len(phrase) < 4:
            continue
        if len(words) == 1 and not words[0].isupper():
            continue
        if re.fullmatch(r"Q\d+", phrase):
            continue
        anchors.append(phrase)
    deduped = []
    seen = set()
    for anchor in anchors:
        key = anchor.lower()
        if key not in seen:
            deduped.append(anchor)
            seen.add(key)
    return deduped


def infer_event_type(query: str) -> str:
    lowered = query.lower()
    if any(term in lowered for term in ["weather", "storm", "air quality", "wildfire", "smoke"]):
        return "weather"
    if any(term in lowered for term in ["outage", "power", "internet", "phone"]):
        return "outage"
    if any(term in lowered for term in ["festival", "event", "market", "concert"]):
        return "local_event"
    if any(term in lowered for term in ["campus", "university", "college", "school"]):
        return "campus"
    if any(term in lowered for term in ["restaurant", "food", "recall", "grocery"]):
        return "food"
    if any(term in lowered for term in ["travel", "airport", "flight", "road"]):
        return "travel"
    if any(term in lowered for term in ["technology", "research", "science", "ai"]):
        return "technology"
    return "local_news"


def query_terms_from_context(
    profile: dict[str, Any],
    social_circle: dict[str, Any],
    max_queries: int = DEFAULT_GDELT_MAX_QUERIES,
) -> list[dict[str, Any]]:
    contacts = contacts_from_social_circle(social_circle)
    city, state = city_and_state(profile)
    state_term = state_search_term(state)
    anchors = anchor_phrases_from_context(profile, social_circle)
    query_specs: list[tuple[str, list[str], str]] = []

    if city:
        local_base = f'"{city}" "{state_term}"' if state_term else f'"{city}"'
        query_specs.extend(
            [
                (local_base, [city, state_term], f"Local context for {city}"),
                (f'{local_base} weather', [city, "weather"], f"Weather or alerts near {city}"),
                (f'{local_base} outage', [city, "outage"], f"Utility or service disruptions near {city}"),
                (f'{local_base} event', [city, "event"], f"Public events near {city}"),
            ]
        )

    for anchor in anchors:
        if city and anchor.lower() in {city.lower(), state_term.lower()}:
            continue
        if len(query_specs) >= max_queries + 4:
            break
        if city:
            query_specs.append(
                (
                    f'"{anchor}" "{city}"',
                    [anchor, city],
                    f"Persona-relevant context: {anchor}",
                )
            )
        else:
            query_specs.append((f'"{anchor}"', [anchor], f"Persona-relevant context: {anchor}"))

    deduped = []
    seen = set()
    for query, terms, relevance in query_specs:
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(
            {
                "query": query,
                "type": infer_event_type(query),
                "location_scope": "local" if city and city.lower() in query.lower() else "regional/national",
                "relevance": relevance,
                "likely_contacts": likely_contacts_for_terms(contacts, terms),
                "anchors": [term for term in terms if term],
            }
        )
    return deduped[:max_queries]


def normalize_brief_queries(
    brief: dict[str, Any],
    contacts: list[dict[str, Any]],
    max_queries: int,
) -> list[dict[str, Any]]:
    contact_names = {str(contact.get("name", "")) for contact in contacts if contact.get("name")}
    queries = brief.get("gdelt_queries", [])
    if not isinstance(queries, list):
        return []

    normalized = []
    seen = set()
    for query in queries:
        if not isinstance(query, dict):
            continue
        query_text = re.sub(r"\s+", " ", str(query.get("query", ""))).strip()
        if len(query_text) < 4:
            continue
        key = query_text.lower()
        if key in seen:
            continue
        seen.add(key)

        anchors = query.get("anchors", [])
        if not isinstance(anchors, list):
            anchors = []
        anchors = [str(anchor) for anchor in anchors if str(anchor).strip()]
        if not anchors:
            anchors = tokenize_for_anchors(query_text)[:3]

        likely_contacts = query.get("likely_contacts", [])
        if not isinstance(likely_contacts, list):
            likely_contacts = []
        likely_contacts = [
            str(name)
            for name in likely_contacts
            if str(name) in contact_names
        ]
        if not likely_contacts:
            likely_contacts = [
                str(contact.get("name", ""))
                for contact in contacts[:2]
                if contact.get("name")
            ]

        normalized.append(
            {
                "query": query_text,
                "type": str(query.get("type") or infer_event_type(query_text)),
                "location_scope": str(query.get("location_scope") or "regional/national"),
                "relevance": str(query.get("relevance") or "Persona-relevant public context"),
                "likely_contacts": likely_contacts,
                "anchors": anchors,
            }
        )
        if len(normalized) >= max_queries:
            break
    return normalized


def fallback_queries_from_brief(
    brief: dict[str, Any] | None,
    contacts: list[dict[str, Any]],
    max_queries: int,
) -> list[dict[str, Any]]:
    if not brief:
        return []
    location_anchors = [
        str(anchor)
        for anchor in brief.get("location_anchors", [])
        if str(anchor).strip()
    ]
    public_anchors = [
        str(anchor)
        for anchor in brief.get("public_interest_anchors", [])
        if str(anchor).strip()
    ]
    primary_locations = location_anchors[:3]
    query_specs = []
    for location in primary_locations:
        query_specs.extend(
            [
                (f'"{location}" weather', "weather", [location, "weather"]),
                (f'"{location}" outage', "outage", [location, "outage"]),
                (f'"{location}" events', "local_event", [location, "events"]),
                (f'"{location}" news', "local_news", [location, "news"]),
            ]
        )
    for anchor in public_anchors[:8]:
        if primary_locations:
            query_specs.append(
                (
                    f'"{anchor}" "{primary_locations[0]}"',
                    infer_event_type(anchor),
                    [anchor, primary_locations[0]],
                )
            )
        else:
            query_specs.append((f'"{anchor}"', infer_event_type(anchor), [anchor]))

    fallback = []
    seen = set()
    for query_text, event_type, anchors in query_specs:
        key = query_text.lower()
        if key in seen:
            continue
        seen.add(key)
        fallback.append(
            {
                "query": query_text,
                "type": event_type,
                "location_scope": "local" if primary_locations and primary_locations[0].lower() in key else "regional/national",
                "relevance": "Fallback query derived from GPT news brief anchors",
                "likely_contacts": [
                    str(contact.get("name", ""))
                    for contact in contacts[:2]
                    if contact.get("name")
                ],
                "anchors": anchors,
            }
        )
        if len(fallback) >= max_queries:
            break
    return fallback


def generate_news_brief(
    profile: dict[str, Any],
    social_circle: dict[str, Any],
    log_window: dict[str, Any],
    client,
    model: str,
    provider: str,
    backend: str,
) -> dict[str, Any]:
    template = NEWS_BRIEF_PROMPT_PATH.read_text(encoding="utf-8")
    template = fill_json(template, "{{PROFILE_JSON}}", profile)
    template = fill_json(template, "{{SOCIAL_CIRCLE_JSON}}", social_circle)
    template = fill_json(template, "{{LOG_WINDOW_JSON}}", log_window)
    raw = call_model(client, model, template, provider, backend)
    brief = extract_json(raw)
    if not isinstance(brief.get("gdelt_queries"), list):
        raise ValueError("news brief missing gdelt_queries")
    return brief


def get_or_create_news_brief(
    profile: dict[str, Any],
    social_circle: dict[str, Any],
    log_window: dict[str, Any],
    brief_path: Path,
    refresh: bool,
    client,
    model: str,
    provider: str,
    backend: str,
) -> dict[str, Any]:
    if brief_path.exists() and not refresh:
        return load_json(brief_path)
    print(f"[news-brief] generating: {brief_path}")
    brief = generate_news_brief(
        profile,
        social_circle,
        log_window,
        client,
        model,
        provider,
        backend,
    )
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(brief_path, brief)
    print(f"Wrote news brief: {brief_path}")
    return brief


def gdelt_datetime(value: str, is_end: bool = False) -> str:
    suffix = "235959" if is_end else "000000"
    return value.replace("-", "") + suffix


def cache_key_for_query(query: str, start_date: str, end_date: str, max_records: int) -> str:
    raw = f"{query}|{start_date}|{end_date}|{max_records}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def gdelt_cache_path(query: str, start_date: str, end_date: str, max_records: int) -> Path:
    return (
        STEP_DIR
        / "data_samples"
        / "input"
        / ".gdelt_cache"
        / f"{cache_key_for_query(query, start_date, end_date, max_records)}.json"
    )


def fetch_gdelt_articles(
    query: str,
    start_date: str,
    end_date: str,
    max_records: int = DEFAULT_GDELT_MAX_RECORDS,
    delay_seconds: float = DEFAULT_GDELT_DELAY_SECONDS,
) -> list[dict[str, Any]]:
    cache_path = gdelt_cache_path(query, start_date, end_date, max_records)
    if cache_path.exists():
        payload = load_json(cache_path)
        articles = payload.get("articles", [])
        return articles if isinstance(articles, list) else []

    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "startdatetime": gdelt_datetime(start_date),
        "enddatetime": gdelt_datetime(end_date, is_end=True),
        "maxrecords": str(max_records),
        "sort": "HybridRel",
    }
    request = Request(
        GDELT_DOC_API + "?" + urlencode(params),
        headers={"User-Agent": "PersonaBench-Step4B/1.0"},
    )

    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    for attempt in range(1, 4):
        if delay_seconds > 0:
            time.sleep(delay_seconds * attempt)
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            break
        except HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < 3:
                time.sleep(10 * attempt)
                continue
            raise
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(3 * attempt)
                continue
            raise

    if payload is None:
        raise RuntimeError(f"GDELT fetch failed: {last_error}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache_path, payload)
    articles = payload.get("articles", [])
    return articles if isinstance(articles, list) else []


def parse_gdelt_date(value: str) -> str | None:
    match = re.match(r"(\d{4})(\d{2})(\d{2})", value or "")
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def normalized_words(value: str) -> set[str]:
    return set(tokenize_for_anchors(value))


def generic_title_rejected(title: str) -> bool:
    lowered = title.lower().strip()
    words = tokenize_for_anchors(title)
    if len(words) < 3:
        return True
    blocked_exact = {
        "targeted news service",
        "redding chico eureka",
    }
    if lowered in blocked_exact:
        return True
    blocked_terms = [
        "nightlife guide",
        "horoscope",
        "stock market today",
        "celebrity birthdays",
        "lottery numbers",
    ]
    return any(term in lowered for term in blocked_terms)


def url_has_stale_year(url: str, event_date: str) -> bool:
    event_year = event_date[:4]
    years = re.findall(r"/((?:19|20)\d{2})(?:/|-)", url)
    return any(year != event_year for year in years)


def anchor_overlap_score(title: str, domain: str, url: str, anchors: list[str]) -> int:
    haystack = f"{title} {domain} {url}".lower()
    score = 0
    for anchor in anchors:
        anchor_text = str(anchor).lower().strip()
        if not anchor_text:
            continue
        if anchor_text in haystack:
            score += 3
            continue
        anchor_words = normalized_words(anchor_text)
        if anchor_words and anchor_words & normalized_words(haystack):
            score += 1
    return score


def article_event_score(article: dict[str, Any], query_meta: dict[str, Any], city: str) -> int:
    title = str(article.get("title", ""))
    domain = str(article.get("domain", ""))
    url = str(article.get("url", ""))
    score = 0
    score += anchor_overlap_score(title, domain, url, query_meta.get("anchors", []))
    if city and city.lower() in title.lower():
        score += 3
    if domain and domain not in {"targetednews.com", "finanznachrichten.de"}:
        score += 2
    if 25 <= len(title) <= 140:
        score += 1
    if any(term in title.lower() for term in ["recap", "stock market", "obituary", "nightlife guide"]):
        score -= 4
    return score


def normalize_article_event(
    article: dict[str, Any],
    query_meta: dict[str, Any],
    city: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    event_date = parse_gdelt_date(str(article.get("seendate", "")))
    if event_date is None or event_date < start_date or event_date > end_date:
        return None
    title = re.sub(r"\s+", " ", str(article.get("title", ""))).strip()
    url = str(article.get("url", "")).strip()
    domain = str(article.get("domain", "")).strip()
    if not title or not url:
        return None
    if url_has_stale_year(url, event_date):
        return None
    if generic_title_rejected(title):
        return None
    if anchor_overlap_score(title, domain, url, query_meta.get("anchors", [])) <= 0:
        return None
    if domain in {"targetednews.com", "finanznachrichten.de"}:
        return None
    return {
        "date": event_date,
        "summary": title,
        "type": query_meta["type"],
        "location_scope": query_meta["location_scope"],
        "relevance": query_meta["relevance"],
        "likely_contacts": query_meta["likely_contacts"],
        "source_name": domain or "GDELT indexed source",
        "source_url": url,
        "retrieved_via": "GDELT DOC 2.1 API",
        "query": query_meta["query"],
        "_score": article_event_score(article, query_meta, city),
    }


def select_timeline_events(
    events: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    count: int,
) -> list[dict[str, Any]]:
    if count <= 0:
        return []

    deduped: dict[str, dict[str, Any]] = {}
    for event in events:
        key = (
            re.sub(r"[^a-z0-9]+", " ", event["summary"].lower()).strip(),
            event["source_url"],
        )
        current = deduped.get(str(key))
        if current is None or event.get("_score", 0) > current.get("_score", 0):
            deduped[str(key)] = event

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    total_weeks = max(1, ((end - start).days // 7) + 1)
    events_by_week: dict[int, list[dict[str, Any]]] = {}
    for event in deduped.values():
        week = min(total_weeks - 1, max(0, (date.fromisoformat(event["date"]) - start).days // 7))
        events_by_week.setdefault(week, []).append(event)

    for week_events in events_by_week.values():
        week_events.sort(key=lambda item: (-item.get("_score", 0), item["date"], item["source_url"]))

    selected: list[dict[str, Any]] = []
    selected_urls: set[str] = set()

    for week in range(total_weeks):
        week_events = events_by_week.get(week, [])
        if not week_events:
            continue
        event = week_events[0]
        selected.append(event)
        selected_urls.add(event["source_url"])
        if len(selected) >= count:
            break

    if len(selected) < count:
        by_type_count: dict[str, int] = {}
        for event in selected:
            by_type_count[event.get("type", "unknown")] = by_type_count.get(event.get("type", "unknown"), 0) + 1
        remaining = [
            event
            for week_events in events_by_week.values()
            for event in week_events
            if event["source_url"] not in selected_urls
        ]
        remaining.sort(
            key=lambda item: (
                by_type_count.get(item.get("type", "unknown"), 0),
                -item.get("_score", 0),
                item["date"],
                item["source_url"],
            )
        )
        for event in remaining:
            selected.append(event)
            selected_urls.add(event["source_url"])
            by_type_count[event.get("type", "unknown")] = by_type_count.get(event.get("type", "unknown"), 0) + 1
            if len(selected) >= count:
                break

    public = []
    for event in sorted(selected, key=lambda item: item["date"]):
        cleaned = dict(event)
        cleaned.pop("_score", None)
        public.append(cleaned)
    return public


def discover_news_events(
    profile: dict[str, Any],
    social_circle: dict[str, Any],
    log_window: dict[str, Any],
    count: int,
    min_count: int,
    news_brief: dict[str, Any] | None = None,
    max_queries: int = DEFAULT_GDELT_MAX_QUERIES,
    max_records: int = DEFAULT_GDELT_MAX_RECORDS,
    delay_seconds: float = DEFAULT_GDELT_DELAY_SECONDS,
) -> list[dict[str, Any]]:
    start_date = str(log_window.get("start_date", ""))
    end_date = str(log_window.get("end_date", ""))
    if not start_date or not end_date:
        raise ValueError("app log missing log_window.start_date/end_date")
    city, _state = city_and_state(profile)
    contacts = contacts_from_social_circle(social_circle)
    queries = (
        normalize_brief_queries(news_brief, contacts, max_queries)
        if news_brief
        else []
    )
    fallback_queries = fallback_queries_from_brief(news_brief, contacts, max_queries)
    heuristic_queries = query_terms_from_context(profile, social_circle, max_queries=max_queries)
    if not queries:
        queries = query_terms_from_context(profile, social_circle, max_queries=max_queries)
    if not queries:
        raise ValueError("Could not derive news queries from profile/social-circle context")

    events: list[dict[str, Any]] = []
    seen_query_keys = set()

    def run_queries(query_batch: list[dict[str, Any]], label: str) -> None:
        nonlocal events
        for query_meta in query_batch:
            query_key = str(query_meta["query"]).lower()
            if query_key in seen_query_keys:
                continue
            seen_query_keys.add(query_key)
            print(f"[news] searching ({label}): {query_meta['query']}")
            try:
                articles = fetch_gdelt_articles(
                    query_meta["query"],
                    start_date,
                    end_date,
                    max_records=max_records,
                    delay_seconds=delay_seconds,
                )
            except Exception as exc:
                print(f"[news] skipped query after fetch error: {exc}")
                continue
            for article in articles:
                event = normalize_article_event(article, query_meta, city, start_date, end_date)
                if event is not None:
                    events.append(event)

    run_queries(queries, "brief")
    selected = select_timeline_events(events, start_date, end_date, count)

    if len(selected) < min_count and fallback_queries:
        print(
            f"[news] only {len(selected)} selected events; broadening with brief fallback queries"
        )
        run_queries(fallback_queries, "brief-fallback")
        selected = select_timeline_events(events, start_date, end_date, count)

    if len(selected) < min_count and heuristic_queries:
        print(
            f"[news] only {len(selected)} selected events; broadening with generic heuristic queries"
        )
        run_queries(heuristic_queries, "heuristic")
        selected = select_timeline_events(events, start_date, end_date, count)

    if not selected:
        raise RuntimeError(
            "No sourced news events found. Provide --news-events or adjust persona/profile inputs."
        )
    if len(selected) < min_count:
        raise RuntimeError(
            f"Only found {len(selected)} sourced news events; minimum is {min_count}. "
            "Try increasing --gdelt-max-queries/--gdelt-max-records, lowering "
            "--min-news-events, or providing --news-events."
        )
    return selected


def session_date(session: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(session.get("date", "")))
    except ValueError:
        return None


def select_surprise_assignments(
    filler_sessions: list[dict[str, Any]],
    news_events: list[dict[str, Any]],
    surprise_rate: float,
    max_surprises: int,
) -> dict[str, dict[str, Any]]:
    if not news_events or not filler_sessions:
        return {}

    target = planned_surprise_count(filler_sessions, surprise_rate, max_surprises)
    candidates = []
    for session in filler_sessions:
        messages = session.get("messages") or []
        parsed_date = session_date(session)
        if parsed_date is None or not messages:
            continue
        ranked_events = sorted(
            (
                (
                    abs((parsed_date - date.fromisoformat(str(event["date"]))).days),
                    event_index,
                    event,
                )
                for event_index, event in enumerate(news_events)
            ),
            key=lambda item: (item[0], item[1]),
        )
        distance, event_index, event = ranked_events[0]
        candidates.append((distance, event_index, str(session["session_id"]), session, event))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    selected: dict[str, dict[str, Any]] = {}
    event_count = max(len(news_events), 1)
    per_event_soft_cap = max(1, round((target / event_count) * 1.35))
    event_usage: dict[str, int] = {}

    for _distance, event_index, session_id, session, event in candidates:
        event_key = f"{event.get('date')}|{event.get('summary')}|{event_index}"
        if event_usage.get(event_key, 0) >= per_event_soft_cap:
            continue
        messages = session.get("messages") or []
        selected[session_id] = {
            "event": event,
            "message_index": min(len(messages) - 1, max(0, len(messages) // 2)),
        }
        event_usage[event_key] = event_usage.get(event_key, 0) + 1
        if len(selected) >= target:
            break

    if len(selected) < target:
        for _distance, event_index, session_id, session, event in candidates:
            if session_id in selected:
                continue
            messages = session.get("messages") or []
            selected[session_id] = {
                "event": event,
                "message_index": min(len(messages) - 1, max(0, len(messages) // 2)),
            }
            if len(selected) >= target:
                break
    return selected


def planned_surprise_count(
    filler_sessions: list[dict[str, Any]], surprise_rate: float, max_surprises: int
) -> int:
    if not filler_sessions or surprise_rate <= 0 or max_surprises == 0:
        return 0
    return min(max_surprises, max(1, round(len(filler_sessions) * surprise_rate)))


def build_prompt_sessions(
    sessions: list[dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    prompt_sessions = []
    for session in sessions:
        session_id = str(session["session_id"])
        assignment = assignments.get(session_id)
        messages = []
        for message_index, message in enumerate(session.get("messages", [])):
            item = {
                "message_index": message_index,
                "time": message.get("time", ""),
                "sender": message.get("sender", ""),
                "original_text": message.get("text", ""),
                "target_length_chars": len(str(message.get("text", ""))),
            }
            if assignment and assignment["message_index"] == message_index:
                item["surprise_event"] = assignment["event"]
            messages.append(item)
        prompt_sessions.append(
            {
                "session_id": session_id,
                "date": session.get("date", ""),
                "contact": session.get("contact", ""),
                "messages": messages,
            }
        )
    return prompt_sessions


def build_prompt(
    app_log: dict[str, Any],
    variant: str,
    prompt_sessions: list[dict[str, Any]],
) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    template = template.replace("{{VARIANT}}", variant)
    template = template.replace("{{PERSONA_NAME}}", str(app_log.get("persona_name", "")))
    template = fill_json(template, "{{LOG_WINDOW_JSON}}", app_log.get("log_window", {}))
    template = fill_json(template, "{{SESSIONS_JSON}}", prompt_sessions)
    return template


def validate_batch_response(
    response: dict[str, Any],
    batch: list[dict[str, Any]],
) -> dict[str, list[str]]:
    sessions = response.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("Model output missing sessions array")

    expected = {
        str(session["session_id"]): len(session.get("messages", []))
        for session in batch
    }
    replacements: dict[str, list[str]] = {}
    for session in sessions:
        session_id = str(session.get("session_id", ""))
        if session_id not in expected:
            raise ValueError(f"Unexpected session_id in model output: {session_id}")
        messages = session.get("messages")
        if not isinstance(messages, list):
            raise ValueError(f"Session {session_id} missing messages array")
        by_index: dict[int, str] = {}
        for message in messages:
            message_index = message.get("message_index")
            text = message.get("text")
            if not isinstance(message_index, int) or not isinstance(text, str):
                raise ValueError(f"Invalid message replacement in session {session_id}")
            by_index[message_index] = text
        if sorted(by_index) != list(range(expected[session_id])):
            raise ValueError(f"Session {session_id} replacement indexes do not match input")
        replacements[session_id] = [by_index[index] for index in range(expected[session_id])]

    if set(replacements) != set(expected):
        missing = sorted(set(expected) - set(replacements))
        raise ValueError(f"Model output missing sessions: {missing[:5]}")
    return replacements


def rewrite_batch(
    client,
    model: str,
    provider: str,
    backend: str,
    app_log: dict[str, Any],
    variant: str,
    batch: list[dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    max_attempts: int,
) -> dict[str, list[str]]:
    prompt_sessions = build_prompt_sessions(batch, assignments)
    prompt = build_prompt(app_log, variant, prompt_sessions)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        raw = call_model(client, model, prompt, provider, backend)
        try:
            return validate_batch_response(extract_json(raw), batch)
        except Exception as exc:
            last_error = exc
            print(f"[batch] invalid model output attempt {attempt}/{max_attempts}: {exc}")
    raise RuntimeError(f"Could not get valid batch output: {last_error}")


def assert_filler_structure_unchanged(
    original: dict[str, Any],
    variant: dict[str, Any],
) -> None:
    original_sessions = original.get("messenger", {}).get("filler_sessions", [])
    variant_sessions = variant.get("messenger", {}).get("filler_sessions", [])
    if len(original_sessions) != len(variant_sessions):
        raise AssertionError("filler session count changed")

    for session_index, (original_session, variant_session) in enumerate(
        zip(original_sessions, variant_sessions)
    ):
        for key in ("session_id", "date", "contact"):
            if original_session.get(key) != variant_session.get(key):
                raise AssertionError(f"filler session {session_index} changed {key}")
        original_messages = original_session.get("messages", [])
        variant_messages = variant_session.get("messages", [])
        if len(original_messages) != len(variant_messages):
            raise AssertionError(f"filler session {session_index} message count changed")
        for message_index, (original_message, variant_message) in enumerate(
            zip(original_messages, variant_messages)
        ):
            original_meta = {k: v for k, v in original_message.items() if k != "text"}
            variant_meta = {k: v for k, v in variant_message.items() if k != "text"}
            if original_meta != variant_meta:
                raise AssertionError(
                    f"filler session {session_index} message {message_index} metadata changed"
                )


def assert_app_log_invariants(original: dict[str, Any], variant: dict[str, Any]) -> None:
    for key in ("persona_name", "log_window", "hidden_facts", "cross_app_index"):
        if original.get(key) != variant.get(key):
            raise AssertionError(f"{key} changed")

    original_messenger = original.get("messenger", {})
    variant_messenger = variant.get("messenger", {})
    if original_messenger.get("meaningful_sessions") != variant_messenger.get(
        "meaningful_sessions"
    ):
        raise AssertionError("messenger.meaningful_sessions changed")

    if original.get("calendar", {}).get("events") != variant.get("calendar", {}).get("events"):
        raise AssertionError("calendar.events changed")

    assert_filler_structure_unchanged(original, variant)


def refresh_token_stats(app_log: dict[str, Any]) -> None:
    messenger = app_log.get("messenger", {})
    meaningful_sessions = messenger.get("meaningful_sessions", [])
    filler_sessions = messenger.get("filler_sessions", [])
    meaningful_tokens = token_estimate(meaningful_sessions)
    filler_tokens = token_estimate(filler_sessions)
    stats = dict(app_log.get("token_stats", {}))
    stats["meaningful_token_count"] = meaningful_tokens
    stats["filler_token_count"] = filler_tokens
    stats["approximate_tokens"] = meaningful_tokens + filler_tokens
    stats["ratio_filler_to_meaningful"] = f"{filler_tokens / max(meaningful_tokens, 1):.2f}:1"
    app_log["token_stats"] = stats


def build_surprises_woven(assignments: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    woven = []
    for session_id, assignment in sorted(assignments.items()):
        event = assignment["event"]
        woven.append(
            {
                "news_event_date": event.get("date", ""),
                "referenced_in_session_id": session_id,
                "message_index": assignment["message_index"],
                "summary": event.get("summary", ""),
            }
        )
    return woven


def report_for(
    original: dict[str, Any],
    variant: dict[str, Any],
    variant_name: str,
    model: str,
    assignments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    original_filler = original.get("messenger", {}).get("filler_sessions", [])
    variant_filler = variant.get("messenger", {}).get("filler_sessions", [])
    changed_messages = 0
    total_messages = 0
    for original_session, variant_session in zip(original_filler, variant_filler):
        for original_message, variant_message in zip(
            original_session.get("messages", []),
            variant_session.get("messages", []),
        ):
            total_messages += 1
            if original_message.get("text") != variant_message.get("text"):
                changed_messages += 1

    return {
        "variant": variant_name,
        "model": model,
        "persona_name": variant.get("persona_name", ""),
        "filler_session_count": len(variant_filler),
        "filler_message_count": total_messages,
        "changed_filler_message_count": changed_messages,
        "surprise_session_count": len(assignments),
        "token_stats": variant.get("token_stats", {}),
        "invariants_checked": True,
    }


def rewrite_filler(
    app_log: dict[str, Any],
    client,
    model: str,
    provider: str,
    backend: str,
    variant: str,
    news_events: list[dict[str, Any]],
    batch_size: int,
    surprise_rate: float,
    max_surprises: int,
    max_batch_attempts: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = copy.deepcopy(app_log)
    filler_sessions = output.get("messenger", {}).get("filler_sessions", [])
    if not isinstance(filler_sessions, list):
        raise ValueError("app log missing messenger.filler_sessions array")

    assignments = (
        select_surprise_assignments(
            filler_sessions,
            news_events,
            surprise_rate=surprise_rate,
            max_surprises=max_surprises,
        )
        if variant == "surprise"
        else {}
    )

    print(
        f"[step4b] rewriting {len(filler_sessions)} filler sessions "
        f"({variant}, {len(assignments)} surprise sessions)"
    )

    for start in range(0, len(filler_sessions), batch_size):
        end = min(start + batch_size, len(filler_sessions))
        batch = filler_sessions[start:end]
        print(f"[step4b] batch {start // batch_size + 1}: sessions {start + 1}-{end}")
        batch_assignments = {
            str(session["session_id"]): assignments[str(session["session_id"])]
            for session in batch
            if str(session.get("session_id")) in assignments
        }
        replacements = rewrite_batch(
            client,
            model,
            provider,
            backend,
            app_log,
            variant,
            batch,
            batch_assignments,
            max_attempts=max_batch_attempts,
        )
        for session in batch:
            session_id = str(session["session_id"])
            for message, text in zip(session.get("messages", []), replacements[session_id]):
                message["text"] = text

    output["surprises_woven"] = build_surprises_woven(assignments) if variant == "surprise" else []
    refresh_token_stats(output)
    assert_app_log_invariants(app_log, output)
    return output, report_for(app_log, output, variant, model, assignments)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona", help="Persona shorthand, e.g. alicia_gonzalez")
    parser.add_argument("--app-logs", type=Path, default=None, help="Existing Step 4 app log JSON")
    parser.add_argument("--profile", type=Path, default=None, help="Step 2 verification JSON used for news discovery")
    parser.add_argument("--social-circle", type=Path, default=None, help="Step 3 social-circle verification JSON used for news discovery")
    parser.add_argument("--variant", choices=["baseline", "surprise"], required=True)
    parser.add_argument("--news-events", type=Path, default=None, help="JSON array of sourced events for surprise variant")
    parser.add_argument("--news-brief", type=Path, default=None, help="Cached GPT search-strategy brief for surprise news discovery")
    parser.add_argument("--refresh-news-brief", action="store_true", help="Regenerate GPT news-search brief before GDELT discovery")
    parser.add_argument("--refresh-news-events", action="store_true", help="Regenerate persona news events even if the input file exists")
    parser.add_argument("--news-event-count", type=int, default=DEFAULT_NEWS_EVENT_COUNT)
    parser.add_argument("--min-news-events", type=int, default=DEFAULT_MIN_NEWS_EVENTS)
    parser.add_argument("--gdelt-max-queries", type=int, default=DEFAULT_GDELT_MAX_QUERIES)
    parser.add_argument("--gdelt-max-records", type=int, default=DEFAULT_GDELT_MAX_RECORDS)
    parser.add_argument("--gdelt-delay-seconds", type=float, default=DEFAULT_GDELT_DELAY_SECONDS)
    parser.add_argument("--output", type=Path, default=STEP_DIR / "data_samples" / "output")
    parser.add_argument("--backend", choices=SUPPORTED_BACKENDS, default=None)
    parser.add_argument("--provider", choices=SUPPORTED_PROVIDERS, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--surprise-rate", type=float, default=DEFAULT_SURPRISE_RATE)
    parser.add_argument("--max-surprises", type=int, default=DEFAULT_MAX_SURPRISES)
    parser.add_argument("--max-batch-attempts", type=int, default=2)
    parser.add_argument("--generate-news-only", action="store_true", help="Create/read news_events and exit before filler generation")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print planned counts without calling a model")
    args = parser.parse_args()

    if args.app_logs is None and not args.persona:
        parser.error("pass --persona or --app-logs")

    if args.backend is None:
        args.backend = os.environ.get("PERSONABENCH_BACKEND", "codex")
    provider = (
        provider_for_backend(args.backend, args.provider or "anthropic")
        if args.backend in API_BACKENDS
        else (args.provider or "anthropic")
    )
    if args.model is None:
        args.model = default_model_for_backend(args.backend, "generator")

    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    if args.surprise_rate < 0:
        parser.error("--surprise-rate must be >= 0")
    if args.max_surprises < 0:
        parser.error("--max-surprises must be >= 0")
    if args.news_event_count < 0:
        parser.error("--news-event-count must be >= 0")
    if args.min_news_events < 0:
        parser.error("--min-news-events must be >= 0")
    if args.min_news_events > args.news_event_count:
        parser.error("--min-news-events cannot exceed --news-event-count")
    if args.gdelt_max_queries < 1:
        parser.error("--gdelt-max-queries must be >= 1")
    if args.gdelt_max_records < 1:
        parser.error("--gdelt-max-records must be >= 1")
    if args.gdelt_delay_seconds < 0:
        parser.error("--gdelt-delay-seconds must be >= 0")
    if args.backend in API_BACKENDS and not check_api_key(provider):
        parser.error(f"{provider.upper()}_API_KEY is not set")

    app_logs_path = resolve_app_logs_path(args.persona, args.app_logs)
    profile_path = resolve_profile_path(args.persona, args.profile)
    social_circle_path = resolve_social_circle_path(args.persona, args.social_circle)

    app_log = load_json(app_logs_path)

    news_events: list[dict[str, Any]] = []
    news_events_path = args.news_events
    news_brief_path = args.news_brief
    planned_news_discovery = False
    planned_news_brief_generation = False
    if args.variant == "surprise":
        if news_events_path is None and args.persona:
            news_events_path = default_news_events_path(args.persona)
        if news_events_path is None:
            news_events_path = STEP_DIR / "data_samples" / "input" / f"{app_logs_path.stem}_news_events.json"
        if news_brief_path is None and args.persona:
            news_brief_path = default_news_brief_path(args.persona)
        if news_brief_path is None:
            news_brief_path = STEP_DIR / "data_samples" / "input" / f"{app_logs_path.stem}_news_brief.json"

        should_discover_news = args.refresh_news_events or not news_events_path.exists()
        planned_news_discovery = should_discover_news
        planned_news_brief_generation = (
            should_discover_news
            and (args.refresh_news_brief or not news_brief_path.exists())
        )
        if should_discover_news and not args.dry_run:
            if profile_path is None or social_circle_path is None:
                parser.error(
                    "--profile and --social-circle are required to auto-generate news events "
                    "when --persona is not provided"
                )
            if not profile_path.exists():
                parser.error(f"profile file not found: {profile_path}")
            if not social_circle_path.exists():
                parser.error(f"social-circle file not found: {social_circle_path}")
            profile = profile_from_bundle(load_json(profile_path))
            social_circle = social_circle_from_bundle(load_json(social_circle_path))
            brief_client = make_client(provider) if args.backend in API_BACKENDS else None
            news_brief = get_or_create_news_brief(
                profile,
                social_circle,
                app_log.get("log_window", {}),
                news_brief_path,
                refresh=args.refresh_news_brief,
                client=brief_client,
                model=args.model,
                provider=provider,
                backend=args.backend,
            )
            news_events = discover_news_events(
                profile,
                social_circle,
                app_log.get("log_window", {}),
                count=args.news_event_count,
                min_count=args.min_news_events,
                news_brief=news_brief,
                max_queries=args.gdelt_max_queries,
                max_records=args.gdelt_max_records,
                delay_seconds=args.gdelt_delay_seconds,
            )
            news_events_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(news_events_path, news_events)
            print(f"Wrote news events: {news_events_path}")
        elif news_events_path.exists():
            news_events = load_news_events(news_events_path)
        elif not args.dry_run:
            parser.error(f"news-events file not found: {news_events_path}")

    if args.generate_news_only:
        if args.variant != "surprise":
            parser.error("--generate-news-only only applies to --variant surprise")
        print(json.dumps(
            {
                "news_brief_path": str(news_brief_path) if news_brief_path else None,
                "news_events_path": str(news_events_path),
                "news_event_count": len(news_events),
                "generated": planned_news_discovery and not args.dry_run,
                "news_brief_generated": planned_news_brief_generation and not args.dry_run,
            },
            indent=2,
        ))
        return

    filler_sessions = app_log.get("messenger", {}).get("filler_sessions", [])
    assignments = (
        select_surprise_assignments(
            filler_sessions,
            news_events,
            surprise_rate=args.surprise_rate,
            max_surprises=args.max_surprises,
        )
        if args.variant == "surprise"
        else {}
    )
    planned_surprise_session_count = (
        len(assignments)
        if news_events
        else planned_surprise_count(filler_sessions, args.surprise_rate, args.max_surprises)
        if args.variant == "surprise"
        else 0
    )

    if args.dry_run:
        print(json.dumps(
            {
                "app_logs": str(app_logs_path),
                "persona_name": app_log.get("persona_name", ""),
                "variant": args.variant,
                "backend": args.backend,
                "model": args.model,
                "filler_session_count": len(filler_sessions),
                "planned_batches": (len(filler_sessions) + args.batch_size - 1) // args.batch_size,
                "planned_surprise_session_count": planned_surprise_session_count,
                "news_events_path": str(news_events_path) if news_events_path else None,
                "news_brief_path": str(news_brief_path) if news_brief_path else None,
                "news_event_count": len(news_events),
                "planned_news_discovery": planned_news_discovery,
                "planned_news_brief_generation": planned_news_brief_generation,
            },
            indent=2,
        ))
        return

    client = make_client(provider) if args.backend in API_BACKENDS else None
    args.output.mkdir(parents=True, exist_ok=True)

    rewritten, report = rewrite_filler(
        app_log,
        client,
        args.model,
        provider,
        args.backend,
        args.variant,
        news_events,
        batch_size=args.batch_size,
        surprise_rate=args.surprise_rate,
        max_surprises=args.max_surprises,
        max_batch_attempts=args.max_batch_attempts,
    )

    out_path = output_path_for(app_logs_path, args.output, args.variant, args.model)
    report_path = out_path.with_name(out_path.stem + "_report.json")
    write_json(out_path, rewritten)
    write_json(report_path, report)
    print(f"Wrote app log: {out_path}")
    print(f"Wrote report: {report_path}")


if __name__ == "__main__":
    main()
