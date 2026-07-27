# Configuration Reference

All flags below belong to `run.py`, the single pipeline entry point. Each step generator accepts the same model and backend flags when run standalone; `run.py` forwards them.

## Persona selection

| Flag | Default | Meaning |
|---|---|---|
| `--persona NAME` | | Shorthand for `step1_seed/data_samples/NAME_seed.json`. |
| `--seed PATH` | | Explicit seed JSON path. |
| `--uuid UUID` | | Nemotron-Personas-USA record id. Required for Step 1. |
| `--all` | | Run every seed in `step1_seed/data_samples/`. |

## Pipeline range

| Flag | Default | Meaning |
|---|---|---|
| `--start N` | 1 | First step to run (1 to 6). |
| `--stop N` | 6 | Last step to run (1 to 6). |

A stage that exits nonzero stops the pipeline for that persona. With `--all`, remaining personas still run and the process exits nonzero, listing every failed persona.

## Backends and models

| Flag | Default | Meaning |
|---|---|---|
| `--backend` | `anthropic-api` | `claude` and `codex` use the logged-in subscription CLIs; `anthropic-api` and `openai-api` use metered API keys. |
| `--provider` | | API provider when the backend is API based; `openrouter` routes the OpenAI SDK through OpenRouter. |
| `--model` | per backend | Generator model. Exact pinned string, never an alias. |
| `--verifier-model` | per backend | Verifier model for construction gates. Should differ from `--model`. |
| `--answer-model` | per backend | Step 6 Pass 1 answering model. |
| `--judge-model` | per backend | Step 6 Pass 2 scoring model. Should differ from `--answer-model`. |
| `--backend-pass2` | matches `--backend` | Separate scoring backend for Step 6. |
| `--provider-pass2` | | Provider override for the scoring backend. |
| `--gpt-reasoning` | `high` | Reasoning effort for generation and verification (Steps 2 to 5) and Step 6 Pass 2 scoring. |
| `--gpt-eval-reasoning` | `low` | Reasoning effort for Step 6 Pass 1 answering. |

**Default model assignments:**

| Role | Claude | GPT |
|---|---|---|
| Generator | `claude-opus-4-7` | `gpt-5.5` |
| Verifier | `claude-sonnet-4-6` | `gpt-5.4` |
| Answer | `claude-haiku-4-5` | `gpt-5.4-mini` |
| Judge | `claude-sonnet-4-6` | `gpt-5.4` |

**OpenAI backend (openai-api, codex) reasoning defaults:**

- Generation steps (Steps 2-5, Step 6 Pass 2) use `high` reasoning effort.
- Evaluated responses (Step 6 Pass 1) use `low` reasoning effort.

## Step 4 app log synthesis

| Flag | Default | Meaning |
|---|---|---|
| `--log-start` | `2026-03-01` | First app log date. |
| `--log-end` | `2026-03-31` | Last app log date. |
| `--per-cluster-max-attempts` | 3 | Generation attempts per hidden-fact cluster. |
| `--max-facts` | 100 | Maximum hidden facts selected. |
| `--filler-ratio` | 2.5 | Filler-to-meaningful token ratio. |
| `--gate-policy` | `strict` | Cluster acceptance policy. `strict` requires a RECOVERED verdict with no leak-flagged fragments, which is the predicate the verifier prompt documents. `lenient` also accepts AMBIGUOUS verdicts whose candidates are all HIGH confidence when leak flags are present; it reproduces the rule the committed data samples were built with and must be selected explicitly. |
| `--target-context-tokens` | | Optional total context token target. |
| `--resume` | | Reuse existing trace and verified fragments when compatible. |
| `--retry-failed` | | With `--resume`, retry only failed clusters. |
| `--verified-decoys PATH` | | Verified decoy pool JSON. |
| `--decoy-count` | 0 | Verified messenger decoys to place. |
| `--decoy-pool-size` | 40 | Decoy candidates to generate when no pool is supplied. |

## Step 6 benchmark

| Flag | Default | Meaning |
|---|---|---|
| `--passk-runs N` | 1 | Repeat Step 6 N times and write a Pass^k summary. |
| `--passk-output PATH` | | Output path for the Pass^k summary JSON. |
| `--passk-allow-missing` | | Score cases missing from a run as 0 instead of failing. |
| `--skip-pass1` | | Reuse an existing `{persona}_pass1_answers.json`. |
| `--skip-pass2` | | Stop after Pass 1 answering. |

Step 6 removes cases the Step 5 verifier marked REJECTED, then freezes the remaining case set as the denominator. A judge batch that fails after three attempts, or a case that ends with no evaluation record, is written as an explicit `FAILED_EVALUATION` record with a score of 0. `metadata.total_cases` always equals the intended case count and `metadata.failed_evaluation_cases` reports how many records are failure placeholders, so headline accuracy can never rise because evaluations were dropped.

## Environment variables

| Variable | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | `--backend anthropic-api` |
| `OPENAI_API_KEY` | `--backend openai-api` |
| `OPENROUTER_API_KEY` | `--backend openai-api --provider openrouter` |

## Tests

```bash
python -m pytest test_pipeline.py step4_app_log_synthesizer step6_benchmark_runner -q
```

`test_pipeline.py` covers runner fail-fast behavior, argument construction, the Step 4 gate policies, and the Step 6 frozen-denominator summary. `step4_app_log_synthesizer/test_decoys.py` and `test_decoy_safety.py` cover decoy selection and safety validation. `step6_benchmark_runner/test_passk.py` covers Pass^k aggregation and flag forwarding.
