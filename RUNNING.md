# Running PersonaBench

PersonaBench is a six-step pipeline that constructs synthetic personas, embeds their traits as implicit behavioral signals in app logs, then evaluates whether an LLM can recover those traits and act safely as the persona's assistant. This document covers everything needed to reproduce the canonical results or run the pipeline from scratch.

## Prerequisites

```
Python 3.10+
pip install anthropic datasets
```

The `datasets` library is required only for Step 1 (seed lookup from HuggingFace). All other steps use only `anthropic` (or `openai` for cross-provider evaluation).

## Authentication

**API key** (pay-per-call):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."          # Unix
$env:ANTHROPIC_API_KEY = "sk-ant-..."          # PowerShell
```

**Claude subscription** (Claude Max / Pro, no API key needed):

Install the [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) and log in. The `_orchestration/` scripts route all calls through `claude -p`, billing against your subscription.

## Pipeline overview

```
Step 1  Seed lookup         NVIDIA Nemotron dataset -> seed JSON
  |
Step 2  Interview           109-question life history -> extracted profile + hidden_facts registry
  |
Step 3  Social circle       5 closest personal contacts with distinct voices
  |
Step 4  App log synthesis   Per-fact fragment generation + reverse-inferability gate + merge with filler
  |
Step 5  Test cases          Typed evaluation questions (Types 1-5) grounded in hidden_facts
  |
Step 6  Benchmark runner    Two-pass evaluation: answering (no ground truth) then scoring
```

Each step consumes the previous step's output. Steps 2-3 take minutes. Step 4 is the most expensive (300+ LLM calls per persona). Steps 5-6 take 10-20 minutes each.

## Quick start: reproduce the canonical benchmark

All 5 personas have complete data through Step 5. To re-score them against a model without regenerating anything:

```bash
# Score one persona
python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6

# Score all 5 personas
python openclaw_pipeline.py --all --start 6 --stop 6
```

This runs Step 6 only: strips existing app logs to raw text (removing all metadata, hidden facts, and internal tagging), sends the raw text with test case questions to the evaluator (Pass 1), then scores answers against ground truth with an independent judge (Pass 2).

Canonical results were produced with Opus 4.7 answering and Sonnet 4.6 judging. To match exactly:

```bash
python openclaw_pipeline.py --all --start 6 --stop 6 \
  --model claude-opus-4-7 \
  --judge-model claude-sonnet-4-6
```

## Run the full pipeline for a new persona

```bash
# Steps 2-6 for one persona (Step 1 seeds are already in the repo)
python openclaw_pipeline.py --persona julio_simmons

# Steps 2-6 for all 5 personas
python openclaw_pipeline.py --all
```

**Time estimate:** 3-5 hours per persona (dominated by Step 4's 300+ LLM calls).

## Run a single step

```bash
python openclaw_pipeline.py --persona alicia_gonzalez --start 4 --stop 4
```

Or call a step's generator directly for full control over output location:

```bash
python step4_app_log_synthesizer/generator.py \
  --profile step2_interview/data_samples/output/alicia_gonzalez_verification.json \
  --social-circle step3_social_circle/data_samples/output/alicia_gonzalez_social_circle_verification.json \
  --output alicia_condensed/ \
  --log-start 2026-03-01 --log-end 2026-03-31 \
  --model claude-opus-4-7 \
  --verifier-model claude-sonnet-4-6
```

Each step's generator accepts `--help` for its full CLI.

## Run via subscription (no API key)

The `_orchestration/` scripts use `claude -p` through your Claude subscription instead of the Anthropic SDK:

```bash
# Process a single hidden fact (generation + verification + trace recording)
python _orchestration/run_one_fact.py \
  --persona alicia_gonzalez \
  --fact-id HF-001 \
  --ground-truth-label "literal label from hidden_facts registry" \
  --contact-usage-file _orchestration/alicia_gonzalez_contact_usage.json

# Process a batch of facts (indices are 1-based)
python _orchestration/run_batch.py \
  --persona alicia_gonzalez \
  --start-idx 1 --end-idx 50 \
  --log-start 2026-03-01 --log-end 2026-03-31
```

## Model configuration

The pipeline uses three model roles. The verifier and judge must differ from the generator to maintain the architectural guarantees that make the benchmark defensible.

| Role | Default | Flag | Purpose |
|---|---|---|---|
| Generator | `claude-opus-4-7` | `--model` | Produces interviews, social circles, app log fragments, test cases, and Pass 1 answers |
| Verifier | `claude-sonnet-4-6` | `--verifier-model` | Runs the Step 4 reverse-inferability gate. Sees only the fragments and a 4-field persona sketch (name, age, occupation, location). Never sees the hidden fact. |
| Judge | `claude-sonnet-4-6` | `--judge-model` | Scores Pass 1 answers against ground truth in Step 6 Pass 2. Separate context from the answering pass. |

**Why independence matters:** If the verifier sees the hidden fact, it cannot test whether the fragments implicitly encode it. If the judge sees the questions during answering, ground-truth strings bias the evaluator. These separations are not optional.

```bash
python openclaw_pipeline.py --persona julio_simmons \
  --model claude-opus-4-7 \
  --verifier-model claude-sonnet-4-6 \
  --judge-model claude-sonnet-4-6
```

## Evaluating other models

The benchmark dataset (Steps 1-5 outputs) is provider-agnostic. Only Step 6 calls the evaluated model. The `--provider openai` flag works with any OpenAI-compatible API by setting `OPENAI_BASE_URL`.

**OpenAI GPT models:**

```bash
export OPENAI_API_KEY="sk-..."

python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6 \
  --provider openai --model gpt-4.1
```

**Local models via Ollama:**

```bash
ollama pull llama3.1:70b
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_API_KEY="ollama"

python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6 \
  --provider openai --model llama3.1:70b
```

**Google Gemini (OpenAI-compatible endpoint):**

```bash
export OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export OPENAI_API_KEY="your-gemini-api-key"

python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6 \
  --provider openai --model gemini-2.5-pro
```

**Hosted open-source models (Together, Fireworks, vLLM):**

```bash
export OPENAI_BASE_URL="https://api.together.xyz/v1"
export OPENAI_API_KEY="your-together-key"

python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6 \
  --provider openai --model meta-llama/Llama-3.1-70B-Instruct
```

Any provider that exposes an OpenAI-compatible `/v1/chat/completions` endpoint works the same way. To add a provider with a non-compatible API, extend `make_client()` and `call_llm()` in `llm.py`.

## Log window and filler ratio

These two parameters control the total context size the evaluator sees.

| Parameter | Default | Where set |
|---|---|---|
| Log window | March 1-31, 2026 (30 days) | `--log-start` / `--log-end` flags on Step 4 |
| Filler ratio | 2.5 filler messages per 1 meaningful message | `step4_app_log_synthesizer/merge_prompt.txt` |

Filler is mundane logistics noise (running late, grocery lists, pet check-ins) that the evaluator must sift through to find the implicit behavioral signals encoding hidden facts. Without filler, the benchmark degenerates into a reading comprehension test.

Changing either parameter requires regenerating Step 4 and downstream steps (5-6) for affected personas. The per-fact fragments and their verification results are unaffected by filler ratio changes; only the merge step reruns.

## Personas

| Name | Hidden facts | Notes |
|---|---|---|
| `julio_simmons` | 134 | Rochester NY, computational modeler, divorced, improv performer |
| `mary_alberti` | 104 | Madison WI, food service, Italian-American |
| `alicia_gonzalez` | 157 | Chico CA, environmental scientist, Chicana |
| `deeva_cintron` | 174 | Largest fact set, retired, most calendar events |
| `maria_buendia` | 104 | Smallest total context |

## Expected outputs

Each step writes to its own `data_samples/output/` directory.

| Step | File | Contents |
|---|---|---|
| 1 | `{name}_seed.json` | Raw demographics from NVIDIA Nemotron dataset |
| 2 | `{name}_interview.json` | 109-question transcript + draft extracted profile |
| 2 | `{name}_verification.json` | 4-direction verified profile + `hidden_facts` registry (canonical answer key for all downstream steps) |
| 3 | `{name}_social_circle.json` | 5 closest personal messaging contacts with demographics, personality, communication style |
| 3 | `{name}_social_circle_verification.json` | 2-direction verified social circle |
| 4 | `{name}_app_logs.json` | Merged messenger sessions + calendar events with filler |
| 4 | `{name}_app_logs_trace.json` | Per-fact reverse-inferability gate results (pass/fail, attempts, verifier verdict) |
| 5 | `{name}_test_cases.json` | Typed test cases (Types 1-5) with ground truth labels and evidence anchors |
| 5 | `{name}_test_cases_verification.json` | Ground-truth sourcing, deduplication, and Type 5 risk validity checks |
| 6 | `{name}_pass1_answers.json` | Evaluator answers produced without ground truth in context |
| 6 | `{name}_benchmark_results.json` | Per-case scored report with accuracy breakdown by type |

## Verifying a successful run

**Step 4:** Check the trace file. Every hidden fact should show `"passed": true`. Facts that fail the reverse-inferability gate after max attempts are still merged but flagged.

```bash
python -c "import json; t=json.load(open('step4_app_log_synthesizer/data_samples/output/julio_simmons_app_logs_trace.json')); print(f'{sum(1 for x in t if x[\"passed\"])}/{len(t)} passed')"
```

**Step 6:** Check overall accuracy and capstone result in the benchmark results file. The capstone (final Type 5a test case) should be VERIFIED or FLAGGED for a passing run.

## Troubleshooting

**`ValueError: Streaming is required for operations that may take longer than 10 minutes`** — The Anthropic SDK requires streaming for large `max_tokens` values on Opus. The pipeline uses streaming by default. If you see this error, update to the latest `llm.py`.

**`UnicodeEncodeError: 'charmap' codec can't encode character`** — Windows console encoding issue. Set `$env:PYTHONIOENCODING = "utf-8"` before running, or run from Windows Terminal (which defaults to UTF-8).

**`JSONDecodeError: Invalid \escape`** — LLMs occasionally emit invalid JSON escape sequences like `\'`. The generator sanitizes these automatically. If you hit this on an older checkout, pull the latest `generator.py`.

**Step 4 crashes mid-run** — The trace file is saved after every fact, so progress is preserved. Re-running the step will regenerate all facts from scratch (the generator does not yet resume from a partial trace). For very large runs, use the `_orchestration/run_batch.py` script which processes fact ranges independently.

**HF-007 or similar facts fail repeatedly (AMBIGUOUS after 3 attempts)** — Some facts describe abstract relational or biographical categories that are inherently difficult to encode without labels. The fragments are still merged; the trace records `"passed": false`. Step 5's test case generator can exclude these facts from test cases.

## Shell shortcuts

```bash
bash run_step.sh <step> <persona> [provider] [model]
bash run_pipeline.sh <persona> [provider] [model]
```

These are convenience wrappers around `openclaw_pipeline.py`. They pass the same model for all three roles (generator, verifier, judge). For independent verification and judging, use `openclaw_pipeline.py` directly with `--verifier-model` and `--judge-model`.
