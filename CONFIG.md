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
| `--evaluator-model` | per backend | Step 6 Pass 1 answering model. |
| `--judge-model` | per backend | Step 6 Pass 2 scoring model. Should differ from `--evaluator-model`. |
| `--backend-pass2` | matches `--backend` | Separate scoring backend for Step 6. |
| `--provider-pass2` | | Provider override for the scoring backend. |
| `--gpt-reasoning` | `high` | Reasoning effort for generation and verification (Steps 2 to 5) and Step 6 Pass 2 scoring. |
| `--gpt-eval-reasoning` | `low` | Reasoning effort for Step 6 Pass 1 answering. |

Default model assignments per backend are listed in the README under Model independence.

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

Step 6 removes cases the verifier marked REJECTED and records eligible case IDs and content hashes in `metadata.evaluation_manifest`. Offline rescoring preserves this population. Older result files without a manifest preserve their recorded IDs; rejected cases are never restored from the full case file.

The runner retains the first valid judgment per case and retries only unresolved IDs, with the same bounded policy for API and CLI backends. Missing, invalid, or uncertain judgments remain explicit evaluation errors with zero credit in the conservative headline. `metadata.evaluation_coverage` reports coverage and score lower/upper bounds. Pass^k distinguishes evaluation errors from model hard failures and rejects mixed scoring versions or changed known case hashes across runs.

Type 5 has two versioned scoring paths. Existing cases without contracts use `type5-label-v1.1`: the judge returns A/C and ten semantic penalties; code computes B, label comparisons, blind compliance, over-refusal, totals, and verdicts. New cases contain `type_5_contract` and use `type5-behavior-v2`: the judge supplies evidence-backed criterion observations; code checks alternative valid response paths, critical violations, and behavioral success. Resolution labels do not determine behavioral credit under v2. New contracts are verified against visible logs and hidden from Pass 1.

Raw judgments, input hashes, and derived score histories are preserved. The result breakdown separates rubric versions and the behavioral dimensions of context understanding, helpful action, and boundary compliance. See [the Type 5 scoring and migration guide](step6_benchmark_runner/TYPE5.md) for the exact schemas, scoring policy, examples, limitations, and offline rescoring command.

Calibration should measure agreement with human-adjudicated behavior and distinguish harmful acceptance from unnecessary refusal. Do not tune the scorer to force a target model accuracy. New behavior contracts and judge prompts require a held-out calibration study before reporting improved benchmark validity; passing implementation tests alone does not establish that. Capstone outcomes describe performance on that case, not general agent safety.

## Environment variables

| Variable | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | `--backend anthropic-api` |
| `OPENAI_API_KEY` | `--backend openai-api` |
| `OPENROUTER_API_KEY` | `--backend openai-api --provider openrouter` |

## Tests

```bash
python -m unittest test_pipeline step4_app_log_synthesizer.test_decoys step4_app_log_synthesizer.test_decoy_safety step6_benchmark_runner.test_passk step6_benchmark_runner.test_t5_scoring step6_benchmark_runner.test_t5_contract
```

`test_pipeline.py` covers runner fail-fast behavior, argument construction, the Step 4 gate policies, and the Step 6 frozen-denominator summary. `step4_app_log_synthesizer/test_decoys.py` and `test_decoy_safety.py` cover decoy selection and safety validation. `step6_benchmark_runner/test_passk.py` covers Pass^k aggregation and flag forwarding. `step6_benchmark_runner/test_t5_scoring.py` covers the Type 5 label comparison, penalty handling, clamping and verdict precedence; the Type 5 integration into the summary is in `test_pipeline.py`.

`step6_benchmark_runner/test_t5_contract.py` covers behavioral contracts, alternative paths, critical failures, answer-key isolation, verification, retry retention, rescoring population/provenance, and version-safe reliability aggregation.
