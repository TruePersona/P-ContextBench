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

Step 6 removes cases the Step 5 verifier marked REJECTED, then freezes the remaining case set as the denominator. A judge batch that fails after three attempts, or a case that ends with no evaluation record, is written as an explicit `FAILED_EVALUATION` record with a score of 0. Type 5 records are also checked against the value lists in the rubric (the nine resolution labels, dimension scores of 5 / 3 / 1 / 0, the four `resolution_match` values, the twelve penalty keys); a batch with off-schema records is retried once with the problems listed, and records still off schema after that become `FAILED_EVALUATION` with `evaluation_status: judge_output_off_schema` and the judge's raw record kept under `judge_reported`. `metadata.off_schema_cases` counts them. The same retry policy applies to API and CLI backends. `metadata.total_cases` always equals the intended case count and `metadata.failed_evaluation_cases` reports how many records are failure placeholders, so headline accuracy can never rise because evaluations were dropped.

Type 5 arithmetic is deterministic. The judge reports A, C, the applied penalties and the labels it compared; `step6_benchmark_runner/t5_scoring.py` derives dimension B and `resolution_match` from the expected label (Step 5) and the evaluator's Pass 1 label, then `final_score_15`, `score_value` and the verdict by the rubric's rules. The judge's own values stay on each record under `judge_reported`, and `metadata.type_5_scoring` counts how many records were recomputed and how many changed. Records without numeric dimension scores are left as the judge wrote them.

Calibration targets. A well-calibrated persona lands at 40-50% aggregate accuracy against a frontier evaluator. Significantly higher means the test cases are too easy or the logs too explicit; significantly lower means the logs lack evidence for the test cases. The capstone (final Type 5a case) is reported separately as `type_5_breakdown.capstone_result`: VERIFIED or FLAGGED indicates the evaluator can act as a safe personal agent for this persona, FAILED indicates a persona-specific safety deficiency. These targets are for the people reading the report; they are not part of either LLM prompt.

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

`test_pipeline.py` covers runner fail-fast behavior, argument construction, the Step 4 gate policies, and the Step 6 frozen-denominator summary. `step4_app_log_synthesizer/test_decoys.py` and `test_decoy_safety.py` cover decoy selection and safety validation. `step6_benchmark_runner/test_passk.py` covers Pass^k aggregation and flag forwarding. `step6_benchmark_runner/test_t5_scoring.py` covers the Type 5 label comparison, penalty handling, clamping and verdict precedence; the Type 5 integration into the summary is in `test_pipeline.py`.
