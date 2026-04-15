# Step 2 — Interview and Extracted Profile

## Purpose

Produce a full qualitative life-history interview and a structured extracted profile for a synthetic persona. The interview uses the 109-question American Voices Project protocol (Park et al., 2024). The extracted profile is a structured summary of everything important from the interview, organized so downstream steps can consume it.

## Process

Step 2 is a two-phase pipeline run inside a single step folder:

1. **Generation** — `prompt.txt` takes the seed data and produces the interview transcript plus the draft extracted profile (preferences across 18 subcategories plus four free-text expert summaries).

2. **Verification** — `verification_prompt.txt` takes the seed, transcript, and draft profile and runs a four-direction consistency check (seed vs. interview, interview vs. profile, profile internal consistency, completeness). It corrects gaps and inconsistencies, preserves the expert summaries verbatim, and generates the deduplicated `hidden_facts` registry.

The `generator.py` script orchestrates both phases and regenerates via an iterative refinement loop if verification fails.

## Inputs

- Seed JSON (from `../step1_seed/data_samples/output/`)
- Optional: additional inputs in `data_samples/input/`

## Outputs

- `data_samples/output/{name}_interview.json` — interview transcript and draft extracted profile
- `data_samples/output/{name}_verification.json` — verification report, corrected extracted profile, and hidden_facts registry

## Extracted profile structure

```
{
  "preferences": { 18 subcategories with summary, details, and Q## evidence },
  "summaries":   { demographer, behavioral_economist, political_scientist, psychologist — free-text }
}
```

After verification, the corrected profile is accompanied by a `hidden_facts` registry of 60-100 atomic facts enumerated and deduplicated from the corrected preferences.

## The 18 preference subcategories

health_and_wellness, food_and_dining, travel, social_and_relationships, home_and_lifestyle, entertainment, hobbies_and_recreation, work_and_career, arts_and_culture, sports_and_fitness, nature_and_outdoors, technology, community_and_civic, music, fashion_and_appearance, cultural_and_linguistic, life_events_and_transitions, media_and_information_diet.

## The hidden_facts registry

`hidden_facts` is the canonical answer key used by all downstream steps. Each entry contains:

- `fact_id`, `source_subcategory`, `claim`, `ground_truth_label`
- `behavioral_evidence_from_interview` (Q## quotes)
- `duplicate_of`, `also_supported_by` (for deduplication traceability)

## Running

```bash
python generator.py \
  --seed data_samples/input/{name}_seed.json \
  --output data_samples/output/
```

## Notes

- The interview questionnaire (109 questions) is embedded directly in `prompt.txt`. No separate questionnaire file is required.
- The expert summaries are generated in Step 2 and are NOT regenerated during verification. Verification only corrects the preferences and produces the hidden_facts registry.
