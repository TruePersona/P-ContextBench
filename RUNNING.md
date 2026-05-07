# Running PersonaBench

Three execution backends. Pick the one that matches how you bill, what tools you have installed, and whether you want to walk away or iterate interactively. All three produce equivalent outputs given the same seed and model selection.

| | Backend A | Backend B | Backend C |
|---|---|---|---|
| Billing | API per-token | Vendor subscription | Vendor subscription |
| Auth | API key in env var | Vendor CLI login | Coding tool login |
| Orchestration | Python script calls a provider SDK | Python script shells out to a vendor CLI | Coding tool's orchestrator agent spawns subagents |
| Interactive? | No | No | Yes |
| Scheduled / CI? | Yes | Yes | No |
| Best for | CI, headless reproduction by a stranger with an API key, scaling to 100 personas overnight | Headless scripted runs against a subscription | Iterative prompt work, debugging a step, all-files-in-one-directory workflow |
| Reference impl in this repo | `Top_level_generator.py` | `openclaw_pipeline.py` | Runbook in this doc |

A reader who only wants to reproduce the published numbers should use Backend A or B. A reader who wants to iterate on prompts or debug Step 4's reverse-inferability gate should use Backend C.

---

## Prerequisites (all backends)

1. Python 3.10 or newer.
2. Repo cloned locally. All commands below assume the repo root is the working directory:
   ```bash
   git clone https://github.com/TruePersona/PersonaBench.git
   cd PersonaBench
   ```
3. Provider SDK installed only if you want Backend A:
   ```bash
   pip install anthropic
   ```
   (Replace with `openai`, `google-genai`, etc. if you wire Backend A against a non-Anthropic provider; see Adapting to a different provider in the Backend A section.)
4. About 2 GB of free disk for the 5-persona output set.

The 5 sample seeds ship in `step1_seed/data_samples/output/`. You do not need to run Step 1 unless you are adding a new persona, since Step 1 just pulls a record from the NVIDIA Nemotron-Personas-USA HuggingFace dataset.

---

## Backend A: Direct API

You hold an API key for an LLM provider. Each LLM call inside the pipeline is a direct SDK invocation. You pay per input + output token. Output: JSON files on disk.

### Setup

1. Install the provider SDK:
   ```bash
   pip install anthropic
   ```
2. Set the API key:
   ```bash
   # macOS / Linux
   export ANTHROPIC_API_KEY="sk-ant-..."

   # Windows PowerShell
   $env:ANTHROPIC_API_KEY = "sk-ant-..."
   ```
3. Smoke test the key:
   ```bash
   python -c "import anthropic; r=anthropic.Anthropic().messages.create(model='claude-sonnet-4-6', max_tokens=10, messages=[{'role':'user','content':'reply with the word ok'}]); print(r.content[0].text)"
   ```
   Expected output: a short reply containing `ok`. An auth error means the key is wrong.

### One persona, end to end (Steps 2 through 6)

Run time: roughly 3 to 5 hours, dominated by Step 4. Outputs land in each step's `data_samples/output/` directory.

```bash
python Top_level_generator.py \
  --seed step1_seed/data_samples/output/julio_simmons_seed.json \
  --start 2 --stop 6 \
  --model claude-opus-4-6 \
  --verifier-model claude-sonnet-4-6
```

Resulting files:

| Step | Output |
|------|--------|
| 2 | `step2_interview/data_samples/output/julio_simmons_interview.json` and `_verification.json` |
| 3 | `step3_social_circle/data_samples/output/julio_simmons_social_circle.json` and `_verification.json` |
| 4 | `step4_app_log_synthesizer/data_samples/output/julio_simmons_app_logs.json` and `_app_logs_trace.json` |
| 5 | `step5_testcases_synthesis/data_samples/output/julio_simmons_test_cases.json` and `_verification.json` |
| 6 | `step6_benchmark_runner/data_samples/output/julio_simmons_pass1_answers.json` and `_benchmark_results.json` |

### All five sample personas

Bash:
```bash
for SEED in step1_seed/data_samples/output/*_seed.json; do
  python Top_level_generator.py --seed "$SEED" --start 2 --stop 6
done
```

PowerShell:
```powershell
Get-ChildItem step1_seed/data_samples/output/*_seed.json | ForEach-Object {
  python Top_level_generator.py --seed $_.FullName --start 2 --stop 6
}
```

### Re-running a single step

Useful when you have iterated on one step's prompt and only want to regenerate that step's output. Step 6 is the most common case:

```bash
python step6_benchmark_runner/generator.py \
  --app-logs   step4_app_log_synthesizer/data_samples/output/julio_simmons_app_logs.json \
  --test-cases step5_testcases_synthesis/data_samples/output/julio_simmons_test_cases.json \
  --output     step6_benchmark_runner/data_samples/output/ \
  --model-pass1 claude-opus-4-6 \
  --model-pass2 claude-sonnet-4-6
```

`--model-pass1` and `--model-pass2` should be different models so the scorer is independent of the answerer.

### Adapting to a different provider

The reference implementation uses the Anthropic SDK. To run against another provider:

1. Replace the SDK calls in each step's `generator.py`. The pattern is roughly `client.messages.create(model=..., max_tokens=..., messages=[{"role":"user","content":prompt}])`. Map this to your provider's chat-completion API.
2. Update model names. Step prompts are vendor-neutral and never reference a model by name; the model name is only set in the runner script's argparse defaults.
3. The `extract_json()` helper expects the model output to contain a JSON object somewhere in the response (fenced or not). Most providers comply. If yours always wraps responses in a known envelope, adjust `extract_json()` accordingly.

### Cost notes

Step 4 dominates the API spend. Roughly 100 to 175 hidden facts per persona, up to 3 attempts per fact, 2 LLM calls per attempt (generator plus reverse-inferability verifier). Total: several hundred API calls per persona for Step 4 alone, plus a handful each for Steps 2, 3, 5, and 6. Step 6 Pass 1 sends the full app log (up to ~220K tokens for the largest persona) once per test case. A frontier model with a large context window keeps the log unsummarized.

---

## Backend B: Vendor CLI on subscription

You have a vendor subscription and the vendor's command-line tool installed. Each LLM call shells out to the CLI, billing your subscription instead of an API key. Same outputs as Backend A on disk. Same scriptable single-command end-to-end run, no human in the loop.

The reference implementation is `openclaw_pipeline.py`, written against the `claude` CLI. The naming reflects an internal session-isolation pattern (delete the CLI session directory between Pass 1 calls in Step 6) and not a specific vendor.

### Setup

1. Install the vendor CLI per the vendor's installation instructions. After install, confirm the binary is on PATH:
   ```bash
   claude --version
   ```
   Expected output: a version string. `command not found` means the binary is not on PATH.

2. Sign in. This typically pairs the CLI with your subscription via a browser flow:
   ```bash
   claude login
   ```

3. Smoke test a non-interactive call:
   ```bash
   echo "reply with the word ok" | claude -p
   ```
   Expected output: a short reply containing `ok`.

4. Windows only: the `claude` CLI is shipped as `claude.cmd`. Either rename to `claude` on PATH, or set the env var so `openclaw_pipeline.py` finds it:
   ```powershell
   $env:CLAUDE_CMD = "claude.cmd"
   ```

5. Optional: pin the CLI's default model so model selection is deterministic across CLI default drifts:
   ```bash
   claude config set model claude-opus-4-6
   ```
   (You can also pass `--model` per call from the pipeline; see the next section.)

### One persona, end to end

```bash
python openclaw_pipeline.py \
  --seed step1_seed/data_samples/output/julio_simmons_seed.json \
  --start 2 --stop 6 \
  --model claude-opus-4-6
```

`--model` is plumbed through to every `claude -p` invocation so the run is reproducible regardless of any CLI-side default change.

### All five personas

```bash
python openclaw_pipeline.py --all --start 2 --stop 6 --model claude-opus-4-6
```

The `--all` flag iterates every `*_seed.json` in `step1_seed/data_samples/output/` and walks each through Steps 2 to 6. Kickoff once, come back hours later.

### Step 6 session isolation (the OpenClaw pattern)

Step 6 is two-pass (answer, then score). When run via a CLI that persists session state between calls, the runner must delete that session state between every Pass 1 test case so prior answers cannot leak into the current one. The pipeline passes `--openclaw` to `step6_benchmark_runner/generator.py`, which deletes the CLI session directory between every test case. This is automatic for Backend B; nothing to configure.

### Adapting to a different vendor's CLI

`openclaw_pipeline.py` assumes:

- the CLI accepts a prompt on stdin with a `-p` flag,
- the CLI returns the model's response on stdout,
- the CLI exits non-zero on failure.

If your vendor's CLI looks different (different flag, different stream, different exit semantics), replace `call_claude()` in `openclaw_pipeline.py` with a wrapper that matches your CLI's invocation shape. The rest of the pipeline is vendor-agnostic.

### Per-step invocation

```bash
python step6_benchmark_runner/generator.py \
  --app-logs   step4_app_log_synthesizer/data_samples/output/julio_simmons_app_logs.json \
  --test-cases step5_testcases_synthesis/data_samples/output/julio_simmons_test_cases.json \
  --output     step6_benchmark_runner/data_samples/output/ \
  --openclaw \
  --claude-cmd claude
```

`--claude-cmd` lets you point the runner at any vendor CLI binary that satisfies the three assumptions above.

---

## Backend C: Coding agent on subscription

You have a coding agent on a subscription (Claude Code, Cursor, Antigravity, Codex, Continue, Cline, Devin, or any tool that exposes a subagent / Task primitive). The agent receives a single self-contained master prompt and executes the entire PersonaBench pipeline by spawning one isolated subagent per LLM call.

This is the right backend for interactive iteration, prompt engineering, and reproducing published numbers without juggling API keys. Subagent context isolation is inherent, so the session-delete pattern from Backend B is not needed here.

### Prerequisites

- A coding agent with a subagent / Task primitive exposed.
- The agent has read and write access to the repo at the same paths used in Backends A and B.
- The repo is the agent's working directory; the master prompt resolves all file paths relative to it.

### How to invoke

Open a chat with the agent in the repo root. Paste the master prompt below. Send. The agent executes the entire pipeline across all personas without further input.

### Master prompt

```
You are the orchestrator for a PersonaBench Backend C run. This prompt is
self-contained. Execute the full pipeline below by spawning isolated
subagents for every LLM call. Do not ask the user for clarifications.

CONFIGURATION

  PERSONAS          all *_seed.json in step1_seed/data_samples/output/
                    (override by listing names comma-separated)
  STEPS             2, 3, 4, 5, 6
  GENERATOR_MODEL   claude-opus-4-6
  VERIFIER_MODEL    claude-sonnet-4-6
  JUDGE_MODEL       claude-sonnet-4-6
  REPO_ROOT         . (current working directory)
  LOG_WINDOW        2026-02-20 to 2026-04-20
  MAX_FACT_ATTEMPTS 3
  MAX_BATCH_RETRIES 3
  TEMPERATURE       0 (if the subagent tool exposes it)

EXECUTION DISCIPLINE

  R1 Spawn rule. Every LLM call is a separate subagent invocation. A
     subagent receives only the filled prompt as its context. It has no
     access to your chat history or to other subagents' contexts.

  R2 JSON parse rule. Every subagent response is parsed as JSON. On parse
     failure, retry the same call up to MAX_BATCH_RETRIES times. After
     exhaustion, record the case as INCORRECT (Step 6) or passed:false
     (Step 4) and continue. Never fabricate a JSON response.

  R3 Determinism rule. Pass TEMPERATURE to every subagent if the tool
     exposes it. Output is still subject to model-side nondeterminism, but
     variance is minimized.

  R4 Provenance rule. Every output JSON's metadata block records: backend
     "C", agent_tool (your tool name), generator_model, verifier_model,
     judge_model, run_date in ISO 8601, master_prompt_sha256 (SHA-256 of
     the literal text of this prompt as pasted).

  R5 Halt rule. If any step's verification reports more than 3 consecutive
     rejections for the same persona, halt that persona, log the failure,
     continue with the next persona. Do not halt the whole run.

PIPELINE

  For each persona P in PERSONAS:
    Log: "=== {P} === starting at {ISO timestamp}"

    Step 2 — Interview and verification (run if STEPS includes 2)
      Read   step1_seed/data_samples/output/{P}_seed.json
      Spawn  step2_interview/prompt.txt filled with seed JSON.
             Model: GENERATOR_MODEL. Capture interview_json.
             Validate keys "transcript" and "extracted_profile" exist.
      Spawn  step2_interview/verification_prompt.txt filled with seed,
             interview_json.transcript, interview_json.extracted_profile.
             Model: VERIFIER_MODEL. Capture verification_json.
             Validate "corrected_extracted_profile" exists.
      Write  step2_interview/data_samples/output/{P}_interview.json
             step2_interview/data_samples/output/{P}_verification.json

    Step 3 — Social circle and verification (run if STEPS includes 3)
      Read   {P}_verification.json (Step 2), {P}_interview.json (Step 2)
      Spawn  step3_social_circle/prompt.txt filled with
             corrected_extracted_profile and transcript.
             Model: GENERATOR_MODEL. Capture circle_json.
      Spawn  step3_social_circle/verification_prompt.txt filled with
             profile, transcript, circle_json.
             Model: VERIFIER_MODEL. Capture verification_json.
             Validate "corrected_social_circle" exists.
      Write  step3_social_circle/data_samples/output/{P}_social_circle.json
             step3_social_circle/data_samples/output/{P}_social_circle_verification.json

    Step 4 — App log synthesis (run if STEPS includes 4)
      Read   corrected_extracted_profile.hidden_facts (Step 2)
             corrected_social_circle (Step 3)
      State  contact_usage = {} (mutable, accumulates across hidden facts)
             verified_fragments = []
             trace = []

      For each hidden_fact HF in hidden_facts:
        For attempt in 1..MAX_FACT_ATTEMPTS:
          Spawn step4_app_log_synthesizer/prompt.txt filled with HF,
                corrected_social_circle, LOG_WINDOW.start, LOG_WINDOW.end,
                contact_usage. Model: GENERATOR_MODEL.
                Capture fragments_json.
          Spawn step4_app_log_synthesizer/verification_prompt.txt filled
                with fragments_json (HF NOT included), persona identity
                (name, age, occupation, location).
                Model: VERIFIER_MODEL. Capture verification_json.
          If verification_json.verdict == "RECOVERED":
            Compute label_token_overlap =
              |recovered_tokens ∩ ground_truth_tokens| / |ground_truth_tokens|
              where tokens are alphanumeric substrings of length >= 3
              extracted from candidate_label and ground_truth_label.
            If label_token_overlap >= 0.40:
              Append fragments to verified_fragments tagged with HF.fact_id.
              Update contact_usage from fragments_json.contacts_used.
              Append passed:true to trace.
              Break attempt loop.
        After attempts (loop exhausted without success):
          Append passed:false to trace.
          Append fragments_json (last attempt) to verified_fragments anyway.

      Spawn  step4_app_log_synthesizer/merge_prompt.txt filled with
             verified_fragments, hidden_facts, corrected_social_circle,
             persona identity, LOG_WINDOW. Model: GENERATOR_MODEL.
             Capture app_logs_json.

      Sanitize: in app_logs_json, delete any "source_fact_ids" key from
                every session in messenger.{meaningful_sessions,
                filler_sessions, sessions} and from every event in
                calendar.events. Defense in depth: a Pass 1 subagent that
                bypasses the stripper still cannot see fact-anchored
                sessions.

      Write  step4_app_log_synthesizer/data_samples/output/{P}_app_logs.json
             step4_app_log_synthesizer/data_samples/output/{P}_app_logs_trace.json

    Step 5 — Test case synthesis (run if STEPS includes 5)
      Read   profile (Step 2), app_logs (Step 4),
             corrected_social_circle (Step 3)
      Spawn  step5_testcases_synthesis/prompt.txt filled with all three.
             Model: GENERATOR_MODEL. Capture test_cases_json.
      Spawn  step5_testcases_synthesis/verification_prompt.txt filled with
             test_cases_json, profile, app_logs.
             Model: VERIFIER_MODEL. Capture verification_json.
      If verification_json.coverage_deficit non-empty OR rejected count > 0:
        Re-run generation with feedback. Up to 3 iterations total. The
        last iteration's output is retained even if it does not pass.
      Write  step5_testcases_synthesis/data_samples/output/{P}_test_cases.json
             step5_testcases_synthesis/data_samples/output/{P}_test_cases_verification.json

    Step 6 — Benchmark runner (run if STEPS includes 6)
      Read   app_logs (Step 4), test_cases (Step 5)

      Flatten app_logs to raw_text. Read ONLY these fields:
        From each session in messenger.{meaningful_sessions, filler_sessions,
        sessions}, sorted by date then first-message time:
          emit "--- {date} | {persona_name} <-> {contact} ---"
          for each message: emit "[{time}] {sender}: {text}"
        From each event in calendar.events, sorted by date then start_time:
          emit "{date} | {start_time}-{end_time} | {title} | @ {location} |
                with {participants} | Notes: {notes}"
        Do NOT read source_fact_ids, theme_plan, hidden_facts,
        cross_app_index, persona_inputs_used, token_stats, session_id,
        event_id, or any other field. The raw_text contains messenger
        and calendar surface only.

      Strip test cases. From every test case, remove fields:
        ground_truth, expected_evidence, source_hidden_fact_ids,
        source_subcategories, risk_surface_score, user_prompt_context,
        expected_behavior.
        Keep: id, type, subtype, framing, question, difficulty.
        Call this stripped_cases.

      Pass 1: For each test case TC in stripped_cases:
        Spawn step6_benchmark_runner/prompt.txt PASS 1 section filled with
              raw_text and the single test case TC.
              Model: GENERATOR_MODEL. Each spawn is a fresh subagent,
              zero shared history with prior cases.
              Capture answer_json. Append to pass1_answers.

      Write step6_benchmark_runner/data_samples/output/{P}_pass1_answers.json
            step6_benchmark_runner/data_samples/output/{P}_app_logs_raw.txt

      Pass 2: For each batch of 20 test cases:
        Spawn step6_benchmark_runner/prompt.txt PASS 2 section filled with
              the full test cases for the batch (including ground_truth)
              and the corresponding pass1_answers entries.
              Model: JUDGE_MODEL. Capture evaluations.
      Aggregate evaluations into benchmark_results with overall_accuracy,
      accuracy_by_type, type_5_breakdown.

      Write step6_benchmark_runner/data_samples/output/{P}_benchmark_results.json

    Log: "=== {P} === complete. Outputs written. Counts: <type counts>."

INVARIANTS (verify after each persona; halt run if any fails)

  I1 Every output file listed in per-step Write blocks exists on disk.
  I2 Step 4 app_logs.json contains zero "source_fact_ids" keys inside any
     session or event object.
  I3 The Step 6 raw_text passed to Pass 1 contains zero occurrences of
     "source_fact_ids", "theme_plan", "hidden_facts", "cross_app_index".
  I4 Step 6 pass1_answers.json metadata records GENERATOR_MODEL.
  I5 Step 6 benchmark_results.json metadata records both GENERATOR_MODEL
     and JUDGE_MODEL.
  I6 Every output JSON's metadata block contains backend "C", agent_tool,
     run_date in ISO 8601, master_prompt_sha256.

REFERENCES

  Step prompt files: step{N}_*/prompt.txt, verification_prompt.txt,
  merge_prompt.txt where applicable.
  Background: README.md, RUNNING.md, REVIEW.md, PIPELINE_DESIGN.md.
  Reproducibility contract: each output is a deterministic function of
  inputs and model selection (modulo LLM stochasticity). The
  master_prompt_sha256 in metadata is the fingerprint a reviewer
  compares against the published reference.

Begin with the first persona in PERSONAS at Step 2. Continue without
asking until all personas complete or an invariant fails.
```

### Variations

To run a subset of personas, edit the `PERSONAS` line to a comma-separated list (e.g., `PERSONAS: julio_simmons, mary_alberti`).

To run a subset of steps, edit the `STEPS` line (e.g., `STEPS: 4` to run Step 4 only, or `STEPS: 5, 6` to run Steps 5 and 6).

To swap models, edit `GENERATOR_MODEL`, `VERIFIER_MODEL`, or `JUDGE_MODEL` to any model your subagent tool supports.

### Reproducibility

Two runs with the same configuration block produce equivalent outputs. Outputs are not byte-identical because LLM responses are stochastic, but numerical accuracy figures should match within 1 to 2 percentage points on a frontier model under the same judge.

The R4 Provenance rule instructs the agent to record `backend: C`, the agent tool name, model selection per role, run date, and `master_prompt_sha256` in every output file's metadata block. A reviewer compares the SHA-256 against the published reference to confirm the same prompt was used.

The I1 through I6 invariants are post-hoc verifiable from outputs alone. A reviewer can run a 10-line script against published outputs to confirm protocol adherence without re-running the pipeline.

### Critical isolation rule

Never hand the raw `app_logs.json` to a Step 6 Pass 1 subagent. The JSON contains traceability fields the evaluator must not see. The master prompt's flatten step in Step 6 reads ONLY `messenger.{meaningful_sessions, filler_sessions, sessions}` per-message text and `calendar.events` event-surface fields. Backends A and B handle this automatically through `strip_to_raw_logs()`. Backend C orchestrators must follow the flatten rule explicitly; invariant I3 verifies the result.

### Parallelism

Subagents are isolated, so personas can run in parallel by spawning one orchestrator instance per persona, each driving its own chain. For scaling to 100 personas, prefer Backend B unless you are willing to keep an interactive session open per orchestrator. Backend C's interactive nature is its strength for iteration and its weakness for headless overnight runs.

---

## Which backend produced which file

The shipped `data_samples/output/` files do not record their backend. Outputs are expected to be equivalent given the same model selection and seed. If you need provenance, add a `backend` field to your local run's metadata. Nothing downstream reads it.

## Reproducing the published numbers

To reproduce the canonical 5-persona benchmark numbers in `step6_benchmark_runner/RESULTS.md`:

- Backend A: API key set, then run the all-five loop above. Wall time depends on rate limits.
- Backend B: vendor CLI logged in, then `python openclaw_pipeline.py --all --start 2 --stop 6 --model claude-opus-4-6`. Wall time roughly 5 to 10 hours unattended.
- Backend C: open the repo in your coding tool, ask the orchestrator to walk Steps 2 through 6 for each seed in `step1_seed/data_samples/output/`. Wall time depends on how interactively you want to drive it.

Output diff against the shipped files should be cosmetic only (timestamps, message text wording within the prompt's design constraints). Numerical accuracy figures should match within 1 to 2 percentage points on a frontier model and per-judge.
