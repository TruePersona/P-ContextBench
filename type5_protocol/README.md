# Local Type 5 protocol experiments

Candidate **0.4**, isolated from the published benchmark scorer. Read
[PROTOCOL.md](PROTOCOL.md) for the construct and release gates, and
[FOLLOWUP.md](FOLLOWUP.md) for the latest experiments. Historical results remain
in [EXPERIMENTS.md](EXPERIMENTS.md). Existing corpus files are unchanged.

The runner evaluates an actual response against justified requirements for
context, useful progress, and boundaries. Every requirement is mandatory;
`critical` controls severity reporting only. Whole-response checks cover material
factual grounding, authorization, execution honesty, consistency, and unnecessary
intervention. There is no compensating partial-credit headline score.

## Reproduce a compact pilot

Use a new directory for a changed dataset or protocol. This example creates a new
copy; it does not overwrite the archived 0.2 study.

```bash
python3 -m type5_protocol.curated_pilot --workdir _orchestration/type5_protocol/curated_v4_replay
python3 -m type5_protocol.review --workdir _orchestration/type5_protocol/curated_v4_replay
python3 -m type5_protocol.review --workdir _orchestration/type5_protocol/curated_v4_replay --families
python3 -m type5_protocol.experiment answer --workdir _orchestration/type5_protocol/curated_v4_replay --run haiku_full
python3 -m type5_protocol.experiment judge --workdir _orchestration/type5_protocol/curated_v4_replay --run haiku_full
python3 -m type5_protocol.experiment summarize --workdir _orchestration/type5_protocol/curated_v4_replay --run haiku_full
```

Answering defaults to Claude Haiku 4.5; review and judging default to GPT-5.5.
Choose model/backend explicitly when comparing conditions. The transports use
installed CLI subscription logins, isolated working directories, and tool-free
inference. The Claude subprocess removes an inherited `ANTHROPIC_API_KEY`.
No automatic provider substitution or API fallback occurs.

Answerers return ordinary text. Reviews and judgments return structured records.
Bounded schema/quotation repairs retain raw attempts; they never select a better
behavioral score. Transport failures and unresolved observations remain in the
intended evaluation denominator.

Within a study, successful calls are cached by exact input and configuration.
A new run name alone reuses answers. Pass a new `--replicate` ID for independent
draws. Identical diagnostic inputs share a locked cache entry and must not count
as independent samples. Summaries audit raw answer/judge bindings and the scoring-version binding before
scoring. Citation validation permits only straight/curly quote typography changes;
every accepted citation retains the actual source text and character span.
Words, numbers, whitespace, negation, and dashes are never normalized.

`--condition relevant`, `facts`, and `no_history` require separate run IDs.
Relevant excerpts and explicit facts are privileged diagnostics, not evaluated
retrieval systems. No-history uses base cases and a separate available-information
rubric; its score cannot be subtracted from full-history success as a
personalization gain. The `generic_caution`, `always_clarify`, and `always_confirm`
answer models are fixed baselines.

## Public-context policy experiments

[POLICY_EXPERIMENT.md](POLICY_EXPERIMENT.md) reports the first application of the
[Meta-Harness analysis](META_HARNESS_REVIEW.md). `context_policy.py` provides three
trusted, stateless policies: complete history, lexical retrieval, and lexical
retrieval with linked records. Policies receive only public episode JSON and
return exact source spans. The trusted renderer preserves original text, speaker,
timestamp, source ID, request, clock, task state, and capabilities. The first
interface supports complete log records, avoiding cuts through negation or
permission scope. It does not execute arbitrary candidate code.

`policy_study.py` freezes a complete comparison matrix before inference: admitted
cases, policies and dependencies, prompts, evaluator, models, character budgets,
replicate IDs, and call ceilings. The answerer sees selected evidence; the judge
always sees the **complete original episode and contract**. Retrieval never gets
the easier no-history rubric. Frozen protocol 0.4 and earlier studies remain
unchanged. Previously inspected holdouts are development evidence here.

```bash
python3 -m type5_protocol.policy_pilot --workdir _orchestration/type5_protocol/policy_proposals
python3 -m type5_protocol.review --workdir _orchestration/type5_protocol/policy_proposals
python3 -m type5_protocol.review --workdir _orchestration/type5_protocol/policy_proposals --families
# A rejected family stays in the admission inventory. Register only after review.
python3 -m type5_protocol.policy_study register --source _orchestration/type5_protocol/policy_proposals --workdir _orchestration/type5_protocol/policy_trial --budget-chars 12000 --replicates r1 r2
python3 -m type5_protocol.policy_study run --workdir _orchestration/type5_protocol/policy_trial --workers 4
python3 -m type5_protocol.policy_study compare --workdir _orchestration/type5_protocol/policy_trial
python3 -m type5_protocol.policy_study export --workdir _orchestration/type5_protocol/policy_trial --output policy_trial.json.gz
```

The comparison reports paired changes by requirement, selected and omitted
sources, case/family outcomes, errors, retrieval time, and inference usage/cost.
Twelve thousand characters means the serialized log array including attribution;
it is not a token estimate. Complete history is unbounded. Short histories that
fit are identical across arms and share cached calls within a replicate. They
are regression controls, not additional independent retrieval comparisons.

The gzip export is a standard JSON archive containing original datasets, code,
registration, reviews, exact inference inputs/outputs, and every result. Decompress
with Python's `gzip` module. Each entry in `files` is keyed by its study-relative
path. No credentials are required to inspect the archive.

For human validation of policy runs, export dedicated packets:

```bash
python3 -m type5_protocol.policy_human_review packets --workdir STUDY
python3 -m type5_protocol.human_validation --packet STUDY/human_review/development/blind_cases.json --kind cases --output case_ratings_template.json
python3 -m type5_protocol.human_validation --packet STUDY/human_review/development/blind_answers.json --kind answers --output answer_ratings_template.json
```

Reviewers see complete public evidence and actual answers, with model identities,
policy names, proposed contracts, and model judgments withheld. Identical answers
to the same case are reviewed once. After two independent reviews and adjudication
using the workflow below, use `policy_human_review calibrate --workdir STUDY --run
RUN --case-reference CASE_REFERENCE --answer-reference ANSWER_REFERENCE --output
REPORT` to measure that run's judge errors. Missing ratings remain unresolved.

## Broader construction and admission

`expanded_pilot.py` constructs the registered 24 families from 12 source personas.
Each has base, decisive-context contrast, and irrelevant-control episodes.
`review.py` performs blind interpretation before contract alignment and separately
checks each family. Source expected behaviors are hypotheses, not answer keys.

The default material-v3 review profile separates material defects from editorial notes,
provides the complete shared scoring policy, and treats every obligation as mandatory.
Model review remains fallible; its acceptance is not a human validity judgment.
`revise_pilot.py` performs one documented case-quality repair pass before answering.
Preserve each construction/review revision in a separate directory. Do not keep
regenerating until a desired acceptance or answerer success rate is reached.

`admit_pilot.py` requires a complete review inventory, admits only fully bound
case/family approvals, and retains every excluded family and reason. It reports
performance's conditional population explicitly. The retained study additionally
records technical review recoveries, including their reviewer identities.

```bash
python3 -m type5_protocol.expanded_pilot --workdir _orchestration/type5_protocol/new_proposals
python3 -m type5_protocol.review --workdir _orchestration/type5_protocol/new_proposals --backend claude --model claude-sonnet-4-6
python3 -m type5_protocol.review --workdir _orchestration/type5_protocol/new_proposals --backend claude --model claude-sonnet-4-6 --families
```

Repeat review with `--split heldout` before freezing a broader study. A held-out
run requires `experiment freeze --split heldout --run freeze` after all admitted
cases are reviewed. Data, prompts, common checks, and core code must remain
unchanged. Freezing does not constitute human validation.

`challenge_pilot.py` adds authored controls for selective non-use of private
history, genuinely missing recipient identity, and resolved permission.
`full_history.py` retains every visible source message and calendar event while
removing private annotations and meaningful/filler labels. Its constructed updates
and timezone assumption are explicit. All full-history contracts require fresh
review; compact-case validity is not presumed to transfer.

## Judge checks and evidence generation

`calibrate.py` evaluates proposed examples against a judge. `grounding_probe.py`
tests three pairs that differ only by an invented material deadline, price, or
income claim. `execution_probe.py` separates truthful historical reports and
text-only completion from fabricated external execution. `holdout_controls.py`
constructs fresh scheduling and third-party access controls for candidate 0.4.
Proposed labels are **not human gold**.

Swapping a response between contexts does not automatically imply failure.
`calibrate --swap-run RUN --swap-labels FILE` requires a complete JSON list with
`episode_id`, `source_answer_sha256` (the fingerprint of the frozen answer record),
`expected_success`, and `reason`. Valid solution sets can overlap, and an incorrect
base answer may remain incorrect under irrelevant changes. Do not infer causal
history use from pair correctness alone.

`generation_probe.py` runs fresh production fragment generation, blind recovery,
and strict admission for three declared diagnostic clusters.
`generation_alignment.py` separately assesses full-claim support on those frozen
recoveries, including clusters that failed implicitness. Neither trial estimates
population acceptance or changes the production gate.

## Human review and calibration

Export historical packets with their frozen protocol code so capability-policy
changes cannot alter the episode a reviewer sees. The retained 0.3 packets were
exported this way and record the frozen code hashes.

Export case and answer packets separately from all private mappings and model
judgments. `--split heldout` works for both packet commands.

```bash
python3 -m type5_protocol.experiment packet --workdir STUDY --run human_packet
python3 -m type5_protocol.human_packets --workdir STUDY --runs RUN_A RUN_B
python3 -m type5_protocol.human_validation --packet STUDY/human_review/development/blind_cases.json --kind cases --output case_ratings_template.json
python3 -m type5_protocol.human_validation --packet STUDY/human_review/development/blind_answers.json --kind answers --output answer_ratings_template.json
```

Give each reviewer a separate copy. A completed submission requires a named human
reviewer, the exact packet fingerprint, and reasons. Case approval also requires
independently stated supported facts and acceptable responses. Intended task
uncertainty can be valid; `material_ambiguities` records unresolved defects in case
interpretation, not every unknown that a targeted clarification would resolve.

```bash
python3 -m type5_protocol.human_validation --packet PACKET --kind cases --reviews reviewer_one.json reviewer_two.json --output case_reference.json
```

Disagreement, missing review, and indeterminate ratings remain unresolved. For
adjudication, supply `--adjudication FILE`; it uses the submission schema plus
`source_reviews_sha256` matching the exact two independent submissions.
Adjudication cannot substitute for a missing independent review or silently
replace agreement. Output files are immutable; revisions need new filenames.

After adjudicating both case and answer packets, run:

```bash
python3 -m type5_protocol.human_report --workdir STUDY --run RUN --case-reference case_reference.json --answer-reference answer_reference.json --output judge_error_report.json
```

The report measures judge false acceptance/rejection only on human-adjudicated
valid cases, with explicit exclusions and persona-cluster uncertainty. Degenerate
or single-persona bootstrap samples do not yield a confidence interval. Empty
human templates never count as validation.

## Verification

```bash
python3 -m unittest type5_protocol.test_protocol type5_protocol.test_experiment type5_protocol.test_validation type5_protocol.test_policy_study step4_app_log_synthesizer.test_evidence_alignment
python3 -m type5_protocol.audit_artifacts STUDY
```

Also run the root pipeline, legacy/contract scoring, repeated-run, and decoy tests
before integration. All work remains local. Publication requires human validity
and judge calibration; neither unit tests nor agreement between model judges is
a substitute.
