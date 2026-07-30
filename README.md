# P-ContextBench: From Personal Fact Recall to Personalized Agent Behavior

We introduce P-ContextBench, a realistic, verifiable, and scalable benchmark framework for evaluating personal-context understanding.

To evaluate LLMs’ personal intelligence in an everyday
setting, P-ContextBench includes five task types:

1. Single-source fact recovery
2. Multi-source fact recovery
3. Temporal state tracking
4. Higher-level personal-pattern inference
5. Constraint-aware agent behavior

P-ContextBench provides measurable targets for improving
the accuracy, reliability, and safety of LLM-based personal
agents.

## Pipeline

Each persona is constructed through a six-step pipeline. Every LLM-based generation step (2-5) has its own verification process to ensure consistency and quality in generated samples. These steps utilize two separate models for generation (`--model`) and verification (`--verifier-model`).
Shared model and backend dispatch helpers live in [`llm.py`](llm.py); shared seed parsing helpers live in [`utils.py`](utils.py).

| Step | What it does |
|---|---|
| [step1_seed](step1_seed) | Pull baseline demographics from the NVIDIA Nemotron-Personas-USA dataset. |
| [step2_interview](step2_interview) | Generate a 109-question life-history interview and a structured profile with a `hidden_facts` registry. |
| [step3_social_circle](step3_social_circle) | Synthesize the people with whom the persona most frequently exchanges personal text messages. |
| [step4_app_log_synthesizer](step4_app_log_synthesizer) | Generate mobile app activity logs (messenger + calendar) that implicitly encode each hidden fact through behavioral signals distributed across multiple sources. |
| [step5_testcases_synthesis](step5_testcases_synthesis) | Construct typed test cases (five types, including agent-behavior scenarios) grounded in the hidden_facts registry. |
| [step6_benchmark_runner](step6_benchmark_runner) | Execute the benchmark against a frontier LLM using a two-pass design that prevents ground-truth leakage; includes Pass^k aggregation for repeated-run reliability. Pass 1 responds to test cases using `--answer-model`. Pass 2 scores the model's answers using `--judge-model`. |

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
- `step5_testcases_synthesis/data_samples/{persona}_test_cases.json`
- `step5_testcases_synthesis/data_samples/{persona}_test_cases_verification.json`

Step 6 writes `{persona}_pass1_answers.json`, `{persona}_benchmark_results.json`, and `{persona}_app_logs_raw.txt` into its output directory at benchmark time. Additionally, using `--passk-runs` returns `{persona}_passk_summary.json`, providing in-depth scoring metrics. 

Seeded personas are automatically listed in [`step1_seed/selected_personas.json`](step1_seed/selected_personas.json) by name and UUID. This file is used during batch generation (e.g. when calling `--all`; refer to examples under **[Run](#run)**). Due to size limitations, sample data includes 30 personas. The complete 100 persona list is provided at [`step1_seed/original_selected_personas.json`](step1_seed/original_selected_personas.json) for reference.

**Provided samples use GPT-5.5 for generation (`--model`) and GPT-5.4 for verification/scoring (`--verifier-model`, `judge-model`).**

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
# Standard benchmark (used in provided data samples)
python run.py --all \
  --start 6 --stop 6 \
  --backend codex \
  --answer-model <ANSWER_MODEL> \
  --judge-model gpt-5.4 \
  --passk-runs 3
```

#### Basic examples:

```bash
# Benchmark GPT-5.4 mini with GPT-5.4 as judge (Codex subscription)
python run.py --persona carlos_mercedes \
  --start 6 --stop 6 \
  --backend codex \
  --answer-model gpt-5.4-mini \
  --judge-model gpt-5.4

# Evaluate through all personas at once
python run.py --all \
  --start 6 --stop 6 \
  --backend codex \
  --answer-model gpt-5.4-mini \
  --judge-model gpt-5.4
```

*To repeat Step 6 for reliability, add `--passk-runs`:*

```bash
python run.py --persona carlos_mercedes \
  --start 6 --stop 6 \
  --backend codex \
  --answer-model gpt-5.4-mini \
  --judge-model gpt-5.4 \
  --passk-runs 3
```

#### Using separate answering/scoring backends:

```bash
python run.py --persona carlos_mercedes \
  --start 6 --stop 6 \
  --backend anthropic-api \
  --answer-model claude-haiku-4-5 \
  --backend-pass2 codex \
  --judge-model gpt-5.4

# Using OpenRouter
python run.py --persona carlos_mercedes \
  --start 6 --stop 6 \
  --backend openai-api \
  --provider openrouter \
  --answer-model google/gemini-3-flash-preview \
  --backend-pass2 codex \
  --judge-model gpt-5.4
```

### Run the entire pipeline end-to-end

```bash
python run.py \
  --uuid 50f90a6f17de473f9ca15f00afdedf7a \
  --start 1 --stop 6 \
  --backend claude \
  --answer-model claude-haiku-4-5
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

### Seed a new population
```bash
# Using defaults (--random-count 30, no filters)
python run.py --start 1 --stop 1

# Filter specific demographics
python run.py \
  --start 1 --stop 1 \
  --random-count 40 \
  --min-age 40 \
  --max-age 60 \
  --sex Male \
  --marital-status married_present \
  --education-level high_school some_college bachelors
```

For the full flag reference, defaults, and failure semantics, see [CONFIG.md](CONFIG.md).

### Tests

```bash
python -m pytest test_pipeline.py step4_app_log_synthesizer step6_benchmark_runner -q
```

[`test_pipeline.py`](test_pipeline.py) covers the runner and stage gates; the step-level suites cover decoy safety and Pass^k aggregation.

## References

- Park et al. 2024 — *Generative Agent Simulations of 1,000 People.* [[paper]](https://arxiv.org/abs/2411.10109) — 109 interview questions and verification approach.
- Ge et al. 2024 — *PersonaHub (Tencent AI Lab).* [[paper]](https://arxiv.org/abs/2406.20094) — Persona-to-Persona method for generating social circles.
- Jiang et al. 2025 — *PersonaMem-v2.* [[paper]](https://arxiv.org/abs/2502.15910) — Design principles: implicit preferences, broad domains, compact summaries.
- NVIDIA Nemotron-Personas-USA. [[dataset]](https://huggingface.co/datasets/nvidia/Nemotron-Personas-USA) — Starter people (seed data).
