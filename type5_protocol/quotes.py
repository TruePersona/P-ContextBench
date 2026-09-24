"""Bind citations to actual text without treating quote typography as paraphrase."""

PUNCTUATION = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
)


def match_quote(text, quote):
    if not isinstance(text, str) or not isinstance(quote, str) or not quote:
        return None
    index = text.find(quote)
    if index >= 0:
        return {
            "start": index,
            "end": index + len(quote),
            "text": quote,
            "match": "exact",
        }
    normalized = text.translate(PUNCTUATION)
    needle = quote.translate(PUNCTUATION)
    positions = []
    start = 0
    while True:
        index = normalized.find(needle, start)
        if index < 0:
            break
        positions.append(index)
        start = index + 1
    if not positions:
        return None
    # Ambiguous typography variants must not choose a source silently.
    spans = {text[i : i + len(quote)] for i in positions}
    if len(spans) != 1:
        return None
    index = positions[0]
    return {
        "start": index,
        "end": index + len(quote),
        "text": text[index : index + len(quote)],
        "match": "quote_typography_only",
    }


def judgment_quote_matches(answer, judgment):
    return [
        {"observation_id": o["id"], "supplied_quote": q, **match_quote(answer, q)}
        for o in judgment["observations"]
        for q in o["quotes"]
    ]
