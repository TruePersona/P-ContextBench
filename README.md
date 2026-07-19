# P-ContextBench: A Benchmark for Evaluating Personalized AI Behavior and User Understanding

P-ContextBench measures whether an LLM can:

1. **Infer** a persona's identity, preferences, and life patterns from raw app logs alone.
2. **Act** as a useful, safe personal agent for that persona given those inferred traits.

Rather than testing generic task completion, P-ContextBench probes deep user context — the kind of behavioral, relational, and safety-relevant signals that a personal assistant would need to serve a user well. A SOTA baseline is evaluated against the benchmark to expose current model limitations.

## Pipeline

Each persona is constructed through a six-step pipeline. Every step has its own generator and verifier.
Shared model and backend dispatch helpers live in [`llm.py`](llm.py).

| Step | What it does |
|---|---|
| [step1_seed](step1_seed) | Pull baseline demographics from the NVIDIA Nemotron-Personas-USA dataset. |
| [step2_interview](step2_interview) | Generate a 109-question life-history interview and a structured profile with a `hidden_facts` registry (60-150 atomic facts per persona). |
| [step3_social_circle](step3_social_circle) | Synthesize the five people with whom the persona most frequently exchanges personal text messages. |
| [step4_app_log_synthesizer](step4_app_log_synthesizer) | Generate mobile app activity logs (messenger + calendar) that implicitly encode each hidden fact through behavioral signals distributed across multiple sources. |
| [step5_testcases_synthesis](step5_testcases_synthesis) | Construct typed test cases (five types, including agent-behavior scenarios) grounded in the hidden_facts registry. |
| [step6_benchmark_runner](step6_benchmark_runner) | Execute the benchmark against a frontier LLM using a two-pass design that prevents ground-truth leakage; includes Pass^k aggregation for repeated-run reliability. |

## Generated Samples

Generated persona artifacts are tracked under each step's
`data_samples/` directory. The file naming convention is:

- `step1_seed/data_samples/{persona}_seed.json`
- `step2_interview/data_samples/{persona}_interview.json`
- `step2_interview/data_samples/{persona}_verification.json`
- `step3_social_circle/data_samples/{persona}_social_circle.json`
- `step3_social_circle/data_samples/{persona}_social_circle_verification.json`
- `step4_app_log_synthesizer/data_samples/{persona}_app_logs.json`
- `step4_app_log_synthesizer/data_samples/{persona}_app_logs_trace.json`
- `step4_app_log_synthesizer/data_samples/{persona}_verified_fragments.json`

## Getting started

### Prerequisites

```
Python 3.10+
pip install anthropic openai datasets
```

### Authentication

**Subscription CLI** (no API key needed): install and log in to the Claude Code CLI (`claude -p`) or the Codex CLI (`codex exec`). Select with `--backend claude` or `--backend codex`.

**API key** (metered): set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in your environment. Select with `--backend anthropic-api` or `--backend openai-api`.

**OpenRouter** (metered, OpenAI-compatible): set `OPENROUTER_API_KEY` and pass `--backend openai-api --provider openrouter`. Requests route through the OpenAI SDK against the OpenRouter endpoint and currently target reasoning-capable models.

Verify your backend works before starting a long run: `python run.py --help`.

## Run

### Score a model against the existing dataset

```bash
# Benchmark GPT-5.4 mini with GPT-5.4 as judge (Codex subscription)
python run.py --persona julio_simmons \
  --start 6 --stop 6 \
  --backend codex \
  --evaluator-model gpt-5.4-mini \
  --judge-model gpt-5.4

# Evaluate through all personas at once
python run.py --all \
  --start 6 --stop 6 \
  --backend codex \
  --evaluator-model gpt-5.4-mini \
  --judge-model gpt-5.4
```

*To repeat Step 6 for reliability, add `--passk-runs`:*

```bash
python run.py --persona julio_simmons \
  --start 6 --stop 6 \
  --backend codex \
  --evaluator-model gpt-5.4-mini \
  --judge-model gpt-5.4 \
  --passk-runs 3
```

#### Using separate answering/scoring backends:

```bash
python run.py --persona julio_simmons \
  --start 6 --stop 6 \
  --backend anthropic-api \
  --evaluator-model claude-haiku-4-5 \
  --backend-pass2 codex \
  --judge-model gpt-5.4

# Using OpenRouter:
python run.py --persona julio_simmons \
  --start 6 --stop 6 \
  --backend openai-api \
  --provider openrouter \
  --evaluator-model google/gemini-3-flash-preview \
  --backend-pass2 ... \
  --judge-model ...
```

### Run the entire pipeline end-to-end

```bash
python run.py \
  --uuid 50f90a6f17de473f9ca15f00afdedf7a \
  --start 1 --stop 6 \
  --backend claude \
  --evaluator-model claude-haiku-4-5
```

#### Generate data for a seeded persona:

```bash
python run.py \
  --persona alicia_gonzalez \
  --start 2 --stop 5 \
  --backend codex \
  --model gpt-5.5 \
  --verifier-model gpt-5.4
```


For further detail, refer to [CONFIG.md](CONFIG.md)

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
| Generator | `claude-opus-4-7` | `gpt-5.5` | `--model` |
| Verifier | `claude-sonnet-4-6` | `gpt-5.4` | `--verifier-model` |
| Evaluator | `claude-haiku-4-5` | `gpt-5.4-mini` | `--evaluator-model` |
| Judge | `claude-sonnet-4-6` | `gpt-5.4` | `--judge-model` |

**OpenAI backend (openai-api, codex) reasoning defaults:**

- Generation steps (Steps 2-5, Step 6 Pass 2) use `high` reasoning effort.
- Evaluated responses (Step 6 Pass 1) use `low` reasoning effort.

## References

- Park et al. 2024 — *Generative Agent Simulations of 1,000 People.* [[paper]](https://arxiv.org/abs/2411.10109) — 109 interview questions and verification approach.
- Ge et al. 2024 — *PersonaHub (Tencent AI Lab).* [[paper]](https://arxiv.org/abs/2406.20094) — Persona-to-Persona method for generating social circles.
- Jiang et al. 2025 — *PersonaMem-v2.* [[paper]](https://arxiv.org/abs/2502.15910) — Design principles: implicit preferences, broad domains, compact summaries.
- Jimenez et al. 2024 — *SWE-bench Verified.* [[paper]](https://openai.com/index/introducing-swe-bench-verified/) — Human-in-the-loop test case verification methodology.
- NVIDIA Nemotron-Personas-USA. [[dataset]](https://huggingface.co/datasets/nvidia/Nemotron-Personas-USA) — Starter people (seed data).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All commits must include a DCO sign-off.

## License

[Apache 2.0](LICENSE).
