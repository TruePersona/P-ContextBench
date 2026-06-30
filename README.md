# PersonaBench

A benchmark for evaluating personalized AI behavior and user understanding.

## Goal

PersonaBench measures whether an LLM can:

1. **Infer** a persona's identity, preferences, and life patterns from raw app logs alone.
2. **Act** as a useful, safe personal agent for that persona given those inferred traits.

Rather than testing generic task completion, PersonaBench probes deep user context — the kind of behavioral, relational, and safety-relevant signals that a personal assistant would need to serve a user well. A SOTA baseline is evaluated against the benchmark to expose current model limitations.

## Pipeline

Each persona is constructed through a six-step pipeline. Every step has its own generator, verifier, and README.
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
`data_samples/output/` directory. The file naming convention is:

- `step1_seed/data_samples/output/{persona}_seed.json`
- `step2_interview/data_samples/output/{persona}_interview.json`
- `step2_interview/data_samples/output/{persona}_verification.json`
- `step3_social_circle/data_samples/output/{persona}_social_circle.json`
- `step3_social_circle/data_samples/output/{persona}_social_circle_verification.json`
- `step4_app_log_synthesizer/data_samples/output/{persona}_app_logs.json`
- `step4_app_log_synthesizer/data_samples/output/{persona}_app_logs_trace.json`
- `step4_app_log_synthesizer/data_samples/output/{persona}_verified_fragments.json`

This output batch adds 40 new personas through Step 4:

`alicia_mosquera`, `alina_acosta`, `andrew_black`,
`angel_diaz`, `antonio_gonzalez`, `baljinder_simmons`,
`brian_martin`, `carolyn_amos`, `catherine_denis`, `chol_tran`,
`christopher_montero`, `david_mckethan`, `debra_reeves`,
`donovan_munoz`, `ellias_chand`, `hanh_gunasekara`,
`irene_tangarife`, `iris_trujillo`, `james_lee`,
`jennifer_cuzzort`, `jose_bonnet`, `joseph_giordano`,
`judith_castillo`, `kailea_rubel`, `katherine_holder`,
`keith_moore`, `kerri_wilson`, `lashonda_brazzell`,
`laura_bost`, `miguel_perezramos`, `mikala_langley`,
`pedro_jimenez`, `raki_roseberry`, `saba_guevara`,
`sandi_chapman`, `sarada_mongru`, `sean_buckley`, `shoba_mehta`,
`terri_maxson`, and `tyler_brizendine`.

## Scope

This batch is scoped to 40 new personas through Step 4 app logs. Step 5 test
cases and Step 6 benchmark runs are generated and reviewed separately.

## Getting started

See [RUNNING.md](RUNNING.md) for three supported execution backends:

- **Direct API** — `python Top_level_generator.py` with an Anthropic API key
- **Vendor CLI** — `python openclaw_pipeline.py` running against a CLI subscription
- **AI coding agent with subagents** — orchestrate inside Claude Code, CodenX, Antigravity, Cursor Agents, or any agent that exposes a Task / subagent tool

All three produce equivalent outputs given the same seed and model.

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
