# Pipeline integrity

Accepted artifacts must have complete review records, matching source content,
and an auditable execution history. A verifier's summary or a matching filename
is insufficient. These checks apply to standalone stages and `run.py`.

## Execution and provenance

`run.py` writes new outputs under `runs/<seed UUID>/<stage>/`. Standalone stages
default to their own `runs/` directory. The tracked `data_samples/` corpus is an
input collection, not the default output destination. New seed filenames contain
the UUID; existing name-only seed paths remain valid inputs. Dataset fetching is
bound to the commit in `step1_seed.generator.DATASET_REVISION`.

Each invocation stores an immutable directory under
`<output>/.attempts/<stage>/<attempt ID>/`, containing input snapshots, parent
manifests, code snapshots, raw calls, output snapshots, configuration, and status.
Top-level output files are convenient current pointers. Their `.provenance.json`
sidecars bind them to the accepted snapshots. Modifying a file invalidates its
binding. Failed attempts remain available. OS locks prevent concurrent writers
from replacing the same persona's stage outputs and release on interruption.

Calls retain the exact task, transport instructions, raw response, parse status,
timing, and provider usage where available. Unavailable usage remains null.
Subscription CLIs use temporary working directories with tools disabled; Claude
uses an explicit text-inference system prompt and does not inherit an API key.
These settings are operational isolation, not a security sandbox for arbitrary
candidate code. Provider/CLI updates and unreported decoding settings still
limit exact reproducibility.

## Admission across the six stages

| Stage | Required checks |
|---|---|
| Seed | UUID-backed filename, immutable record revision, no conflicting overwrite. |
| Interview | Complete 109-question transcript, matching participant identity, passing review and nonempty canonical profile/fact registry. |
| Social circle | Bound matching interview/profile inputs, passing review and five identified canonical relationships. |
| App history | Bound profile/circle inputs, existing fragment recovery/alignment and assembly checks; resume validates original sources and generation settings. Rejected partial attempts may be used only for explicit reconstruction/resume. |
| Cases | Independent public-only assessment for each isolated question against full history; private alignment review with all seven criteria; complete ID inventory; resolvable source fact IDs; code-computed verdict counts, case count/type coverage and exact source bindings. |
| Evaluation | Complete bound case admission, hidden-key isolation, source-bound answers, frozen intended denominator, full-history judging, compatible distinct repeated calls. |

The public review occurs before private alignment. The alignment reviewer sees
the frozen public assessment and may reject its unsupported conclusions; it
cannot rewrite that assessment and call it blind recovery. Type 4 interpretation
is independently reviewed. Public review and judging both see filler and later
updates. This increases inference cost relative to checking only selected
fragments, and does not substitute for human calibration.

Step 5's accepted cases are reconstructed from the original input by code.
Suggested private-key rewrites do not silently replace accepted cases. Unknown,
duplicate, or missing review IDs, malformed criteria, inconsistent overall
verdicts, fabricated quotes, stale bindings, and missing source IDs fail closed.
Each rejected generation attempt is retained. Re-reviewing an unchanged rejected
dataset cannot select a more favorable verdict through retries.

The ordinary case-count target remains 45–55. Explicit smaller `--min-cases` /
`--max-cases` runs are marked `smoke_test` in admission and scoring outputs; their
scores are execution checks, not benchmark estimates. Other semantic coverage
rules still rely on recorded independent review. Structural validation does not
prove semantic correctness or realistic persona coverage.

## Historical corpus migration

Audit before regeneration:

```bash
python -m pipeline_integrity.audit --output runs/corpus_review_inventory.json
```

The preserved corpus contains 4,810 cases across 100 personas. Its stored review
files lack individual records for 1,066 cases across 26 personas, including 266
T5 cases; 45 files have summary counts that disagree with recorded verdicts.
This measures missing evidence, not the number of incorrect cases. The complete
inventory and source hashes are in `results/corpus_review_inventory.json`.

Use `--allow-legacy-inputs` to explicitly import historical upstream profiles,
circles, or logs after structural checks. It records unbound ancestry and does
**not** bypass complete case admission. To construct newly reviewed cases from
those sources:

```bash
python run.py --persona alicia_gonzalez --start 5 --stop 6 \
  --allow-legacy-inputs --backend codex \
  --model gpt-5.5 --verifier-model gpt-5.4 \
  --evaluator-model gpt-5.4-mini --judge-model gpt-5.4
```

Step 5 also accepts `--review-existing PATH` with a separate `--output` directory
for one review of frozen cases. Existing T5 cases must first satisfy the current
behavior-contract schema; an old label-only key cannot silently become a new
contract. Missing historical reviews are never inferred from summary totals.
Original artifacts and score files retain their historical meaning.

## Reuse, isolation, and reliability

Pass 1 defaults to isolated questions, each with the same complete public
history. This prevents questions from supplying evidence to one another.
`--answering-layout batch` retains the old prompt layout for explicit comparison.
Layout is part of run identity; this change is not a demonstrated accuracy gain.

`--skip-pass1` requires a bound answer file with the same history, questions,
case contents, answer prompt/implementation, model, layout, and configuration.
Missing files and changed inputs fail before inference. A new judge/model or
scoring prompt may rescore the same answers; the original call identity and
earlier result snapshots remain available. Rescoring one answer twice does not
create two independent answering runs.

Pass^k requires compatible run identities and distinct answer calls. Identical
answer text from separately recorded calls is valid. Duplicate files, copied
calls, mixed models, changed cases, and altered scoring implementations are
rejected. Standalone historical aggregation requires `--allow-legacy`; it is
labelled `historical_unbound` and cannot certify independent calls. The existing
metric continues to require success on every run, rather than any-run success.

## Validation and remaining research

The offline suite runs all six implementations while replacing only inference
transport. It also covers the audit's failure modes, unchanged-answer rescoring,
source/answer tampering, public-review isolation, missing-answer credit, and
artifact locks. CI runs the full production and T5 suites plus repository lint.
See `VALIDATION.md` for recorded checks and the bounded live smoke run.

The candidate T5 0.4 protocol and retrieval studies remain separate from the
published scorer. Their frozen code and original experimental records are
preserved. Human-adjudicated validity, balanced controls across fresh personas,
and estimates of judge false acceptance/rejection remain required before
claiming a validated replacement benchmark or a general retrieval improvement.
