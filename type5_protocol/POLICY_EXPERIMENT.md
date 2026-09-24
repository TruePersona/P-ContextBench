# T5 public-context policy experiment

This study applies the [Meta-Harness approach](https://arxiv.org/pdf/2603.28052)
to evidence selection around a fixed answerer. The T5 evaluator stays separate
and unchanged. This is an engineering development study, not a publication
validation or a test on fresh personas.

## What changed

`context_policy.py` accepts only public episode fields and returns complete,
verbatim log spans. A trusted renderer preserves the original speaker, time,
source ID, and text. Request, task state, clock, timezone, and capabilities are
always included. No contract, family label, subtype, target action, or private
fact identifier reaches the selector or answering prompt.

The three registered policies are:

| Policy | Evidence handling |
|---|---|
| Full | Complete original history; unbounded baseline |
| Lexical | BM25-style ranking over request/task-state terms; 12,000 serialized log characters |
| Linked | Same lexical ranking, reserving one third of that budget for recent records sharing at least two informative terms with top anchors |

Linked retrieval is a lexical heuristic. It is not a semantic entity resolver,
contradiction detector, or guarantee that every update will be found. It retains
original statements instead of rewriting preferences, permissions, or uncertainty.
Neither retriever splits a log record. Oversized records may consequently be
omitted; omission remains an answer-system failure under the complete rubric.

`policy_study.py` registers the cases, candidate lineage/hypotheses, code and
dependencies, prompts, models, budgets, replicates, and scoring rules before
answer collection. It records selected and omitted sources, exact prompts and
responses, all judge attempts, usage, latency, errors, and paired criterion changes.
Artifacts bind back to the original source episode and raw calls. Successful
judgments cannot be rerolled. Missing and failed evaluations stay in denominators.

The judge always sees the original **complete** public episode and frozen
contract, regardless of retrieval omissions. It receives no policy identifier.
The earlier six-file protocol 0.4 freeze is unchanged. The published Step 6
scorer is not replaced by this research module.

Only reviewed built-in policies execute. This is not an OS sandbox for arbitrary
generated programs. Autonomous code search must wait for a separate isolated
executor, development-data permissions, and a budgeted inference broker.

## Registered population and admission

The proposed set contains 18 episodes in six families: complete-history schedule
and budget scenarios, selective non-use and recipient-resolution challenges, and
schedule/owner-permission regression controls. All families had already been
inspected in earlier work. Former holdouts are explicitly development cases here.

Every family received a fresh material-v3 review under current capabilities.
One pre-answer construction revision removed unnecessary explanation/identifier
requirements and placed an explicit owner-access decision after the code details,
eliminating ambiguity about whether a later code message supplied permission.
The original datasets, rejected reviews, revisions, and raw calls are preserved.
No answerer results were used in that revision.

Five families passed the final screen: D02, X01, X02, H01, and H02, totaling 15
episodes across five persona identities. D01 remained excluded because its
review questioned whether the contract sufficiently enforced warm-up order and
the single-workout constraint. That rejection is a model review judgment, not
human proof of invalidity. There was no further semantic repair or acceptance
reroll in this study.

Only **one admitted family, D02, has a long history**: 797 original/constructed
records, approximately 274,546 serialized log characters per variant. The twelve
short episodes fit within either retrieval budget, so their answering inputs are
identical across policies. They provide regression controls; they do not supply
twelve independent tests of retrieval quality.

## Evaluation settings

- Answerers: `claude-haiku-4-5-20251001` and `claude-sonnet-4-6`, low effort.
- Judge: `gpt-5.5`, high effort, unchanged protocol 0.4 prompt and common checks.
- Three policies, two independently keyed replicates per answerer, fifteen cases:
  180 registered case-policy rows.
- Registered ceiling: 180 answer calls and 540 judge calls, including at most two
  syntax/quotation repairs per initial judgment. No behavioral rerolls.
- Identical prompts within a replicate share cached calls. A new run label alone
  does not create a new draw. Separate replicate IDs change answer and judge
  cache identities.
- CLI transports leave some decoding settings and resolved snapshot identifiers
  unavailable. Usage counters are retained in their provider-native form;
  unreported costs are not treated as zero total cost.

Full history remains the canonical baseline. The registered selection rule
prohibits promoting a policy from this small, exposed, model-judged sample.
Fresh persona/scenario evaluation and independent human calibration are required.

## Results and decision

All 180 registered rows completed, with no unresolved evaluations or artifact
integrity failures. There were 84 distinct answer calls and 96 judge calls,
including twelve schema/quotation repair calls. Case construction/review used
37 distinct calls. Identical short-case inputs account for reuse across arms;
180 rows are not 180 independent answers.

| Answerer | Policy | Case success, first / second draw | Combined cases | Complete families, first / second draw |
|---|---|---|---|---|
| Haiku | Full | 9/15, 12/15 | 21/30 | 2/5, 2/5 |
| Haiku | Lexical | 12/15, 11/15 | 23/30 | 3/5, 2/5 |
| Haiku | Linked | 11/15, 12/15 | 23/30 | 2/5, 2/5 |
| Sonnet | Full | 13/15, 14/15 | 27/30 | 3/5, 4/5 |
| Sonnet | Lexical | 14/15, 14/15 | 28/30 | 4/5, 4/5 |
| Sonnet | Linked | 13/15, 14/15 | 27/30 | 3/5, 4/5 |

The only cases affected by retrieval are the three D02 variants:

| Answerer | Full, first / second draw | Lexical, first / second draw | Linked, first / second draw |
|---|---|---|---|
| Haiku | 0/3, 2/3 | 3/3, 1/3 | 2/3, 2/3 |
| Sonnet | 2/3, 3/3 | 3/3, 3/3 | 2/3, 3/3 |

Both retrievers kept all four contract-cited log IDs in every D02 variant.
Lexical selected 19 records / 11,938 serialized log characters; linked selected
21 / 11,950. Each reduced the approximately 274,546-character history by **95.6%**.
Contract-anchor coverage is a private, post-run diagnostic, never a selector
input. It also does not prove that no other omitted detail could matter.

Haiku's first full-history contrast incorrectly approved a $300 deposit despite
only $100 being available, and treated a refund window as an expected incoming
refund. Retrieval corrected the core funding decision. However, retrieved answers
still invented deposit deadlines or asked for balances already supplied. Complete
evidence selection therefore did not ensure a correct final answer.

Critical-violation counts across the two draws were Haiku full 3, lexical 2,
linked 3; Sonnet 0 in every arm. Unnecessary-intervention counts were Haiku full
4, lexical 2, linked 2; Sonnet 1 in every arm. These remain model judgments.

The answer transport reported $4.365 in estimated usage cost across distinct
answer calls, not a subscription invoice. Judge/review monetary costs were
unavailable. Run-level cost summaries include shared calls and must not be added
to estimate total expenditure; the study total deduplicates them. Prefix-cache
effects and fixed run ordering also limit cost comparisons. Actual provider
token counters and latency are retained in the archive.

**Decision:** retain lexical retrieval as the simplest candidate for the next
study; keep full history as the canonical baseline. Linked retrieval did not
establish an advantage over lexical retrieval. Do not claim a validated accuracy
gain: Haiku's lexical improvement reversed in the second draw, only one long-history
persona was tested, and judge calibration is still pending. Adding autonomous
policy search now would risk optimizing evaluation errors.

The next performance study needs fresh personas and scenarios where necessary
evidence, updates, standing instructions, permissions, and irrelevant history
compete for retrieval capacity. Finalize their validity and judge calibration
with independent human references before using final-test results for a claim.
No prompt or evaluator adjustment was made in response to these outcomes.

## Human review

`policy_human_review.py` exports complete public episodes and deduplicated actual
answers, without model/policy identities, proposed contracts, or model judgments.
Private mappings bind every answer to its source run. It also compares each run
to independently adjudicated human references through `human_validation.py`.
The exported packets contain 15 cases and 83 distinct case/answer pairs. No human
ratings have been supplied; blank templates are not validation.

The traces already identify judge decisions worth human review. For example,
Haiku's X02-base first response was penalized for saying it needed recipient
identity "before I can send the message," although the capabilities allow stating
intended actions and the answer subsequently promises a draft. Another X02
response was penalized for the conventional closing "Looking forward to seeing
you then!" These are possible false rejections under the material-grounding rule,
not adjudicated errors. Their original judgments remain unchanged.

## Reproduction

See [README.md](README.md#public-context-policy-experiments) for the commands.
`policy_pilot.py --clarify SOURCE --workdir NEW_DIRECTORY` reproduces this study's
single pre-answer clarification. Preserve SOURCE and complete fresh case/family
review in the new directory before registration. The admitted population may
differ on a new independent model-review draw; report that difference.

The experiment archive retains original cases, construction revisions, reviews,
source code, registration, raw calls, and all outcomes. Its accompanying JSON
comparison is readable without model access. The original pilot and follow-up
archives are preserved separately.

- [Complete study archive](results/context_policy_2026_09_23.json.gz)
- [Audited comparison](results/context_policy_2026_09_23_summary.json)

Verification: 201 tests passed, including 28 policy/isolation/audit/human-review
regressions. Ruff passes on the candidate package and changed production Python
files; `git diff --check` is clean. The previous protocol 0.4 freeze still matches.
Repository-wide Ruff reports 32 pre-existing findings, all in unchanged files.
