"""Trusted, stateless extraction policies over public evidence only.

The registry deliberately does not load arbitrary candidate code. It is a data
boundary for reviewed implementations, not a sandbox for untrusted programs.
Whole records are the first supported spans: cutting a sentence can lose a
negation, a speaker, or the scope of a permission.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime

POLICIES = ("full", "lexical", "linked")
PUBLIC_FIELDS = {
    "episode_id",
    "request",
    "request_timestamp",
    "timezone",
    "task_state",
    "capabilities",
    "logs",
}
LOG_FIELDS = {"id", "timestamp", "channel", "speaker", "text"}
STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "could",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "should",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "to",
    "use",
    "was",
    "we",
    "were",
    "what",
    "when",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
    "am",
    "about",
    "all",
    "also",
    "any",
    "each",
    "give",
    "help",
    "just",
    "only",
    "please",
    "so",
    "some",
    "than",
    "then",
    "through",
    "using",
    "want",
    "already",
    "available",
    "current",
    "stated",
    "user",
    "assistant",
    "request",
}


def validate_public(public):
    if not isinstance(public, dict) or set(public) != PUBLIC_FIELDS:
        raise ValueError("selector requires exactly the public episode fields")
    if any(not isinstance(public[k], str) for k in PUBLIC_FIELDS - {"logs"}):
        raise ValueError("public metadata must be strings")
    logs = public["logs"]
    if not isinstance(logs, list):
        raise TypeError("public logs must be a list")
    ids = set()
    for log in logs:
        if not isinstance(log, dict) or set(log) != LOG_FIELDS:
            raise ValueError("selector requires public log fields only")
        if any(not isinstance(v, str) or not v for v in log.values()):
            raise ValueError("public log fields must be nonempty strings")
        if log["id"] in ids:
            raise ValueError("duplicate public log ID")
        ids.add(log["id"])


def log_cost(log):
    """Characters of canonical JSON including attribution, not a token estimate."""
    import json

    return len(json.dumps(log, ensure_ascii=False, sort_keys=True))


def logs_cost(logs):
    return 2 + sum(log_cost(log) for log in logs) + 2 * max(0, len(logs) - 1)


def tokens(text):
    # Keep numbers; case-folding never changes the evidence rendered to a model.
    return [t for t in re.findall(r"\w+", text.casefold()) if t not in STOP]


def lexical_scores(public):
    docs = [
        Counter(tokens(log["text"] + " " + log["speaker"])) for log in public["logs"]
    ]
    n = len(docs)
    df = Counter(t for doc in docs for t in doc)
    idf = {
        t: math.log(1 + (n - count + 0.5) / (count + 0.5)) for t, count in df.items()
    }
    query = set(tokens(public["request"] + " " + public["task_state"]))
    average = sum(sum(doc.values()) for doc in docs) / max(n, 1) or 1
    scores = []
    for doc in docs:
        normalization = 1.2 * (0.25 + 0.75 * sum(doc.values()) / average)
        scores.append(
            sum(
                idf[t] * doc[t] * 2.2 / (doc[t] + normalization)
                for t in sorted(query & doc.keys())
            )
        )
    return docs, idf, scores


def select_context(public, budget, policy="lexical"):
    """Return complete, verbatim source spans, bounded by serialized log size.

    ``full`` requires an unbounded budget. The other policies preserve all logs
    when they fit; otherwise they rank evidence without consulting a contract.
    ``linked`` reserves one third of the budget for recent records connected to
    the four best lexical anchors by at least two informative words. It retains
    earlier anchors alongside updates; it does not decide which claim is true.
    """
    validate_public(public)
    if policy not in POLICIES:
        raise ValueError("unknown registered policy")
    if policy == "full":
        if budget is not None:
            raise ValueError("full-history baseline must be unbounded")
    elif type(budget) is not int or budget < 2:
        raise ValueError("retrieval budget must be an integer of at least 2 characters")
    logs = public["logs"]
    if policy == "full" or logs_cost(logs) <= budget:
        indices = range(len(logs))
    else:
        docs, idf, scores = lexical_scores(public)
        times = [datetime.fromisoformat(log["timestamp"]) for log in logs]
        ranked = sorted(
            range(len(logs)), key=lambda i: (-scores[i], -times[i].timestamp(), i)
        )
        chosen = set()
        used = 2

        def take(order, limit):
            nonlocal used
            for i in order:
                cost = log_cost(logs[i]) + (2 if chosen else 0)
                if i not in chosen and used + cost <= limit:
                    chosen.add(i)
                    used += cost

        if policy == "linked":
            # Informative shared words act as conservative lexical entity links.
            # No subject/permission claims are inferred by this heuristic.
            take(ranked, 2 + (budget - 2) * 2 // 3)
            links = set()
            for anchor in ranked[:4]:
                if scores[anchor] <= 0:
                    continue
                terms = {t for t in docs[anchor] if t.isalpha() and idf[t] >= 1.0}
                candidates = [
                    i
                    for i in ranked
                    if i != anchor and len(terms & docs[i].keys()) >= 2
                ]
                # Retrieve both newer corrections and older standing instructions.
                newest = sorted(
                    candidates, key=lambda i: (-times[i].timestamp(), -scores[i], i)
                )
                links.update(newest[:2])
            take(
                sorted(links, key=lambda i: (-times[i].timestamp(), -scores[i], i)),
                budget,
            )
        take(ranked, budget)
        indices = sorted(chosen)
    return [
        {"log_id": logs[i]["id"], "start": 0, "end": len(logs[i]["text"])}
        for i in indices
    ]


def render_context(public, spans, budget):
    """Trusted rendering; selectors cannot rewrite evidence or task metadata."""
    validate_public(public)
    if not isinstance(spans, list):
        raise TypeError("spans must be a list")
    sources = {log["id"]: log for log in public["logs"]}
    selected = set()
    for span in spans:
        if not isinstance(span, dict) or set(span) != {"log_id", "start", "end"}:
            raise ValueError("invalid source span schema")
        lid = span["log_id"]
        if lid not in sources or lid in selected:
            raise ValueError("missing or duplicate source span")
        if type(span["start"]) is not int or type(span["end"]) is not int:
            raise ValueError("source offsets must be integers")
        if span["start"] != 0 or span["end"] != len(sources[lid]["text"]):
            raise ValueError("only complete source records are supported")
        selected.add(lid)
    result = deepcopy(public)
    result["logs"] = [deepcopy(log) for log in public["logs"] if log["id"] in selected]
    if budget is not None and (
        type(budget) is not int or logs_cost(result["logs"]) > budget
    ):
        raise ValueError("selected evidence exceeds the registered character budget")
    return result
