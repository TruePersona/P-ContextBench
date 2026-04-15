# Contributing to PersonaBench

## Getting Started

1. Clone the repository.
2. Review the top-level `README.md` for the pipeline overview.
3. Each step folder (`PersonaEngine/step*`) contains its own `README.md` with step-specific documentation, prompts, and a generator script.

## Repository Layout

Every step folder follows the same structure:

- `prompt.txt` — generation prompt for the step
- `verification_prompt.txt` — verification prompt for the step (where applicable)
- `generator.py` — orchestration script that runs generation, verification, and iterative refinement
- `README.md` — step documentation
- `data_samples/input/` — sample input data (when the step requires input beyond the previous step's output)
- `data_samples/output/` — sample output data

## Prompt Conventions

- Prompts are model-agnostic. Do not reference specific model names or providers inside prompt bodies.
- Prompts do not reference step numbers or pipeline positions. When another step's output is needed, refer to it by path (e.g., `step2_interview/data_samples/output/`).
- Every generation prompt has a matching verification prompt that runs at the end of the step and produces a corrected canonical output.
- Schema fields use `verdict` (consistent | inconsistent) and `gap` (true | false) as independent concepts. Resolution fields are populated only when an action is taken.

## Adding a New Step

1. Create a new folder under `PersonaEngine/` following the naming pattern `stepN_<name>`.
2. Add `prompt.txt`, `verification_prompt.txt` (if verification applies), `generator.py`, and `README.md`.
3. Add `data_samples/input/` and `data_samples/output/`.
4. Update the top-level `README.md` pipeline table to reference the new step.
5. Update `Top_level_generator.py` to orchestrate the new step into the pipeline.

## Regenerating Personas

Run the pipeline end-to-end for a single persona:

```bash
python Top_level_generator.py --participant_id <id>
```

Run a single step for an existing persona:

```bash
python PersonaEngine/step2_interview/generator.py \
  --seed PersonaEngine/step1_seed/data_samples/output/{name}_seed.json \
  --output PersonaEngine/step2_interview/data_samples/output/
```

## Contributions

Open a pull request with a clear description of the change. For prompt modifications, include a before-and-after example of the prompt's output to demonstrate the effect.

## License

Contributions are accepted under the Apache 2.0 license (see `LICENSE`).
