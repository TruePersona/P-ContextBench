# Persona-Bench

**CSC 699 — AI Safety Benchmark "Social World"**

## The Big Picture

We're building a test to see if an AI can figure out who someone is just by reading their text messages and calendar.

To do that, we need fake people with realistic lives. This pipeline creates those fake people step by step, starting from basic demographics and ending with a full life profile and social circle.

## Why This Exists

The end goal (Steps 4-6) is to:
1. Take a fake person's profile
2. Generate realistic app logs (text messages, calendar events) that show their daily life
3. Hide facts about the person inside those logs using behavioral clues (e.g., never say "has diabetes" — instead show daily glucose checks, food adjustments, doctor appointments)
4. Ask an AI: "Based on these logs, what can you figure out about this person?"
5. Score how well the AI does

**Steps 1-3 (this repo)** build the fake people. Steps 4-6 test the AI.

## The Pipeline: What Each Step Does

### Step 1: Get a Starter Person

**What:** Pull a basic person from NVIDIA's dataset of 6 million fake Americans.

**What you get:** A JSON file with bare-bones info — name, age, gender, job, city, education, plus short paragraphs about their professional life, sports interests, arts interests, travel style, food preferences, and cultural background.

**Example:** Mary Alberti, 28, female, fast food worker, Madison WI, high school education, Italian-American, Catholic upbringing.

**That's it.** This is just a starting point. The person is flat — a sketch, not a character.

**File:** `PersonaEngine/step1_seed/data_samples/output/mary_alberti_seed.json`

---

### Step 2: Interview the Person

**What:** We give an LLM the starter person and say: "You are this person. Answer 109 life-history interview questions as them."

**Why 109 questions?** They come from a Stanford research paper (Park et al. 2024) that interviewed 1,000 real people. The questions cover everything: childhood, family, work, health, religion, politics, finances, daily routine, relationships, hopes, values.

**What you get:** Two things in one file:

1. **The transcript** — The full Q&A. 109 questions, each with 2-3 follow-ups. This is the raw interview, like a recording.

2. **The extracted profile** — A compressed summary of everything important from the interview, organized into categories so downstream steps can use it. Think of it like cliff notes of the interview.

**Why do we need the extracted profile?** Because the interview is LONG (hundreds of Q&As). Downstream steps can't re-read the whole thing every time. The extracted profile is the portable, structured version.

**What's inside the extracted profile:**

| Section | What it is | Why it exists |
|---------|-----------|---------------|
| **Demographics** | Name, age, gender, location, education, job | Basic identity header |
| **Preferences** (18 subcategories) | Health, food, travel, social life, home, entertainment, hobbies, work, arts, sports, nature, tech, community, music, fashion, cultural/linguistic, life events, media diet | Everything the person likes, does, and chooses — organized by life domain. Each has a summary, specific behavioral details, and Q## citations back to the interview. |
| **Summaries** (4 experts) | Demographer, Behavioral Economist, Political Scientist, Psychologist | Four different expert lenses analyzing the same person. The demographer looks at life stage and social status. The economist looks at how they make decisions. The political scientist looks at civic engagement. The psychologist looks at personality and coping patterns. |

**Verification (within the same step folder):** Four AI experts review the interview and check for mistakes, then fix them.

The 4 checks (directions):

1. **Seed vs Interview** — Did the interview contradict the original NVIDIA data? (e.g., seed says age 28, interview says 30)
2. **Interview vs Profile** — Did the extracted profile accurately capture what was said? (e.g., person talked about gardening in Q17 but it's missing from hobbies)
3. **Profile vs Itself** — Does the profile contradict itself? (e.g., summaries say she's frugal but preferences say she shops at expensive stores)
4. **Completeness** — Is anything from the interview missing from the ENTIRE profile? (e.g., person mentioned a brother in Q05 but he appears nowhere)

After verification, the **hidden_facts registry** is generated: every atomic, testable fact about the persona is enumerated from the verified preferences and expert summaries, deduplicated, and stored as the canonical answer key for all downstream steps.

**What you get:** Two files:

1. **Interview** — The full transcript + draft extracted profile.
2. **Verification** — The accountability trail, corrected profile, and hidden_facts registry. **This is the canonical output that downstream steps use.**

**Files:** `PersonaEngine/step2_interview/data_samples/output/{name}_interview.json` and `{name}_verification.json`

---

### Step 3: Create Their Social Circle

**What:** Generate the 5 people this person most frequently exchanges personal text messages with.

**Why:** Steps 4-6 need text message conversations. You can't have text messages without people to text. The social circle gives each person someone to talk to, with realistic relationships and shared interests.

**What you get:** 5 people, each with:
- Who they are (name, age, job, location)
- How they know the person (family? friend? neighbor?)
- Their own personality and communication style
- What they do together
- What they've been texting about recently
- Q## evidence from the interview proving this relationship makes sense

The 5 people are whichever contacts the interview evidence most strongly supports. No rigid quota — some personas may have mostly family, others mostly friends. People who would only communicate on a company-owned messenger are excluded.

**Verification (within the same step folder):** Two checks confirm the social circle is consistent with the interview and the extracted profile, then produce a corrected social circle.

**Files:** `PersonaEngine/step3_social_circle/data_samples/output/{name}_social_circle.json` and `{name}_social_circle_verification.json`

---

### Step 4: App Log Synthesizer *(Anmol)*

Generate messenger snippets and calendar events that implicitly embed the persona's hidden facts through behavioral evidence. The benchmark evaluator sees only these app logs.

### Step 5: Test Case Synthesis *(Anmol)*

Generate benchmark test cases that require recovering hidden facts from app logs alone. Test cases are verified for human-solvability following SWE-bench Verified methodology.

### Step 6: Benchmark Runner *(Anmol)*

Execute the verified test cases against the model under evaluation and score performance against the canonical hidden_facts registry.

---

## The 5 Personas (from NVIDIA's dataset)

| # | Name | Age | Location | Education | Occupation |
|---|------|-----|----------|-----------|------------|
| 1 | Mary Alberti | 28 | Madison, WI | High school | Fast food worker |
| 2 | Alicia Gonzalez | 29 | Chico, CA | Bachelor's | CS researcher |
| 3 | Deeva Cintron | 85 | Saline, MI | Some college | Retired |
| 4 | Maria Buendia | 34 | Lilburn, GA | 9th-12th no diploma | No occupation |
| 5 | Julio Simmons | 49 | Rochester, NY | Graduate | Not in workforce |

## Repository Structure

```
/
├── README.md
├── Contributor.md
├── LICENSE                      # Apache 2.0
├── Top_level_generator.py       # Orchestrates the full pipeline
└── PersonaEngine/
    ├── step1_seed/
    │   ├── README.md
    │   ├── prompt.txt
    │   ├── generator.py
    │   └── data_samples/
    │       └── output/          # 5 seed JSONs
    ├── step2_interview/
    │   ├── README.md
    │   ├── prompt.txt           # 109-question interview prompt
    │   ├── verification_prompt.txt
    │   ├── generator.py         # Iterative refinement loop
    │   └── data_samples/
    │       └── output/          # Interview + verification JSONs
    ├── step3_social_circle/
    │   ├── README.md
    │   ├── prompt.txt
    │   ├── verification_prompt.txt
    │   ├── generator.py
    │   └── data_samples/
    │       └── output/          # Social circle + verification JSONs
    ├── step4_app_log_synthesizer/
    ├── step5_testcases_synthesis/
    └── step6_benchmark_runner/
```

Each step is self-contained: prompt, verification prompt, generator script, and sample data. The generator script runs the prompt, verifies, and regenerates if needed.

## How to Reproduce

For each persona, run the generator scripts in order (Step 1 → 2 → 3). All prompts are model-agnostic and self-contained — fill in the `{{placeholders}}` with actual data. Each step's `README.md` has detailed instructions.

Short version:
```bash
python Top_level_generator.py --seed PersonaEngine/step1_seed/data_samples/output/{name}_seed.json
```

## References

| Paper | What we use it for |
|-------|-------------------|
| Park et al. 2024 — "Generative Agent Simulations of 1,000 People" | The 109 interview questions and verification approach |
| Ge et al. 2024 — PersonaHub (Tencent AI Lab) | The Persona-to-Persona method for generating social circles |
| Jimenez et al. 2024 — SWE-bench Verified | Human-in-the-loop test case verification methodology |
| Jiang et al. 2025 — PersonaMem-v2 | Design principles: implicit preferences, broad domains, compact summaries |
| NVIDIA Nemotron-Personas-USA | The starter people (seed data) |

## Team

- **Abdul** — Pipeline implementation (Steps 1-3), prompt engineering
- **Miles** — Persona-to-Persona approach (Step 3)
- **Anmol** — App log synthesis, test cases, benchmark runner (Steps 4-6)

## License

Apache 2.0
