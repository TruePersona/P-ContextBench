# Pipeline validation record

Checks recorded on September 23, 2026. This validates execution and admission
controls; it does not certify the semantic validity of the benchmark.

## Automated checks

- **235 tests pass**, including all six stage implementations with only inference
  transport replaced by 13 deterministic synthetic responses. The fixture has
  109 interview records, five relationships, two supporting fragments, one fact,
  and one Type 1 case. It exercises schema and lineage boundaries rather than
  realistic persona generation or benchmark coverage.
- Repository-wide `ruff check .`, `git diff --check`, and dependency compatibility
  checks pass with the pinned development requirements.
- Regression coverage includes missing canonical outputs, incomplete reviews,
  fabricated evidence quotes, public/private prompt separation, changed input
  files, stale answer reuse, missing-answer credit, incompatible or duplicate
  reliability runs, rescoring, raw-call retention, and concurrent output locks.
- The earlier protocol 0.4 freeze and all nine policy-study source snapshots
  match the current research implementation. Freeze hashes use that study's
  canonical JSON encoding; they are not raw-file SHA256 values.
- The tracked `data_samples/` corpus is unchanged.

Run the same suite with the command in the root README. CI runs it on Python
3.10 and 3.13; local checks used the recorded Python runtime in the evidence
summary. Dependency pins cover direct packages, not a complete environment lock.

## Bounded live test

The synthetic source artifacts from the offline fixture were reused for a live
case review and two independent answering/scoring runs:

| Role | Backend/model | Calls |
|---|---|---:|
| Public-only case assessment | Claude CLI / `claude-sonnet-4-6` | 1 |
| Private-key alignment review | Claude CLI / `claude-sonnet-4-6` | 1 |
| Answering | Claude CLI / `claude-haiku-4-5-20251001` | 2 |
| Scoring | Codex CLI / `gpt-5.5` | 2 |

All six calls returned usable JSON. Both answers received full credit on the
single Type 1 fixture, and strict Pass^2 aggregation accepted their distinct
call identities. Outputs are explicitly marked `smoke_test`. This is neither a
live generation test of all six stages nor an estimate of model accuracy or T5
validity.

After the final scoring changes, two fresh answer calls and two fresh judge
calls repeated the same successful bound Pass^2 check. The evidence records
both runs and their source snapshots; the repeat did not reuse prior answers.

An earlier answering attempt returned a coding-assistant refusal instead of
JSON. Its raw response remains in the archive. Giving the CLI an explicit
text-inference system prompt resolved that observed failure. Code snapshots
identify the implementation at each call. The first live run predates the API
compatibility fix and expanded runtime/source snapshots; the final scoring
repeat includes those changes. All final source changes passed the offline suite.

The installed Anthropic SDK rejected the old `temperature` argument before
making a request. The transport now omits it and records provider-default
temperature as unavailable rather than claiming deterministic decoding. The
next API attempt reached the service but returned **401 invalid API key**.
Successful live API inference therefore remains unverified. Unit tests cover
the installed SDK's request shape, usage capture, truncation handling, and the
OpenAI request's system instruction and completion budget.

[Evidence summary](results/live_smoke_2026_09_23_summary.json) lists call identities,
statuses, and file hashes. The accompanying compressed JSON archive retains
synthetic source artifacts, source snapshots, exact prompts, raw responses,
errors, and manifests. Both failed and successful attempts are retained.
Extracted paths are relative to the smoke workspace; original manifest paths
remain recorded as executed. No API credential is included.

## Prompt output examples

These examples illustrate acceptance behavior, not a controlled accuracy
comparison. T5 prompt examples are recorded separately in
[PROMPT_EXAMPLES.md](../type5_protocol/PROMPT_EXAMPLES.md).

**Case verification.** Previously, an empty `{}` review of non-contract cases
could pass because missing rejection counts and coverage deficits defaulted to
zero/empty. It now fails before admission: every case needs a public assessment
and a complete private review with consistent criterion verdicts.

For the live fixture, the public question is `When does Alex run?`. The answerer
and public reviewer receive the two messages `Finished my morning run before
breakfast again.` with their original dates and speakers. The private fact label
and behavior contract are absent. The new public assessment included:

```json
{
  "test_case_id": "TC-1",
  "answerability": "supported",
  "answer": "Alex runs in the morning, before breakfast, finishing by around 7:00 AM on at least two consecutive days (March 1 and March 2, 2026).",
  "supporting_quotes": [
    "Finished my morning run before breakfast again.",
    "Finished my morning run before breakfast again."
  ],
  "limitations": "The history shows a consistent pattern on two mornings, but does not confirm this is Alex's permanent routine. The exact start time of the run is not stated, only the finish time inferred from the 07:00 message timestamps."
}
```

The subsequent private review returned `public_evidence_check: PASS`; code
checked the quotes and bound the original case, complete review, and history.
The timestamp interpretation is still a model judgment, not established by
the structural checks. Human review remains necessary for semantic calibration.

**Answering layout.** Previously, a single prompt could include every question,
letting later questions reveal context for earlier ones. The default now asks
each question separately against the same public history, returning one answer
record for that question. Explicit batch layout remains available and has a
different run identity. This change prevents cross-question exposure; its
accuracy/cost effect has not been measured across the corpus.

**Scoring evidence.** Previously, the judge relied on private keys and selected
fragments. It now also receives complete public history. This makes omitted
updates and contradictions available to review; it does not guarantee the
judge recognizes them. Missing answers receive zero credit and an explicit
evaluation error even if a judge supplies a positive verdict.

Previously, a factual judgment such as `CORRECT` with `score_value: 100` could
enter the summary unchecked. Types 1–4 now require the rubric's exact verdict/
score pair. The old instruction to exclude unrecoverable required labels has
also been removed: an invalid or uncertain reference now produces a retained
evaluation error and score bounds, without rerolling the judgment or reducing
the reference requirements.

## Corpus and research limits

The read-only inventory found 4,810 cases in 100 stored sets, 3,744 review records,
1,066 missing individual reviews in 26 sets, and 45 summary/count mismatches.
Of the missing records, 266 are T5. These counts describe stored evidence; they
do not estimate case correctness or justify rewriting historical scores.

The candidate T5 protocol and public-context policies remain separate from the
published scorer. The policy study covers 180 case-policy rows but only five
admitted families, with one long-history family. Human-adjudicated case validity,
judge calibration, fresh-persona transfer, and wider live pipeline coverage are
still required. See [POLICY_EXPERIMENT.md](../type5_protocol/POLICY_EXPERIMENT.md)
for the registered comparison and limitations. Full history remains the baseline.
