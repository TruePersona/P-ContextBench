# T5 foundation and validation findings

September 23, 2026. Local branch `codex/t5-protocol-validation`, based on
`7ce81183ff7de71b635548a2fce466ebc6970223`. Candidate protocol **0.4**.
No commit, push, merge, corpus regeneration, or published-score replacement.
The subsequent public-retrieval implementation and 180-row comparison are in
[POLICY_EXPERIMENT.md](POLICY_EXPERIMENT.md).

## Decision

T5 should measure **whether personal evidence changes help appropriately**:
given a current request and app history, use the relevant evidence, make useful
progress, and respect current intent and established authority. Successful behavior
can be a concrete recommendation, a draft, a targeted question, or deliberate
non-use of irrelevant personal information. A caution phrase or action label is
insufficient.

Keep the candidate response protocol separate from the published scorer until
human case adjudication and judge calibration are complete. The local code and
automated experiments support the design, but do not establish a validated
population benchmark. Two model judges agreeing with proposed labels is not an
independent human reference.

The most important change is the evidence chain:

**Persona construction → visible evidence → justified belief → necessary response
requirements → observed response.** Each transition must be checked separately.
A fact assigned to a synthetic persona is not automatically recoverable, relevant,
current, or sufficient to prohibit an action. The request can revise a preference;
it cannot establish another person's permission merely by asking.

## What was wrong at the foundation

The original corpus audit found 1,357 eligible T5 cases out of 1,463, with no
materialized decision contracts. Of those eligible cases, 423 used relative-time
requests and 502 involved calendar reasoning, without a request timestamp.
Thirty exposed subtype information in the public type value, fourteen exposed
risk categories, and all 100 corpus metadata blocks exposed capstone construction
information. The public serializer now uses an allowlist and normalized types.

The evidence audit found 138 unmatched fact references among 3,082 unique T5
references, affecting 171 eligible cases across 78 personas. These are provenance
gaps, **not proof that the corresponding information is absent from every log**.
The old strict gate could accept unrelated recovered candidates without proving
that the intended claims were recovered. Full-claim alignment now follows a frozen
blind recovery, with source quotations and bindings to facts, recovery, and visible
fragments. Old strict traces lacking those bindings are regenerated on resume.

Historical partial-credit scoring could give a privacy failure two-thirds credit.
The candidate requires all necessary conditions, so success cannot compensate for
a decisive failure. Known violations establish failure even if another condition
is uncertain; otherwise unresolved evaluation remains visible in lower/upper
bounds. All obligations are mandatory. `critical: false` only changes severity
reporting.

The experiments found additional problems that code-only examples did not expose:

| Failure | Correction and practical effect |
|---|---|
| A correct central decision accompanied by invented dates, funds, or conditions | Whole-response grounding is mandatory. Required-fact recall alone cannot earn success. |
| A truthful historical action mistaken for new assistant execution | Attribute actions to actor and time. Historical reports, text completion, and quoted drafts are allowed; fabricated new external actions fail. |
| Redundant confirmation counted as a critical authority violation | Assess unnecessary intervention under progress. Exceeding authority is a separate check. |
| A private draft treated as equivalent to disclosure | State the requested decision and authority explicitly; distinguish preparing text from committing to send it. |
| Reviewers rejected missing case-specific safeguards already enforced globally | Alignment and family reviews now receive the complete common scoring policy. Blind interpretation remains independent of the proposed contract. |
| Reviewers treated `critical: false` as optional, or editorial suggestions as defects | The current profile states conjunctive semantics and requires a concrete wrongly accepted/rejected response for material objections. |
| Straight versus curly apostrophes exhausted quotation repairs | Match only quote typography, preserve raw output, and record the exact source span. Changes to words, numbers, negation, spacing, and dashes still fail. |
| Concurrent identical diagnostic calls overwrote their shared cache record | A per-key process lock preserves one frozen response. Raw-call audits detect disagreement with saved judgments. |

These fixes improve measurement validity. They are not attempts to force a chosen
accuracy range or make models pass.

## Broader construction experiment

Twenty-four proposed families were constructed from twelve source personas. Each
family has a base, a decisive-context contrast, and an irrelevant control: 72
episodes. Sixteen families/eight personas were development; eight families/four
different personas were held out. The construction targets spanned all eight
legacy subtype labels. Adaptation and exclusion mean this is **not evidence of
complete construct coverage** in the admitted set.

All construction/review stages are retained. A review profile was revised before
answering to distinguish material defects from editorial notes. One case-quality
repair pass followed; it used case reviews, not answerer performance. Three
technical review recoveries in the earlier stage are documented, including use
of the constructor model for those reviews. That is not independent cross-model
validation.

| Stage | Individual base/contrast approvals | Family approvals |
|---|---:|---:|
| Initial material review | 14/48 | 17/24 |
| After one case-quality repair | 28/47 completed; one technical error | 24/24 |
| Fully bound admission | **8/24 families**, 24 episodes | Both individual and family checks required |

The admitted set contains six development families across four personas and two
held-out families across two other personas. Rejected families and missing reviews
remain in the construction denominator. Family coherence alone did not establish
individual case validity. Some rejection reasons were themselves mistaken, so
8/24 measures admission under this screen, not the true proportion of valid cases.

Common proposal defects included stale relative dates, incomplete changes across
counterfactual variants, preferences strengthened into prohibitions, unsupported
permission requirements, and exclusion of reasonable alternatives. Case production
is a major bottleneck; changing the final scorer alone cannot solve it.

## Frozen 0.3 response results

These results retain their original prompts, public policies, and frozen code.
They are GPT-5.5 judgments conditional on model-screened admission, not human
accuracy or representative PersonaBench performance.

| Condition | Case successes | Complete families |
|---|---:|---:|
| Development, Haiku 4.5, compact full history | 8/18 | 0/6 |
| Development, Sonnet 4.6, compact full history | 13/18 | 2/6 |
| Development, Haiku, relevant excerpts | 14/18 | 4/6 |
| Development, Haiku, explicit supported facts | 12/18 | 3/6 |
| Held-out, Haiku, compact full history | 2/6 | 0/2 |
| Held-out, independent second Haiku draw | 2/6 | 0/2 |
| Held-out, Sonnet, compact full history | 3/6 | 1/2 |
| Generic caution / always clarify / always confirm | 0/18 each | 0/6 each |

All 150 answer/judgment records in this study pass the raw-artifact binding audit.
Relevant-excerpt and fact conditions each contain only twelve distinct answer
calls for eighteen rows because base/control inputs collapse. These are privileged
diagnostics, not retrieval-system evaluations or eighteen independent draws.
The no-history condition scored 4/6 under its own available-information rubric;
subtracting it from full-history success would not measure personalization gain.

**The held-out result exposed a scoring/case defect.** F17's task state broadly
banned reporting completed real-world actions. Sonnet's supported statement that
an alarm was already set was then penalized as fabricated execution. Other F17
answers introduced genuinely unsupported medication-preparation details or
contradictory timing. These failures must not be collapsed into one category.
F17 needs case adjudication; the table is a historical observation, not a clean
held-out accuracy claim. These exposed cases cannot be fresh tests for 0.4.

## Context transfer and targeted controls

The complete-history transfer retained every visible original message and calendar
event for two personas: 2,032 messages/68 events and 1,755 messages/69 events.
The resulting public inputs were approximately 325,522 and 275,465 characters.
No history was truncated. Constructed current updates and the timezone assumption
are explicit; this is transfer of constructed decisions into real corpus histories,
not evaluation of the original T5 questions.

Under 0.2, Sonnet passed 6/6; Haiku had five passes and one quotation error, while
a second judge passed the same Haiku answers 6/6. Adding whole-response grounding
under 0.3 reduced both frozen answer sets to 4/6. The newly detected problems
included an invented booking deadline, an incorrect day-count buffer, and treating
a past Tuesday paycheck as future. One rejection concerning an unstated remaining
balance may be overly strict and is marked for adjudication. No ranking follows.

A separate six-episode challenge tested selective non-use of private calendar
details and unresolved versus resolved recipient identity. Haiku passed 6/6 and
Sonnet 3/6 under 0.3. The latter judgments flagged an overlapping appointment,
an unsupported relationship claim, and a wrong key location. These are additional
small diagnostic observations, not prevalence estimates.

| Judge probe | Observed agreement with authored proposals |
|---|---|
| Broad 0.3 examples, GPT-5.5 | 23/24; one rejection of a proposed valid answer |
| Same examples, Sonnet | 20/20 resolved; four quotation errors out of 24 intended |
| Correct answer versus added invented deadline/price/income | Both judges 6/6 |
| Eight execution/grounding attribution controls, old criterion | GPT 7/8; Sonnet 6/8 |
| Same attribution controls, actor/time criterion adopted in 0.4 | Both judges 8/8 |

These labels remain proposals. The probes support the specific corrections but
cannot estimate judge error against human truth.

## Fresh 0.4 validation

Two new fictional control personas were authored before any answerer output:
one for scheduling and established historical reservations, one for owner-controlled
guest access and readiness to send a draft. They are six fresh control episodes,
not a source-derived population holdout.

Two documented pre-answer revisions clarified drafting versus sending and repaired
a missing readiness requirement. Review also exposed the omission of common checks
from reviewer inputs. All earlier reviews are preserved. The final four individual
reviews and both family reviews passed before data, prompts, and six core source
files were frozen. No performance-driven revision is permitted within that run.

Both Haiku 4.5 and Sonnet 4.6 passed **6/6 episodes and 2/2 complete families**
under GPT-5.5 judging, with no unresolved evaluations. Both GPT-5.5 and Sonnet
agreed with **8/8 authored valid/invalid response labels**. All twelve actual
answer/judgment records pass the raw-artifact audit, and the freeze remained
unchanged. These results support the narrow control behaviors, not broad accuracy.

Mechanical revalidation of the historical quotation failures found three examples
whose failed calls differ only in quote typography. The fourth also adds a closing
quote that is not at that position in the answer; it correctly remains invalid
under the new matcher. No historical semantic judgments or scores were rewritten.

## Fresh evidence-generation experiment

Three declared source clusters were generated once through the actual production
generation and blind-verification functions. All three failed the strict
implicitness gate; there were no transport errors. Post hoc full-claim alignment
of the frozen recoveries found **3 supported, 3 ambiguous, and 2 unsupported**
claims among eight intended claims.

For example, routine stretching can support soreness management without proving
absence of chronic illness; meal preparation does not automatically establish a
health motivation. The diagnostic did not override the strict gate. Three clusters
do not estimate population yield, and final filler assembly was not tested.

The design consequence is to separate **evidence validity from difficulty**.
T5 should require the operational facts needed for a decision. Explicit permission
can be valid even when easy to read. If only a narrower claim is supported, name
and review that narrower claim; do not call it recovery of the full registry fact.
The strict production gate remains a fidelity check, not the T5 admission policy.

## What is ready, and what still needs validation

| Gate | Status |
|---|---|
| Public-input isolation, provenance, chronology, non-compensatory aggregation, missing-case accounting | Implemented and regression-tested |
| Frozen manifests, genuine replication, cache locking, raw-call integrity | Implemented; historical cache mismatch retained and disclosed |
| Controlled decision contrasts, irrelevant controls, static baselines | Exercised in real model runs |
| Full-history transfer | Exercised on two personas; limited coverage |
| Fresh fragment generation and full-claim support | Exercised on three clusters; insufficient to establish production yield |
| Independent human case validity and accepted alternative responses | **Outstanding**; blinded packets and submission/adjudication tools prepared |
| Judge false acceptance/rejection against human references | **Outstanding**; proposed-label agreement is insufficient |
| Broad native-corpus coverage and publication-level precision | **Outstanding**; the admitted pilot is small and selected |

The appropriate next release is a small, explicitly curated T5 response track
whose primary reference is independently adjudicated human judgment. Keep automated
judge results diagnostic until calibration justifies their use. Register an
acceptable judge-error budget and sampling plan before collecting a fresh test;
do not select them after observing favorable scores. Expand by context role—useful
accommodation, real conflict, legitimate revision, material uncertainty, irrelevant
context, and authority—rather than optimizing the legacy subtype balance.

Keep actual tool execution as a separate future track with observable environment
state and action outcomes. Current text-only experiments cannot substantiate claims
about executing purchases, sending messages, persistent memory, or deployed safety.

## Artifacts and reproducibility

[PROTOCOL.md](PROTOCOL.md) defines the candidate semantics and gates.
[README.md](README.md) gives reproduction commands.
[EXPERIMENTS.md](EXPERIMENTS.md) preserves the earlier 0.2 milestone.
[The result snapshot](results/followup_2026_09_23.json) retains data, reviews, manifests,
results, source snapshots, and explicit limitations without replacing the earlier
`results/pilot_2026_09_23.json`.

Complete raw CLI calls and immutable study revisions remain under
`_orchestration/type5_protocol/`. The broad 0.3 human packets were exported with
the original frozen public serializer: later capability changes do not alter the
episode a reviewer sees. Packet mappings and model judgments are private to the
evaluation coordinator. Templates contain no human ratings.

Review-ready local files:

- [Fresh 0.4 cases](../_orchestration/type5_protocol/holdout_controls_v4_final/human_review/heldout/blind_cases.md)
  and [responses](../_orchestration/type5_protocol/holdout_controls_v4_final/human_review/heldout/blind_answers.md).
- [Case submission template](../_orchestration/type5_protocol/holdout_controls_v4_final/human_review/heldout/cases_ratings_template.json)
  and [response submission template](../_orchestration/type5_protocol/holdout_controls_v4_final/human_review/heldout/answers_ratings_template.json).
- [Broader 0.3 development cases](../_orchestration/type5_protocol/expanded_admitted_v3/human_review/development/blind_cases.md)
  and [held-out cases](../_orchestration/type5_protocol/expanded_admitted_v3/human_review/heldout/blind_cases.md),
  with matching response packets and templates in the same directories.

The only historical raw-call mismatch is
`curated_v2/runs/haiku_relevant_v2/judgments/D01-base.json`. Its original 6/6
diagnostic summary is not integrity-validated; the ordinary-text primary runs were
unaffected. Repaired caching prevents recurrence without rewriting that evidence.

This phase finished with 173 passing tests. The subsequent policy study expands
the suite to 201 tests and clears the remaining lint findings in changed files.
The portable snapshot also verifies 186 saved score computations under their
original scoring versions and lossless reconstruction of compressed histories.
All study conclusions remain subject to the validity limits above.
