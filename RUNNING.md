# Running PersonaBench

PersonaBench measures whether an LLM can infer a persona's identity from raw app logs and act safely as their personal assistant. This document covers two use cases: scoring a model against the existing dataset, and generating a new persona end-to-end.

## Prerequisites

```
Python 3.10+
pip install anthropic openai datasets
```

## Authentication

**Subscription CLI** (no API key needed): install and log in to the Claude Code CLI (`claude -p`) or the Codex CLI (`codex exec`). Select with `--backend claude` or `--backend codex`.

**API key** (metered): set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in your environment. Select with `--backend anthropic-api` or `--backend openai-api`.

## Preflight

Verify CLI tools are installed and callable before starting a long run:

```bash
python openclaw_pipeline.py --help
python step1_seed/generator.py --help
codex exec --help              # if using Codex backend
claude --help                  # if using Claude backend
```

Smoke-test authentication with a single cheap call before committing to a full run:

```bash
# Codex backend
echo "Reply with the word ok." | codex exec --ephemeral -

# Claude backend
echo "Reply with the word ok." | claude -p --tools ""

# Anthropic API
python -c "import anthropic; print(anthropic.Anthropic().messages.create(model='claude-sonnet-4-6', max_tokens=5, messages=[{'role':'user','content':'ok?'}]).content[0].text)"

# OpenAI API
python -c "from openai import OpenAI; print(OpenAI().chat.completions.create(model='gpt-4.1-nano', max_tokens=5, messages=[{'role':'user','content':'ok?'}]).choices[0].message.content)"
```

If the smoke test fails, fix authentication before proceeding. A broken credential discovered after setup or during a long run wastes time and can leave partial outputs.

## Score a model against the existing dataset

All 5 personas have complete data through Step 5. To benchmark a model, run Step 6 only. Step 6 has two passes with separate model roles:

- **Pass 1 (evaluator)**: the model being benchmarked. Sees only raw app logs and questions.
- **Pass 2 (judge)**: scores Pass 1 answers against ground truth. Must be a different model.

```bash
# Benchmark GPT 5 with GPT 5.4 as judge (Codex subscription)
python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6 \
  --backend codex \
  --model gpt-5 \
  --judge-model gpt-5.4

# Benchmark Opus 4.7 with Sonnet 4.6 as judge (Claude subscription)
python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6 \
  --backend claude \
  --model claude-opus-4-7 \
  --judge-model claude-sonnet-4-6

# Score all 5 personas at once
python openclaw_pipeline.py --all --start 6 --stop 6 \
  --backend codex \
  --model gpt-5 \
  --judge-model gpt-5.4
```

When running Step 6 directly (with `--start 6 --stop 6`), `--model` controls the evaluator only. This is different from the full pipeline, where `--model` controls the generator for Steps 2-5.

## Generate a new persona end-to-end

**Step 1: fetch a seed.** Browse the NVIDIA Nemotron-Personas-USA dataset to choose a persona UUID:

```python
from datasets import load_dataset
ds = load_dataset("nvidia/Nemotron-Personas-USA", split="train")
print(f"{len(ds)} personas available")
for row in ds.select(range(5)):
    print(f"  {row['uuid']}  {row['persona'][:80]}")
```

Fetch the seed. The generator prints the output path -- use it for the next command:

```bash
python step1_seed/generator.py \
  --uuid 50f90a6f17de473f9ca15f00afdedf7a \
  --output step1_seed/data_samples/output/
# Prints: "Wrote seed: step1_seed/data_samples/output/alicia_gonzalez_seed.json"
```

The UUID above is Alicia Gonzalez, one of the five validated demo personas. Any Nemotron UUID works; demo UUIDs are listed in the Personas table below.

**Steps 2-5: generate the dataset.** This produces the interview, social circle, app logs, and test cases:

```bash
python openclaw_pipeline.py \
  --seed step1_seed/data_samples/output/alicia_gonzalez_seed.json \
  --start 2 --stop 5 \
  --backend codex \
  --model gpt-5.5 \
  --verifier-model gpt-5
```

**Step 6: benchmark.** Run separately so you can use a different evaluator model:

```bash
python openclaw_pipeline.py \
  --persona alicia_gonzalez --start 6 --stop 6 \
  --backend codex \
  --model gpt-5 \
  --judge-model gpt-5.4
```

**Time estimate:** 3-5 hours per persona (dominated by Step 4's 300+ LLM calls for per-fact fragment generation and verification).

For an existing repo persona whose seed is already committed, the same two-stage pattern applies:

```bash
# Generate Steps 2-5
python openclaw_pipeline.py --persona julio_simmons --start 2 --stop 5 \
  --backend codex --model gpt-5.5 --verifier-model gpt-5

# Benchmark Step 6
python openclaw_pipeline.py --persona julio_simmons --start 6 --stop 6 \
  --backend codex --model gpt-5 --judge-model gpt-5.4
```

## Run a single step

```bash
python openclaw_pipeline.py --persona alicia_gonzalez --start 4 --stop 4 --backend claude
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

## Model independence

The pipeline uses four model roles. Three independence boundaries prevent systematic bias:

| Boundary | Requirement | Why |
|---|---|---|
| Generator differs from Verifier | The model that creates app log fragments must not verify its own output. | A model pattern-matching its own generation is not an independent recoverability test. |
| Evaluator differs from Judge | The model being benchmarked must not grade its own answers. | Same-model self-grading inflates scores by ~27% (empirically measured). |
| Generator differs from Judge | The model that created the test cases must not grade answers to them. | Shared systematic biases in question construction and answer evaluation. |

**Default model assignments:**

| Role | Claude | GPT | Flag |
|---|---|---|---|
| Generator | `claude-opus-4-7` | `gpt-5.5` | `--model` (Steps 2-5) |
| Verifier | `claude-sonnet-4-6` | `gpt-5` | `--verifier-model` |
| Evaluator | (run Step 6 separately) | `gpt-5` | `--model` (Step 6 only) |
| Judge | `claude-sonnet-4-6` | `gpt-5.4` | `--judge-model` |

The evaluator is intentionally run in a separate `--start 6 --stop 6` invocation so it can use a different model from the generator. When running the full pipeline in one command (`--start 2 --stop 6`), `--model` is used for both generation and evaluation, which violates the Generator-differs-from-Evaluator boundary. Always run Step 6 separately to maintain evaluator independence.

Codex CLI mode uses the locally authenticated Codex CLI session rather than the OpenAI Python SDK or `OPENAI_API_KEY`. Account limits and billing depend on the user's subscription.

## Log window and filler ratio

| Parameter | Default | Where set |
|---|---|---|
| Log window | March 1-31, 2026 (30 days) | `--log-start` / `--log-end` flags on Step 4 |
| Filler ratio | 2.5 filler messages per 1 meaningful message | `step4_app_log_synthesizer/merge_prompt.txt` |

Filler is mundane logistics noise that the evaluator must sift through to find implicit behavioral signals. Without filler, the benchmark degenerates into a reading comprehension test. Changing either parameter requires regenerating Step 4 and downstream steps (5-6).

## Personas

| Name | UUID | Hidden facts |
|---|---|---:|
| `julio_simmons` | `e7035edf5bc744c9912694a7d4b2a99c` | 134 |
| `mary_alberti` | `e7c0574639a244c8972c92aab9501035` | 104 |
| `alicia_gonzalez` | `50f90a6f17de473f9ca15f00afdedf7a` | 157 |
| `deeva_cintron` | `f2f5dbaf4d3d43f68adeb7f318afa3a2` | 174 |
| `maria_buendia` | `5237e90a0ca3460dbbcba20adb61922f` | 104 |

## Expected outputs

Each step writes to its own `data_samples/output/` directory.

| Step | File | Contents |
|---|---|---|
| 1 | `{name}_seed.json` | Raw demographics from NVIDIA Nemotron dataset |
| 2 | `{name}_interview.json` | 109-question transcript + draft extracted profile |
| 2 | `{name}_verification.json` | 4-direction verified profile + `hidden_facts` registry (canonical ground truth for all downstream steps) |
| 3 | `{name}_social_circle.json` | 5 closest personal messaging contacts |
| 3 | `{name}_social_circle_verification.json` | 2-direction verified social circle |
| 4 | `{name}_app_logs.json` | Merged messenger sessions + calendar events with filler |
| 4 | `{name}_app_logs_trace.json` | Per-fact reverse-inferability gate results |
| 5 | `{name}_test_cases.json` | Typed test cases (Types 1-5) with ground truth |
| 5 | `{name}_test_cases_verification.json` | Ground-truth sourcing and deduplication checks |
| 6 | `{name}_pass1_answers.json` | Evaluator answers (ground truth not in context) |
| 6 | `{name}_benchmark_results.json` | Scored report with per-type accuracy breakdown |

## Verifying a successful run

**Step 4:** Check the trace file. Every hidden fact should show `"passed": true`.

```bash
python -c "import json; t=json.load(open('step4_app_log_synthesizer/data_samples/output/julio_simmons_app_logs_trace.json')); print(f'{sum(1 for x in t if x[\"passed\"])}/{len(t)} passed')"
```

**Step 6:** Check overall accuracy and capstone result. The capstone (final Type 5a test case) should be VERIFIED or FLAGGED.

## Troubleshooting

**`ValueError: Streaming is required`** -- The Anthropic SDK requires streaming for large `max_tokens` on Opus. The pipeline uses streaming by default. Update to the latest `llm.py` if you see this.

**`UnicodeEncodeError: 'charmap'`** -- Windows console encoding. Set `$env:PYTHONIOENCODING = "utf-8"` before running, or use Windows Terminal.

**`JSONDecodeError: Invalid \escape`** -- LLMs occasionally emit `\'` or similar. The generator sanitizes these automatically.

**Step 4 crashes mid-run** -- Trace and fragment files are saved after every fact so progress is auditable. Re-running the step regenerates all facts from scratch.

**AMBIGUOUS after 3 attempts** -- Abstract relational facts are hard to encode without labels. Fragments are merged anyway; the trace records `"passed": false`.

## Shell shortcuts

```bash
bash run_step.sh <step> <persona> [backend] [model]
bash run_pipeline.sh <persona> [backend] [model]
```

Convenience wrappers around `openclaw_pipeline.py`. For independent verifier and judge model selection, use `openclaw_pipeline.py` directly. On Windows without Git Bash or WSL, use `python openclaw_pipeline.py` directly.
