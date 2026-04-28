"""Run Pass 2 (scoring only) for all 5 dynamic-news personas.

Reads:
  - Full test cases:  step5_testcases_synthesis/data_samples/output/{p}_test_cases.json
  - Pass 1 answers:   step6_benchmark_runner/data_samples/output_news_dynamic_v1/{p}_pass1_answers.json

Writes:
  - step6_benchmark_runner/data_samples/output_news_dynamic_v1/{p}_benchmark_results.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import anthropic

REPO_ROOT = Path(__file__).parent.parent
STEP6 = Path(__file__).parent
OUTPUT_DIR = STEP6 / "data_samples" / "output_news_dynamic_v1"
TC_DIR = REPO_ROOT / "step5_testcases_synthesis" / "data_samples" / "output"
PROMPT_PATH = STEP6 / "prompt.txt"

PERSONAS = [
    "alicia_gonzalez",
    "deeva_cintron",
    "julio_simmons",
    "maria_buendia",
    "mary_alberti",
]

MODEL_PASS2 = "claude-opus-4-7"


def load_pass2_template() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    pass2_marker = "PASS 2 — SCORING"
    header_end = text.index("PASS 1 — ANSWERING")
    pass2_start = text.index(pass2_marker)
    header = text[:header_end]
    return header + text[pass2_start:]


def fill(template: str, placeholder: str, payload: Any) -> str:
    if isinstance(payload, str):
        return template.replace(placeholder, payload)
    return template.replace(placeholder, json.dumps(payload, indent=2, ensure_ascii=False))


def extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start = payload.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM output")
    return json.loads(payload[start:])


def call_llm_streaming(client: anthropic.Anthropic, model: str, prompt: str) -> str:
    chunks: list[str] = []
    with client.messages.stream(
        model=model,
        max_tokens=64_000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    ) as stream:
        for text in stream.text_stream:
            chunks.append(text)
    return "".join(chunks)


def run_pass2_streaming(
    test_cases: dict[str, Any],
    pass1_answers: dict[str, Any],
    model: str,
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    template = load_pass2_template()
    template = fill(template, "{{INSERT_FULL_TEST_CASES_JSON_HERE}}", test_cases)
    template = fill(template, "{{INSERT_PASS_1_ANSWERS_JSON_HERE}}", pass1_answers)
    raw = call_llm_streaming(client, model, template)
    return extract_json(raw)


def main() -> None:
    client = anthropic.Anthropic()

    for persona in PERSONAS:
        tc_path = TC_DIR / f"{persona}_test_cases.json"
        p1_path = OUTPUT_DIR / f"{persona}_pass1_answers.json"
        out_path = OUTPUT_DIR / f"{persona}_benchmark_results.json"

        print(f"\n[pass 2] scoring {persona} …", flush=True)

        test_cases = json.loads(tc_path.read_text(encoding="utf-8"))
        pass1_answers = json.loads(p1_path.read_text(encoding="utf-8"))

        result = run_pass2_streaming(test_cases, pass1_answers, MODEL_PASS2, client)

        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

        accuracy = result.get("overall_accuracy", "unknown")
        print(f"[done]  {persona} → overall_accuracy={accuracy}", flush=True)


if __name__ == "__main__":
    main()
