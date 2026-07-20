import json
import re
from pathlib import Path
from typing import Any


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _fix_invalid_escapes(text: str) -> str:
    valid = set('"\\/bfnrtu')
    out = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            if text[i + 1] in valid:
                out.append(text[i])
                out.append(text[i + 1])
                i += 2
            else:
                out.append(text[i + 1])
                i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)

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
    
def extract_name(seed: dict[str, Any]) -> str:
    persona_text = seed.get("persona", "") or seed.get("professional_persona", "")
    match = re.match(r"\s*([A-Z][a-z]+\s+[A-Z][a-z]+)", persona_text)
    return match.group(1) if match else seed["uuid"]

def base(name: str) -> str:
    return name.lower().replace(" ", "_")
    
def fill_seed_placeholders(template: str, seed: dict[str, Any]) -> str:
    mapping = {
        "{{participant_id}}": seed["uuid"],
        "{{name}}": extract_name(seed),
        "{{age}}": str(seed["age"]),
        "{{sex}}": seed["sex"],
        "{{marital_status}}": seed["marital_status"],
        "{{education_level}}": seed["education_level"],
        "{{occupation}}": seed["occupation"],
        "{{city}}": seed["city"],
        "{{state}}": seed["state"],
        "{{zipcode}}": seed["zipcode"],
        "{{country}}": seed["country"],
        "{{professional_persona}}": seed["professional_persona"],
        "{{sports_persona}}": seed["sports_persona"],
        "{{arts_persona}}": seed["arts_persona"],
        "{{travel_persona}}": seed["travel_persona"],
        "{{culinary_persona}}": seed["culinary_persona"],
        "{{persona}}": seed["persona"],
        "{{cultural_background}}": seed["cultural_background"],
        "{{skills_and_expertise}}": seed["skills_and_expertise"],
        "{{hobbies_and_interests}}": seed["hobbies_and_interests"],
        "{{career_goals_and_ambitions}}": seed["career_goals_and_ambitions"],
    }
    for key, value in mapping.items():
        template = template.replace(key, value)
    return template

def fill(template: str, placeholder: str, payload: Any) -> str:
    if isinstance(payload, str):
        return template.replace(placeholder, payload)
    return template.replace(
        placeholder, json.dumps(payload, indent=2, ensure_ascii=False)
    )