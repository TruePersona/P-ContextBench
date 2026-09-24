# Type 5 development results — September 23, 2026

**Historical milestone: candidate 0.2, not a validated benchmark protocol.**
Follow-up work is recorded in [FOLLOWUP.md](FOLLOWUP.md). A later raw-artifact audit
found one overwritten judgment in `haiku_relevant_v2`; its original 6/6 report
is not an integrity-validated result. The ordinary-text primary runs were unaffected. Work is local on
`codex/t5-protocol-validation`, based on `7ce8118`. No corpus regeneration, push,
or merge was performed. The implementation, experiments, and limitations are
separate from historical PersonaBench scores.

## What the experiments establish

The new scoring path can distinguish a decision supported by the available
context from generic caution, redundant confirmation, a decision appropriate to
another context, and an answer that acknowledges a constraint but subsequently
violates it. It evaluates the actual response using necessary conditions for
context, progress, and boundaries. There is no compensating partial-credit total.

This is an engineering result on **two constructed families, two personas, six
episodes**. The cases concern an objectively feasible workout schedule and an
adequately funded travel deposit. Their current dates, amounts, and task states
are explicitly constructed; they are not new facts recovered from the original
personas. Each family has a base, a decisive-context contrast, and an irrelevant
control. Model reviews approved the four base/contrast contracts and both families.
Human validity judgments are still missing.

## Recorded results

The final ordinary-text runs use GPT-5.5 as judge. Their frozen manifests include
dataset, public-input, prompt, common-check, and core-code hashes.

| Experiment | Observed result | Interpretation |
|---|---|---|
| Haiku 4.5, full compact history | 6/6 successful; 2/2 families | Feasibility check on these cases |
| Sonnet 4.6, full compact history | 6/6 successful; 2/2 families | Same small feasibility check |
| Independent second Haiku draw | 6/6 successful; 2/2 families | One repeated draw, not six new independent scenarios |
| Generic caution | 0/6 successful | Caution without completing the task does not earn a pass |
| Always clarify | 0/6 successful; zero critical violations | Unnecessary questioning is a progress failure |
| Always confirm | 0/6 successful; zero critical violations | Redundant confirmation is a progress failure |
| Swap base/contrast answers | All 4 fail in the other decisive context | The scored decision depends on the context |
| Reuse base answers under irrelevant changes | Both remain valid | The proposed irrelevant controls are inert for these answers |
| GPT-5.5 judge stress test | Agrees with 8/8 authored labels | Includes alternative correct answers and plausible failures |
| Sonnet 4.6 judge stress test | Agrees with the same 8/8 labels | Cross-model agreement, not human calibration |
| Semantic evidence-alignment stress test | 4/4 expected gate decisions | Accepts full recovery; rejects unrelated recovery, diagnostic overreach, and permission-scope expansion |

The eight calibration labels are proposals. Agreement from two judges does not
turn them into sixteen independent human-labeled examples. The four alignment
tests use constructed frozen recoveries; they test the alignment component, not
end-to-end implicit-log generation.

Earlier diagnostic runs used JSON-wrapped answers. Within that prompt condition,
Haiku scored 6/6 with full compact history, 6/6 with relevant excerpts, and 5/6
with explicit facts. Relevant/fact conditions have only **four distinct public
inputs** because removing distractors makes base/control inputs identical; their
cached answers must not be counted as independent draws. These are privileged
diagnostics, not evaluated retrieval methods.

The no-history diagnostic scored 1/2 under its own available-information rubric.
Its scheduling answer failed because it asserted feasibility without knowing the
call time, not because it lacked private history. This score cannot be subtracted
from full-history success to estimate a personalization gain.

No population accuracy or model ranking is supported. Both independent-persona
count and scenario diversity are too small. Degenerate bootstrap distributions
no longer produce apparently certain `[1, 1]` or `[0, 0]` intervals.

## Problems found and corrected

**Overlapping criteria inflated critical violations.** Candidate 0.1 included
redundant confirmation in the authorization check. All twelve always-clarify and
always-confirm responses consequently appeared to violate a critical boundary.
Candidate 0.2 restricts authorization to exceeding authority and assesses
unnecessary intervention under progress. Rejudging the frozen responses preserves
all twelve task failures while removing all twelve false critical classifications.
The original results remain available; they were not overwritten.

**A correct warning did not make the whole answer correct.** In the explicit-fact
condition, an actual answer identified a $200 funding gap, then proposed covering
it with credit. The judge detected the contradiction and the unfunded commitment.
This is why observing a caution phrase or the right action label is insufficient.

**Automatic adaptation produced unsupported keys.** Two generated health/workout
families passed a joint family review, but their four individual variants failed
the independent evidence/contract screen. Problems included applying a March
event to an April request without establishing continuity, strengthening ordinary
habits into restrictions, and narrowing acceptable alternatives without support.
These are findings about the constructed proposals, not an estimate of the error
rate in the original corpus. Some screening objections also require adjudication;
the reviewer is not an oracle. The proposals were withheld from performance scoring.

**The evidence validator initially ignored legitimate public sources.** Blind
review may cite the current request, task state, or capability policy as well as
logs. All such quotations now require an exact match to their identified source.

**Answer formatting obscured behavior.** One Sonnet JSON-answer record failed to
parse. It remained unresolved in the denominator instead of disappearing. The
answerer now returns ordinary text; only judge/review observations require JSON.
Both models were rerun across the entire pilot under new run IDs. The old malformed
response and original outcome remain recorded.

**Caching is not replication.** An explicit replicate ID now requests a separate
answering draw without adding that ID to the model's input. New run names alone
reuse cached responses. An interrupted repeat run was preserved when the new
code-binding check detected a changed manifest; its already-generated responses
were subsequently evaluated under a new frozen run, without selecting new answers.

## Local implementation

- Public inputs use explicit allowlists. Step 6 no longer exposes risk categories,
  capstone metadata, or subtype values hidden in the type field. The blind fragment
  reader also strips new private annotations, including nested fields.
- Strict fact recovery requires a subsequent semantic comparison of every full
  intended claim with frozen blind recovery and quoted visible evidence. A topic
  match is insufficient. Acceptance and resume are bound to the exact facts,
  recovery, alignment, and public fragments; resume reapplies the complete gate.
- Cases specify clocks, current task state, available capabilities, evidence
  anchors, and justified obligations. Private contracts never reach the answerer.
- Case success is a conjunction. Dimensions remain diagnostics. Evaluation
  uncertainty and missing/invalid results stay visible as bounds over the intended
  population. Known failure still establishes failure when another criterion is
  uncertain.
- Case/family review provenance, condition reuse, split overlap, exact quotations,
  counterfactual controls, held-out freezes, and independent replicate calls have
  mechanical checks. A changed held-out dataset or core implementation requires a
  new study revision.

The existing production scoring path is not replaced by this experimental runner.
The stricter generation gate is locally implemented and component-tested; its cost,
acceptance rate, and end-to-end corpus quality still need evaluation. If an intended
clinical or psychological label cannot be identified from evidence, the remedy is
to narrow the observable claim or exclude it—not to keep regenerating until a
verifier confidently guesses the label. Explicit permissions and current task
facts must also remain distinct from implicitly inferred background preferences.

## Required next validation

1. Obtain independent judgments from two humans on the six public cases and the
   twenty blinded response examples. Freeze those judgments before showing the
   proposed contracts and model assessments; adjudicate substantive disagreement.
   This establishes an initial human reference before scaling automatic construction.
2. Expand to the registered 24 families / 12 personas. Add positive cases requiring
   clarification, selective non-use, legitimate preference changes, scoped consent,
   ambiguity, pressure, and indirect multi-log evidence. The current easy planning
   and funding cases cannot substitute for these constructs.
3. Run complete-log transfer with native source chronology, all relevant distractors,
   and renewed case review. Adding large logs can change what is knowable and which
   actions are justified; a compact-case contract cannot simply be assumed valid.
4. Measure judge false acceptance and false rejection against adjudicated human
   references, with independent-persona/family uncertainty and enough examples to
   support the desired error tolerance. Neither unit tests nor eight agreements
   establish a low judge error rate.
5. Freeze the study and evaluate the persona-disjoint held-out set, repeated draws,
   and multiple answerers. Report failures and unresolved cases without tuning to
   a target accuracy. Only then consider integrating a new benchmark protocol.

## Evidence and checks

Local raw artifacts: `_orchestration/type5_protocol/`. The admitted study is under
`curated_v2/`; prior proposals and revisions are preserved separately. The portable
[pilot snapshot](results/pilot_2026_09_23.json) contains the case data, selected run
manifests, responses, judgments, reviews, stress tests, and code hashes.

The blinded human packets are `curated_v2/human_review/development/blind_cases.md`
and `blind_answers.md`, with JSON templates. Keep private mappings and model
judgments separate during independent review.

Verification: **151 unit tests passed**, including the root pipeline, legacy and
contract scorers, repeated-run handling, decoy checks, new protocol, and evidence
alignment. New modules pass Ruff; four remaining warnings in older files were
also present on main. No held-out evaluation, human calibration, or complete-log
transfer result is claimed.
