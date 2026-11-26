# Engine completion log

A record of the accuracy work on the Aetrix V5.5 correction engine: what was
changed, what was run, what it proved, and what it did not. Dates are session
dates; every test figure below is a command that was actually executed.

## Scope

Two phases:

1. **Defect repair** — nine defects found in an audit of the marking pipeline,
   each fixed with a test that fails without the fix.
2. **Accuracy engineering** — independent verification that does not re-ask the
   same model, cost-aware review modes, page coverage, and preparation for a
   live measurement that the repository could not honestly perform.

The 95% item-accuracy target is **not met and not measurable** with the evidence
this repository holds. It requires a teacher-certified holdout, which is empty
(0 papers). Nothing below claims otherwise.

## Phase 1 — defects repaired

| # | Defect | Fix |
| --- | --- | --- |
| 1 | A reply with a valid mark but auxiliary fields out of range failed the whole schema and became a review item. | The parser clips out-of-range optional fields instead of rejecting the reply (`correction/aetrix/schema.py`). |
| 2 | JSON wrapped in prose ("Here is the marking: {…}") was rejected. | `parse_json_text` extracts the first balanced object. |
| 3 | Prompt v1's example contradicted the rules it stated. | Prompt v2 assets for marking and double check, with one consistent example; `prompts/manifest.json` records the versions. |
| 4 | Re-running a job paid again for a question that already had a second opinion. | `_record_double_check` is idempotent and the pipeline reports `already_checked`. |
| 5 | A second award above the maximum was classified as a disagreement, implying a real mark was in dispute. | Over-maximum second awards are `UNVERIFIABLE`. |
| 6 | A reply truncated by the page limit was presented as a normal award. | `PAGE_LIMIT_TRUNCATED` forces review per row. |
| 7 | A zero award beside an answer the deterministic check proved equivalent was accepted silently. | The contradiction is recorded and forces review. |
| 8 | `latest_job_for_submission` could return a cancelled job. | Cancelled jobs are excluded. |
| 9 | `docs/engine/README.md` claimed a live measurement it did not have. | Corrected to state what the replay measures. |

Verification: the suite went from **611 passed** at the audit baseline to
**648 passed, 1 warning** (340 s, exit 0), `ruff check` clean, against a local
PostgreSQL 16 cluster. The frontend files that changed during that session were
not touched by this work and were not committed.

## Phase 2 — accuracy engineering

### Independent verification (`correction/scheme_check.py`)

The second opinion is no longer only "ask the model again". The approved scheme
is compared with the reply:

- `UNKNOWN_CRITERION` — an award built on a mark point the scheme does not define.
- `MISSING_MARK_POINT` — a scheme mark point the reply never considered (possible
  under-marking).
- `OVER_SCHEME_CAPACITY` — an award larger than the scheme's marks allow.
- `UNMET_DEPENDENCY` — a dependent mark awarded without its prerequisite.
- `SCHEME_ANSWER_DIFFERENT` — the scheme states an answer, the student's answer is
  provably different, and marks were awarded.
- `SCHEME_ANSWER_EQUIVALENT_WITH_ZERO` — the scheme states an answer, the student's
  answer is provably equivalent, and no marks were awarded.

Only unambiguous scheme text is treated as a stated answer (short, contains a
digit, and every alphabetic token is a single letter or a known function), so
"M1 for expanding" never becomes an expression. An `UNKNOWN` comparison produces
no finding. Math findings fire only in the two contradiction directions above, and
every comparison is stored as a `SCHEME_MATHEMATICAL` verification record with the
student expression, expected expression and award.

Two refinements came from measuring the layer on preserved responses, not from
guessing:

- **Code normalisation.** A reply may qualify a point with its question
  (`1a_B1`) or append scheme notation (`M1FT`, `M1_DEP`). Those name the scheme's
  `B1`/`M1`, so the question prefix is stripped and a variant resolves to its base
  code when the scheme defines that base. Without this, one benchmark run flagged
  38 of 38 items on labelling alone.
- **Missing points only when marks are unclaimed.** `MISSING_MARK_POINT` now fires
  only when the award is below the scheme's capacity; a reply that already awarded
  every available mark cannot have withheld one by not naming it.

Measured on the preserved benchmark (228 item decisions across six runs, zero
provider requests): the scheme layer flagged 24 items — **9 of the 20 wrong items
(45%) and 15 of the 208 right ones (7%)**. The deterministic layer caught none of
those 20. Every flag is a review item with the scheme's own statement attached;
no mark is rewritten.

### Review modes (`correction/sampling.py`)

`assignments.review_mode` was stored, validated and never read. It is now read
from the tenant-scoped assignment and resolves to a policy:

| Mode | Second opinions | Confidence threshold | Confident sample | Recovery rounds |
| --- | --- | --- | --- | --- |
| `ECONOMY` | 0 (`NOT_REQUIRED`) | — | 0 | 1 |
| `BALANCED` | `double_check_max_questions` | `double_check_min_confidence` | 0 | 2 |
| `ACCURACY` | `max(double_check_max_questions, 12)` | `max(double_check_min_confidence, 0.95)` | 2 | 3 |

`settings.marking.double_check_enabled` stays authoritative; modes narrow or
widen scope and never enable a disabled double check. Selection is deterministic
(seeded by the job id), so a run's cost is reproducible, and it is ranked by
suspicion: low confidence (4), a normalised award (4), marks beside a blank answer
(3), full marks on a question worth at least three (2), an outstanding scheme
concern (2), past double-check disagreements on the same question (2 each, capped
at two). The reasons travel with the verdict (`detail.selection`) and into the
`DOUBLE_CHECK` engine run.

Measured cost effect on the integration fixture (three questions, one generous
award): ECONOMY 3 provider calls, BALANCED 4, ACCURACY 5 — one request per chosen
question, never more than the budget.

### Page coverage (`correction/page_coverage.py`)

- `MISSING_PAGE` — the document declares pages storage does not hold. **Blocking**:
  the run stops before any provider request, with no rows written.
- `UNMAPPED_PAGE` — a readable page no question is mapped to, when mappings exist.
  Recorded, not blocking.
- `PAGE_LIMIT` — a script longer than the six pages one request carries, with
  questions that are not fully mapped. Recorded; the per-row
  `PAGE_LIMIT_TRUNCATED` concern is what forces review.

### Tests added

- `tests/unit/test_scheme_check.py` (20 tests)
- `tests/unit/test_review_sampling.py` (19 tests)
- `tests/unit/test_page_coverage.py` (10 tests)
  (49 new unit tests in total)
- `tests/integration/test_correction_pipeline.py` — four new end-to-end tests
  (mode cost table, scheme mismatch → review, missing page → no request, partial
  mapping → recorded) and four updated double-check tests whose expected selection
  changed by design.

### Verification (this phase)

- `ruff check app tests` — clean.
- `pytest tests/unit` — **452 passed**.
- `pytest tests/integration/test_correction_pipeline.py` — **20 passed**.
- `pytest` (full suite, local PostgreSQL 16) — **705 passed, 1 warning in
  416.54 s, exit 0**.

## Phase 3 — verification optimisation, transcription, validation harness

### 1. Scheme findings: attribution, severity, measured before/after

The Phase 2 layer flagged 24 of 228 preserved decisions (9 wrong, 15 right).
Every false positive was traced to one cause: a reply that awarded method marks
and withheld the accuracy mark was judged as if it had awarded the accuracy mark,
so a correct `M1 M1` award was flagged because the final answer (correctly)
did not match. The layer now attributes the comparison to the mark point:

- `DEFINITE_MISMATCH` — an award above the scheme's capacity, a dependent point
  without its prerequisite, or an accuracy mark awarded for an answer the scheme
  says is different. Always reviewed.
- `POSSIBLE_MISMATCH` — notation the scheme does not use, a scheme point nobody
  named while marks were unclaimed, or an accuracy mark withheld although the
  answer is provably equivalent. Reviewed in `BALANCED`/`ACCURACY`, recorded as
  evidence in `ECONOMY`.
- `VERIFIED` / `UNVERIFIABLE` — nothing to dispute, or this build cannot compare.

| Measurement (228 item decisions, 6 preserved runs) | Phase 2 | Phase 3 |
| --- | --- | --- |
| Flags | 24 | **6** |
| Wrong items caught | 9 | 6 |
| Correct items flagged | 15 | **0** |
| Recall | 45% | 30% |
| Precision | 37.5% | **100%** |

Every flagged and every wrong item, with its own cause, is listed in
`experiment/paper01_engine_analysis/root_causes.md` (6 caught, 14 missed, 0 false
alarms, generated from the stored evidence).

Recall fell because three of the old catches were method-mark awards whose
wrongness the scheme cannot see from the final answer. Two new directions did
recover errors: an accuracy mark withheld although the answer is equivalent
(A run3 items 21, 32) and full marks for a wrong answer (item 36 twice). The 14
remaining misses are the blank answers the model could not read (the case
transcription targets), missing dependent method marks, and items where the
reference itself is disputable. No award is ever changed by a finding.

### 2. Page coverage

`assess_coverage` now also reports `PAGE_SEQUENCE` (page numbers contradict the
document's count), `DUPLICATE_PAGE` (the same image twice) and a per-question
`PAGE_LIMIT` (a question mapped to more pages than one request carries).
`MISSING_PAGE` still blocks before any request. The other findings keep the award
and attach a `PAGE_COVERAGE` concern to every stored question, because an
unmapped page can hide the continuation of a mapped question's answer. When every
question has a mapping, an unmapped page is informational: a cover page cannot
hide a marked answer. `PAGE_LIMIT_TRUNCATED` remains per row for the pages a
question could not carry.

### 3. Review modes

- `settings.marking.review_mode` was a second, dead source of truth; the
  assignment remains authoritative and the setting is now the fallback for a row
  that predates modes.
- `ECONOMY` buys no second opinion and no transcription but still runs every
  integrity, scheme and coverage check (proven by an integration test that feeds
  a reply whose components do not sum to its award).
- `experiment/review_modes/compare.py` reproduces the three modes on a fixed
  eight-question paper; on it, ECONOMY spends 9 requests, BALANCED 17, ACCURACY
  21, with the selected questions and reasons written to `comparison.json`.

### 4. Blind independent transcription

New `aetrix_v5_5_transcription:v1` prompt (review model) and
`correction/transcription.py`. The reader receives the pages and the question
only — no award, no scheme, no expected answer, no first conclusion — and copies
what the candidate wrote. Its reading is compared with the first pass:
`AGREES`, `DIFFERS`, `ABSENT` or `UNVERIFIABLE`; a difference raises
`TRANSCRIPTION_DIFFERS`, sends the question to a person and leaves the award and
the original evidence untouched. Selection is deterministic and targets a zero
beside a blank answer first, then incomplete pages, low confidence and existing
scheme doubt. Budget: off by default (`transcription_enabled`), 0 in ECONOMY, 2
in BALANCED, 6 in ACCURACY, capped by `transcription_max_questions`. Each selected
question is exactly one request; the prompt is 1,477 characters (236 words) and
the response is capped at 2,048 output tokens, against a marking prompt of 5,782
characters and a marking cap of 8,192.

### 5. Live validation harness

`experiment/live_validation/evaluate.py` scores stored runs against certified
references and computes item exactness, within-one, mark agreement, paper-total
exactness, absolute paper error, over/under-awarded items and marks, review rate,
review false positives/negatives, wrong items caught, requests, tokens and cost
per paper, plus a paper-level paired bootstrap against a named baseline. It
refuses any reference whose status is not `teacher_certified` (exit 2, no output
file) and never scores a run for a paper without a certified reference. Seven
unit tests pin the refusal and the arithmetic. The holdout still has **0
certified papers**, so no accuracy number is produced.

### 6. Provider cost and reliability

- One question is one request; a decided row is never re-marked (idempotency is
  tested), and the second opinion, transcription and recovery each have an
  explicit budget.
- Retries are bounded by `provider.max_attempts` (4) with exponential backoff up
  to 10 s; a 401 marks the credential invalid, a 429 cools only that key and
  rotates to a sibling (`provider_calls.py`), so quota exhaustion does not park a
  paper the fleet could still mark.
- Prompt v2 is 5,782 characters against v1's 2,590 — about 0.8k extra input
  tokens per request, roughly 30k tokens per 38-question paper. It is not trimmed
  without evidence that the added rules do not earn that cost; the live
  experiment is what would show it.
- `thinking_budget` defaults to 0, so no output budget is spent reasoning, and a
  response too small for the marking schema is rejected rather than retried
  blindly.

### 7. Defect found by this phase

The `verification_results` check constraints only allowed `MATHEMATICAL`,
`INTEGRITY` and `DOUBLE_CHECK`, so the Phase 2 `SCHEME_MATHEMATICAL` record and
the new `TRANSCRIPTION` records could not be stored at all. Migration
`0026_verification_kinds` widens both constraints (kinds and the `SKIPPED`,
`DIFFERS`, `ABSENT` statuses); `models.py` matches it, and the integration suite
runs every migration from zero.

### Verification (Phase 3)

- `ruff check app tests` — clean.
- `pytest tests/unit` — **489 passed**.
- `pytest tests/integration/test_correction_pipeline.py` — **25 passed**.
- Full suite against local PostgreSQL 16, from an empty database with all
  migrations applied — **747 passed, 1 warning in 366.06 s, exit 0**.

## Phase 4 — integrated validation, cost measurement and live readiness

### 1. The pipeline as one system

Every stage was traced through `AetrixPipeline.run` and the stage matrix was
checked against the code, not the documentation. The rule that governs all of it:
**uncertainty only ever moves a question towards a person.**

| Situation | What the pipeline does | Where it is proven |
| --- | --- | --- |
| Correct answer, full marks | `MARKED`, no concerns | `test_a_full_run_through_the_seam_persists_every_question` |
| Correct answer, zero marks | reply contradicts its own answer check → `NEEDS_REVIEW` | `test_marking_verification` |
| Partially correct | awarded marks kept, method marks recorded | pipeline suite (`1a`) |
| Wrong answer with method marks | award kept; scheme stays silent unless the accuracy point was awarded | `test_scheme_check` attribution cases |
| Unsupported accuracy mark | `SCHEME_ANSWER_DIFFERENT`, definite, reviewed | `test_a_scheme_contradiction_is_not_second_guessed` |
| Blank answer | `CONFIRMED_ZERO` only at high confidence; otherwise reviewed | pipeline suite |
| Unreadable page | every award on the script reviewed, zero not confirmed | `test_an_unreadable_page_prevents_a_confident_zero` |
| Answer split across pages | mapped pages sent together, in page order | page-coverage unit tests |
| Missing page | blocking, **no rows and no provider calls** | `test_a_page_missing_from_storage_blocks_marking_before_any_request` |
| Duplicate page | marked, award kept, reviewed | `test_a_duplicated_page_image_is_marked_and_reviewed` |
| Incorrect page mapping | marked, gap reviewed (`UNMAPPED_PAGE`) | `test_a_partially_mapped_script_is_marked_and_the_gap_is_reviewed` |
| Mathematical equivalence | SymPy decides; `UNKNOWN` is never a wrong answer | `test_marking_verification`, transcription tests |
| Alternative valid wording | no equivalence → no finding, never a mismatch | scheme-check tests |
| Dependent criteria | `UNMET_DEPENDENCY`, definite | scheme-check tests |
| Contradictory working and answer | accuracy-point attribution decides | scheme-check tests |
| Malformed evidence | zero withheld, `MODEL_RESPONSE_INVALID`, reviewed | pipeline suite |
| Interrupted marking | rows kept per question, unusable reply recovered in bounded rounds | `test_job_recovery`, recovery tests |
| Recovery after restart | decided rows are never re-marked; recovery rounds persist on the job | `test_running_the_job_again_does_not_re_mark_anything` |
| Duplicate execution | `(job, question)` is the idempotency key | same test |
| Conflicting verification | a reviewed question is not second-guessed by a later stage | `test_a_scheme_contradiction_is_not_second_guessed` |

Four integration tests and six unit tests were added to prove the rows that were
not already covered.

### 2. Defects found and fixed

1. **An unprocessed document was invisible.** Coverage audited only documents in
   `PROCESSED` state, so a rejected or still-pending document's pages were absent
   from every request and its answers would have looked blank. New blocking
   `UNPROCESSED_DOCUMENT` finding: no rows, no provider calls.
2. **Cancellation was ignored during transcription and the double check.** The
   loops kept buying requests after a teacher pressed cancel, and the run could
   return `FINALIZING`. Both loops now stop, and the run returns `CANCELLED`
   between the stages.
3. **A cancelled run left verification records behind.** `_discard` deleted the
   question rows but not their `verification_results`, and a resumed execution
   treats a stored verdict as already taken — so it would have skipped a question
   whose award had been discarded. `_discard` now removes them with the rows.
4. **A definite scheme mismatch could be raised against an incomplete scheme.** An
   award above the criteria's capacity was always `DEFINITE_MISMATCH`, even when
   the stored criteria summed to fewer marks than the question. It is now definite
   only when the criteria cover the question's maximum; otherwise possible.
5. **Verification verdicts were not durable per question.** A crash between the
   first and last verdict lost them all, and the next execution paid for the same
   readings again. Each verdict is now committed as it is made.

A suspected fifth defect — the transcription `SCHEME_DOUBT` signal being
unreachable because reviewed rows are excluded — was investigated and rejected:
`ECONOMY` stores a possible scheme finding without reviewing the row, so a decided
row with doubt is exactly what that signal sees. The existing test that a question
already with a person is not re-read was kept.

### 3. Scheme verification after Phase 4

The 14 remaining misses in `experiment/paper01_engine_analysis/root_causes.md` fall
into three groups:

| Group | Count | Detectable by | Decision |
| --- | --- | --- | --- |
| Blank answer the first pass could not read | 6 | blind transcription | already the top transcription target; ACCURACY's budget covers a paper's three blanks |
| Method-mark award, accuracy withheld, wrong answer | 6 | a second marking only | no deterministic rule can see it; adding one would flag correct method-mark awards again |
| Over-award with an answer that matches the scheme | 2 | a second marking only | same: the final answer agrees, so the scheme has nothing to contradict |

No new recall rule was added, because none of the 14 can be decided from the
scheme, the mathematics or the stored evidence without re-introducing the Phase 2
false alarms. The replay after the Phase 4 changes is unchanged: **6 flags, 6 of
them wrong, 0 correct items flagged, recall 30%, precision 100%** on the same 228
decisions. The precision-protecting capacity change did not alter any replay result
because the reference schemes' criteria already sum to the question maxima.

### 4. Prompt size and actual token usage

`experiment/prompt_cost/measure.py` writes `measurements.json`. Prompt sizes are
exact characters and words; token counts are only ever the provider's reported
`promptTokenCount`. **No token count is derived from a character count.**

| Asset | Characters | Words |
| --- | --- | --- |
| marking v1 | 2,590 | 405 |
| marking v2 | 5,782 | 945 |
| double check v2 | 2,171 | 321 |
| transcription v1 | 1,477 | 236 |

The API ledger has 63 marking calls with reported usage, 177,301 input tokens in
total. Per marking request: `gemini-3.5-flash-lite` median **1,154.5** (n=48,
p95 2,381); `gemini-3.6-flash` median **1,511** (n=15, with one 31,818-token
whole-paper request). The production engine sends **one question per request**, so
a 38-question paper is 38 marking requests, and the prompt is transmitted once in
each.

The earlier "about 30,000 extra input tokens per paper" figure was derived from
characters and cannot be reproduced from reported usage; it is withdrawn. What is
measured is the size delta: v2 adds 3,192 characters / 540 words to **every**
marking request. Converting that to tokens needs one `countTokens` call per prompt
version on an approved key — two requests, no marking spend — or the first live
run's usage metadata.

Caching: the prompt is inlined as the first text part, which is what makes it
eligible, but the documented implicit-cache minimum is 4,096 input tokens for
Gemini 3.6 Flash (2,048 for 2.5 Flash), and a measured single-question marking
request has a median of ~1.2k input tokens including the page image. The prompt
alone is far below both thresholds, so implicit caching cannot remove its cost,
and an explicit cache has the same minimum. Rotating questions and pages also break
the shared prefix. Caching is therefore **not applicable** at this prompt size; it
becomes worth revisiting only if the shared instructions grow past the threshold.

### 5. Review-mode cost and value

`experiment/review_modes/coverage.py` reconstructs the six preserved runs' rows and
asks the production sampler which questions each mode would select. It measures
selection coverage, not detection: a selected question is one a second examiner
would be asked about, and rows carry no scheme concerns, so this is a lower bound.

| Mode | Requests/paper | Questions selected (6 papers) | Known-wrong hit (of 20) | Correct selected |
| --- | --- | --- | --- | --- |
| `ECONOMY` | 38.00 | 0 | 0 | 0 |
| `BALANCED` | 47.33 | 56 | 5 | 51 |
| `ACCURACY` | 51.83 | 83 | 11 | 72 |

ACCURACY costs 4.5 more requests per paper than BALANCED and reaches six more of
the twenty known errors; ECONOMY reaches none and confirms nothing. Two findings
matter for cost:

- `FULL_MARKS_VALUABLE` supplies 48 of BALANCED's 56 and 65 of ACCURACY's 83
  selections. Most second opinions therefore confirm a generous award on a
  valuable question; that is defensible, but it means selection precision against
  known errors is only 8.9% (BALANCED) and 13.3% (ACCURACY) against an 8.8% base
  rate of wrong items.
- The confidence threshold is **active**, contrary to an earlier Phase 4 note
  that called it inert. Marking routes an award below `min_confidence` (0.6 by
  default) to `NEEDS_REVIEW`, so a `MARKED` row may carry confidence anywhere
  from 0.6 to 0.949. ACCURACY's 0.95 threshold reviews those rows; BALANCED's
  0.6 threshold does not. The effect on this sample is modest because
  `FULL_MARKS_VALUABLE` dominates selection, but the comparison is real and is
  pinned by
  `test_the_accuracy_threshold_is_active_above_the_operator_default`.

The mode and switch interaction is covered by tests: `double_check_enabled=false`
disables second opinions in every mode (`DISABLED`, `SKIPPED`) while transcription
and every integrity check still run; `ECONOMY` still reports an integrity failure
with no second opinion bought.

### 6. Failure and security testing

Already covered by the existing suites and re-run here: provider 401 (credential
invalid, never counted against quota), 429 (per-key cooldown and rotation, not a
project pause), timeouts and network errors, malformed and truncated responses,
lease expiry and reclaim, stale-write refusal, concurrent guard reads, duplicate
execution, workspace isolation and the RLS regressions. Added this phase:
cancellation during the double check (no verdicts remain), and a resumed run that
does not pay twice for a stored reading or verdict. No credential, key or student
answer is newly logged; the usage ledger records token counts and costs, not
content.

### 7. Live readiness

`evaluate.py` now also emits a per-item `item_errors` list so the per-question
analysis does not need the raw run files. It already supports arbitrary
configuration directories, multiple prompt versions and modes through those
directories, cost and token accounting from each run's `usage`, review-rate
comparison and a paper-level paired bootstrap. `RUNBOOK.md` defines the material,
certification and adjudication rules, configuration matrix, request cap, stopping
conditions, evaluation method and reproducibility requirements.

Holdout: **0 certified papers, 0 live requests**. Nothing in this phase spent
provider credit.

### Verification (Phase 4)

- `ruff check app tests migrations experiment` — clean.
- `pytest tests/integration/test_correction_pipeline.py` — 33 passed.
- Replay `experiment/paper01_engine_analysis/analysis.py` — unchanged (6/6/0).
- Full suite against local PostgreSQL 16 — **764 passed, 1 warning in
  364.19 s, exit 0**.
- Migrations from a **new empty database** (`aetrix_fresh`, created after the
  suite) to head, including `0026_verification_kinds` — `tests/integration/
  test_schema.py`: 4 passed.

## Benchmark evidence

`experiment/paper01_engine_analysis/` replays six preserved benchmark runs
(38 items) through the deterministic layer:

- 0 awards changed by verification.
- 1 correct item flagged for review, 0 wrong items caught.
- Best item accuracy 36/38 (94.7%), mark agreement 97.5%, totals 72–82 against
  the reference's 80.

The replay also measures the scheme layer against the reference scheme's own mark
points: after attribution and severity, **6 of 20 wrong items flagged, 0 of 208
right items flagged**, for zero provider requests. The Phase 2 version flagged 24
items (9 wrong, 15 right); the 15 false alarms were each traced to judging a
method-mark award as if it carried the accuracy mark. Every flag is a review gate,
never a mark.

The reference is `candidate_not_teacher_certified`, so these figures are
provisional and the 95% target cannot be evaluated from them. The holdout
contains zero papers.

## Phase 5 — independent audit and validation preparation

Baseline `d6585cb`; existing AMI and user files were left untouched and nothing
was committed. The audit read the implementation rather than the tests and found
three defects, all fixed here:

1. **Stale verification verdicts.** A retried question kept the `INTEGRITY`,
   `MATHEMATICAL` and `SCHEME_MATHEMATICAL` verdicts of the reply it replaced,
   because persistence was upsert-only. The marking kinds are now deleted as a set
   before the new verdicts are written, and an unusable reply also clears the
   components and evidence of the attempt it replaces. A stale `MATHEMATICAL`
   verdict can therefore no longer appear against a reply that made no
   mathematical comparison.
2. **Cancellation before the guard.** Cancellation was checked after marking,
   transcription and double check, but a request arriving in the final gap could
   still reach `_apply_guard` and start presenting a finished run. A check before
   the guard now discards the rows and returns `CANCELLED`.
3. **Misleading confidence-threshold claim.** The Phase 4 note called ACCURACY's
   0.95 threshold inert. It is active: marking only routes below
   `min_confidence` (0.6) to review, so `MARKED` rows can carry 0.6-0.949 and
   ACCURACY reviews them while BALANCED does not. The note above is corrected and
   `test_the_accuracy_threshold_is_active_above_the_operator_default` pins it.

Also added:

- `settings.marking.marking_prompt_version` pins marking prompt v1 or v2 and is
  recorded on every result row and engine run, so the baseline and the rewritten
  prompt can be compared on identical papers without editing an asset.
- Failure-path integration tests against real PostgreSQL: cancellation during
  marking, transcription and before the guard; crash before and after the
  verification commit; a database statement failure inside the transaction; stale
  verdict replacement on retry; `UPLOADED` and `REJECTED` documents blocking
  before any request; prompt pinning and default provenance.
- The evaluation harness now refuses uncertified, single-marker, unadjudicated or
  incompletely covered references and runs; scores only papers present in both the
  reference and the run; records excluded runs and provenance; reports
  over/under-awards and review false positives/negatives separately; and states
  that its bootstrap unit is the paper.
- `experiment/live_validation/validate_dataset.py` plus `reference.schema.json`
  and `reference/README.md`: two-marker evidence, independent adjudication,
  certification fields, a SHA-256 integrity manifest, and a command that exits 2
  before any experiment if the dataset is incomplete or changed.
- `experiment/prompt_cost/prepare_count_tokens.py` and `COUNT_TOKENS.md`: the two
  exact `countTokens` bodies for v1 and v2 are written locally; **zero requests
  were sent**. `EXPERIMENT_MATRIX.md` defines the four configurations, caps
  (2,120 requests including recovery contingency), projections, metrics, analysis
  and stopping conditions.

Verification (this phase, disposable PostgreSQL 16):

```
backend pytest (unit + integration)   809 passed, 1 warning, 322.61 s, exit 0
migrations from an empty database    4 passed (tests/integration/test_schema.py)
ruff check app tests experiment      all checks passed
```

No AMI or frontend file was modified (`git status` shows no `frontend/` entry and
`ami/` remains untracked). Nothing was committed or pushed.

Remaining issues:

| Severity | Issue | Status |
| --- | --- | --- |
| Blocker | Zero teacher-certified papers; the reference directory is empty | external material required |
| Blocker | No approved provider budget/key; live provider remains `UNVERIFIED` | approval required |
| High | Accuracy of the engine and of the review modes is unmeasured | blocked on the two items above |
| Low | The harness requires every disagreement to name the same certified adjudicator | intentional strictness; a multi-adjudicator dataset would need a contract change |
| Low | `marking_prompt_version` is an environment setting, not a UI control | sufficient for the prepared experiment |
| Resolved | A pinned prompt changed midway through one job could mix versions across rows | engine now fails closed before spending a request; harness refuses mixed per-question versions |

## Review-mode measurement reconciliation

Re-ran ECONOMY, BALANCED and ACCURACY offline over the same six preserved raw runs
and the same 38 scored questions per run. `experiment/review_modes/coverage.json`
is untouched; the re-run writes `reconciliation.json` and
`RECONCILIATION.md`. Every Phase 4 metric and reason count reproduces **exactly**:
38.00 / 47.33 / 51.83 requests per paper, 0 / 56 / 83 selections, 0 / 5 / 11 known
errors selected, 8.9% / 13.3% selection precision.

The corrected threshold claim is now quantified. Two `MARKED` rows in the sample
carry confidence in `[0.85, 0.95)` (`a_run2/26`, `c_run5/36`, both 0.90 and both
correct). ACCURACY selects both **specifically because of the 0.95 threshold**;
they displace `a_run2/2` and `c_run5/16b`, so the threshold adds **two questions,
zero known errors and zero requests**. The 12-question budget is full: the
threshold changes which questions are reviewed, not how many. "Inert" was the
wrong mechanism and roughly the right net effect on this sample; it is not inert
in general, and the test pins the mechanism.

Selection reasons (question-level, ACCURACY second opinions): 65
`FULL_MARKS_VALUABLE`, 2 `LOW_CONFIDENCE`, 4 deterministic high-confidence sample,
0 other. BALANCED: 48 full marks; all 8 transcriptions `BLANK_ZERO`. ACCURACY: 12
transcriptions, all `BLANK_ZERO`. Reconstructed rows carry no scheme concerns or
history, so other reasons are a lower bound, not evidence they never occur.
Incremental BALANCED -> ACCURACY is +27 requests for +6 known errors reached
(4.5 requests per additional known error selected); this is **selection**, not
detection.

Provenance is now enforced per question: a run file must carry the result row's
`prompt_version` on every item, matching the run's marking version, and the report
records engine/config/prompt for every question. A retry that would add rows from
a different prompt version fails closed before any request; a test covers it.

## Provider usage

**Zero live provider requests were made in this session.** Every pipeline test
uses a stub provider; the benchmark figures come from preserved responses. No
model was rotated, no credential was created, and no production data was changed.

## Blockers and what is not established

1. **No certified holdout.** Accuracy cannot be claimed until a teacher-marked
   set exists. Plan: `experiment/live_validation/PLAN.md`.
2. **Live Gemini provider remains `UNVERIFIED`.** Any live experiment needs an
   approved credential and a written request budget.
3. **Review-mode accuracy gain is unmeasured.** The cost side is tested; whether
   ACCURACY catches more wrong marks per request is exactly what the holdout
   experiment must measure.
4. The local PostgreSQL cluster used for these runs is a disposable pgserver
   instance under `.tmp/` (gitignored); it is not part of the product.

## Phase 6 — a reproducible gate, and an approval that binds its rules

### 1. The integration gate could not run from a clean cluster

`pytest tests/integration` failed at setup on a fresh local PostgreSQL 16: the RLS
migrations revoke from `anon` and `authenticated`, which Supabase defines and a
bare cluster does not. CI creates them (`.github/workflows/ci.yml`); the pytest
bootstrap did not, so "the suite migrates to head" was only true of a cluster
someone had prepared by hand. `tests/conftest.py` now creates the two roles when
they are missing, before `alembic upgrade head`. This is test bootstrap only: no
product schema, migration or database change.

With that in place the full suite ran from a new database through every revision,
including the restored `0026_scheme_criteria_approval` →
`0027_transcription_checks` branch, the `0028_merge_heads` merge, and `0029`/`0030`.

### 2. Approval now records the marking rules it covered

`mark_scheme_versions.criteria_approved_at` said a person had reviewed the
criteria. It could not say *which* criteria: editing a tolerance, changing a mark
point, adding a dependency or re-targeting an alternative left the timestamp valid,
and the engine would mark against rules nobody approved. `criteria_blueprint_hash`
was written by the importer but never read, so nothing detected the drift.

Now:

- `scheme_criteria.criteria_rules_hash(criteria, structure)` is a SHA-256 over each
  rule's identity (`question_id`, `code`, `ordinal`), marks, description, printed
  answer, required evidence, dependencies, alternative routes, award and withhold
  conditions, plus the blueprint leaves the rules were reviewed against. Row order
  does not change it.
- Migration `0031_scheme_criteria_rules_hash` adds
  `mark_scheme_versions.criteria_rules_hash` (nullable, no backfill).
- The importer records the digest when it approves, and the marking gate
  (`criteria_readiness`) recomputes it from the stored rows before any provider
  request. A different digest is `SCHEME_CRITERIA_RULES_CHANGED`; an approval that
  records none is `SCHEME_CRITERIA_RULES_UNVERIFIED`. Both refuse the run with no
  rows and no request. An incomplete criteria set still reports
  `SCHEME_CRITERIA_INCOMPLETE`, because that defect is independent of approval.
- `scripts/import_scheme_criteria.py --approve-existing --approve-by <id>
  --reason "..."` re-approves rows that are already imported. It refuses unless the
  document's rules match the stored rows exactly (exit 5) and edits no criterion
  row; it records the digest, approver, time and reason only.

**Consequence for an existing deployment:** a scheme approved before this revision
has no digest, so the gate refuses it until it is re-approved with
`--approve-existing`. That refusal is deliberate: the approval cannot be shown to
cover the rows stored beside it, and inventing a digest would assert a review
nobody performed. No historical result, award or job is affected, because results
keep the engine and version that produced them.

### 3. Verification (this phase, disposable PostgreSQL 16)

```
ruff check app tests scripts/import_scheme_criteria.py     All checks passed
pytest tests/unit -q                                       728 passed in 8.06 s
pytest tests/integration -q                                291 passed, 1 warning in 330.63 s, exit 0
  (from the head of migration 0031, after the from-zero run below)
pytest test_schema.py test_whole_paper_marking.py -q       13 passed in 23.05 s
  (on a brand-new database `aetrix_fresh`, migrated to head, exit 0)
alembic heads                                              0031_scheme_criteria_rules_hash (head)
```

`ruff check scripts` (all scripts) still reports five pre-existing findings in
`finish_job.py`, `mark_downloads.py`, `retry_job.py`, `validate_live_credentials.py`
and `watch_marking.py`, none of which this work touched.

No provider request was made, no live database was migrated, no job was resumed,
and no frontend or AMI file was modified.

## Phase 7 — criterion identity, route exclusion, term counts, paper recovery

Phase 6 made approval record the rules it covered. This phase closed the four
Engine gaps that were still open after it: which printed row an award belongs to,
what an alternative route replaces, whether a printed term count holds, and what a
crash between a paid paper request and its rows may cost.

### 1. A reply's order no longer decides which criterion is awarded

The pilot repeats codes (`M1 M1 A1`), and a reply names codes, not rows. The
resolution is now pinned by tests over the real payload
(`backend/tests/unit/test_criterion_identity.py`):

- every permutation of a full `M1 M1 A1` award credits the same rows and yields
  the same findings, and the six orderings of Q18 are one award;
- a bare repeated code credits the printed order (the earlier row), which is the
  only convention that cannot invent an award;
- `M1FT` is the explicit identity: it is pinned to the dependent row wherever it
  appears in the list, and awarded alone it is still `UNMET_DEPENDENCY`;
- a missing component is never invented, a duplicated component cannot earn a
  mark point twice (`EXCESS_CRITERION_AWARD`), an unknown code is
  `UNKNOWN_CRITERION`, and a duplicated alternative route cannot earn its marks
  twice. No response-order dependence remains, so no ordering review signal was
  added; the convention is documented in the tests that pin it.

### 2. An alternative route replaces specific criteria

`alternatives` in the approved data now carry `replaces`. `scheme_criteria.validate`
refuses a coded alternative that names no scope, names an undefined code, omits
its own host, leaves a prerequisite active, is defined twice, carries more marks
than the rows it replaces, or records an unusable `term_count`. Readiness refuses
the scheme before any request, so a pilot cannot start on route data the verifier
cannot interpret.

`scheme_check.alternative_routes` resolves a route to the rows it excludes, and
`_route_findings` reports `ROUTE_CONFLICT` when an award earns a route and a row
it replaces. This is what makes the two previously invisible over-awards visible:
Q34 `M2+M1` and Q36 `B2+A1` both total the question's three marks, so capacity
alone could not see them. `backend/tests/unit/test_alternative_routes.py` covers
each valid route, every previously identified over-award combination, both routes
of one question at once, and the approved data itself. One existing expectation
was corrected: Q36's `B2` answers with no working, so a `B2` plus an `M1FT` is now
reported as both `UNMET_DEPENDENCY` and `ROUTE_CONFLICT` — the no-working route
stands in for the method marks it follows.

`backend/seed/pilot_scheme_v1_criteria.json` holds 8 route entries, 7 of them
coded; all 7 now record the codes they replace (Q13's is printed prose and carries
no code). The review file was regenerated with the new semantics.

### 3. Term counts are evaluated, or reported as unknown

`backend/app/correction/term_count.py` reads a recorded threshold
(`{"expression", "count", "required"}`), parses the student's answer with the
existing parser, and matches the earned terms against the printed ones. A threshold
that cannot describe its own expression, an answer written as a product or
fraction, and any expression the parser cannot read return `UNKNOWN`.

`scheme_check.term_count_findings` turns that into findings: `TERM_COUNT_NOT_MET`
(definite), `TERM_COUNT_UNVERIFIED` (review), and `ROUTE_THRESHOLD_UNRECORDED` for
an awarded route with no recorded threshold. Only the two no-working routes have a
printed term count (Q36 and Q37a, both `3 out of a maximum of 4 terms`); both now
record the expression and threshold, so no route silently passes. The check is
wired into `_MarkingRun._persist_mark` beside the existing scheme checks.

### 4. A paid paper is never bought twice

`mark_paper` now commits the complete reply to `provider_responses` in its own
transaction before anything is parsed or any question row is written. On a later
execution:

- `_recoverable_paper_reply` reuses an archived reply that still parses to marks
  for the questions being marked, without a provider request (a resumed or
  truncated paper included);
- `_paid_paper_attempt` finds a successful whole-paper call in the usage ledger
  when no archive is usable and returns `PAID_ATTEMPT_UNRECOVERABLE`, marking the
  unmarked questions individually instead of re-sending the paper;
- `ARCHIVE_FAILED` is parked like `PERSIST_FAILED`, but reported honestly: the
  reply was not kept, so no marks were taken from it.

What this does not claim: the provider offers no idempotency key. A process that
dies after the provider answered and before the usage row is committed leaves no
local trace, and that request can be repeated on retry. The archive closes the
window after the response is recorded; it cannot close the window before. The raw
reply and every attempt stay in `provider_responses` / `provider_usage`.

### 5. Verification (this phase, disposable PostgreSQL 16)

```
ruff check app tests                                     All checks passed
ruff check scripts/import_scheme_criteria.py \
           scripts/render_scheme_review.py               All checks passed
pytest tests/unit -q                                     797 passed in 5.07 s
pytest tests/integration -q                              292 passed, 1 warning
                                                          in 323.65 s, exit 0
python scripts/render_scheme_review.py --check           matches the payload
```

Migrations did not change this phase, so the fresh-database chain was not re-run;
`alembic heads` remains `0031_scheme_criteria_rules_hash`.

Two integration fixtures were corrected rather than the rule relaxed: their
canned replies put a whole leaf's marks on a single `A1` component, which is the
contradiction `EXCESS_CRITERION_AWARD` exists to catch. The replies now name the
printed codes, and the repeated whole-paper run asserts that the archived reply is
reused (`paper_requests == 1`) instead of a second paid request.

No provider request was made, no live database was migrated, no parked job was
requeued, no historical result was modified, and no AMI or frontend file was
touched.

## Phase 8 — independent verification: identity, term counts, routes, recovery

No redesign. The resolver, evaluator, route enforcement and recovery boundaries
were re-read and re-tested; one real defect was found and fixed.

### The defect: deterministic attribution was reported as decided attribution

`_awarded_criteria` matches an award of a repeated code to the rows of that code in
printed order. That is deterministic, but five pilot questions (Q6, Q11, Q13, Q28,
Q37b) print **two independent mark points under one code**. A reply that awards
that code once does not say which point it earned, and the engine was crediting the
first row with no signal at all.

`scheme_check._identity_findings` now reports `AMBIGUOUS_CRITERION_CODE`
(`POSSIBLE_MISMATCH`) in exactly that case, naming the code, the number of printed
points and the marks awarded, and telling the reviewer the award was read against
the printed order and must be attributed.

It does **not** fire where the resolution is genuinely determinate:

- a follow-through chain (the eleven questions whose second `M1` depends on the
  first) — the dependent point cannot be earned without the earlier one, so one
  award of that code can only be the earlier point;
- a full award of both points (two components, or one component carrying both
  marks);
- a decorated code (`M1FT`), which is an explicit identity judged by the
  dependency check.

A probe over the whole pilot confirms the finding appears for exactly the five
independent pairs and nowhere else, for a single award or a full one.

### Verified without change

- **Term counts.** `_written_terms` refuses products of sums and unreadable
  expressions (`UNKNOWN`) and matches terms by mathematical equality with
  consumption, so a repeated term cannot stand in for another. New tests pin the
  cases that distinguish structure from textual fragments: an unrelated extra term
  leaves a met threshold met, extra *like* terms collect and break the matches,
  wrong coefficients and powers do not match, and ordering or grouping brackets
  change nothing. Q34's printed threshold counts four uncollected terms
  (`12x^3 - 30x^2 - 30x^2 + 75x`), which SymPy collects to three; recording that
  spec is refused, so Q34 stays `ROUTE_THRESHOLD_UNRECORDED` rather than getting a
  threshold that does not describe it. Q18, Q23 and Q26 remain in review: their
  eight-term specifications are not transcribed.
- **Routes at runtime.** A new integration test adds a documented two-mark route
  (`M3`, replacing `M1` and `M2`) to the stored criteria, recomputes the approval
  digest, and marks a reply that awards `M3` and a `M1` it replaces: the row keeps
  its three marks, is `REVIEW_REQUIRED`, and carries `ROUTE_CONFLICT`. Enforcement
  is in the marking path, not only in the importer.
- **Recovery.** Archive-then-rows transaction order, the archive re-use path, the
  `PAID_ATTEMPT_UNRECOVERABLE` guard, `ARCHIVE_FAILED` parking, duplicate-object
  first-wins parsing and the no-duplicate partial-paper fallback are unchanged and
  remain covered by the Phase 7 tests.

### Verification (disposable PostgreSQL 16)

```
ruff check app tests                                      All checks passed
pytest tests/unit -q                                      824 passed in 7.92 s
pytest tests/integration -q                               293 passed, 1 warning
                                                           in 315.26 s, exit 0
python scripts/render_scheme_review.py --check            matches the payload
```

No migration was applied, no live database was written, no provider call was made,
no job was requeued, the pilot scheme was not re-approved, and nothing was
committed or pushed.

## Phase 9 — scheme answer source and lost superscripts

Baseline `7dcdf92` on `main`, working tree already dirty with the parallel/whole-paper
integration work; nothing was reset, stashed, overwritten or committed. Migrations at
`0036_verification_completeness (head)`. AMI untouched. No production row was written
and no provider request was made.

During the session HEAD advanced to `65a5abf` ("feat(web): add the paged correction
preview and verification records"), committed at 21:08 local by an external Codebuff
process. This work did not create that commit and did not modify or revert it; its own
changes remain uncommitted on top of it.

### 1. Baseline measured, not assumed

```
ruff check app tests                                  All checks passed
pytest tests/unit -q                                  1116 passed in 12.19 s
pytest tests/integration -q                           343 passed, 1 warning in 520.66 s
  (disposable PostgreSQL 17.6 on 127.0.0.1:55433, migrated from an empty database)
frontend tsc --noEmit                                 exit 0
frontend vite build                                    exit 0
frontend playwright verification-ui                   12 passed
```

The integration suite refuses to run without `AETRIX_TEST_DATABASE_URL`; that guard is
correct and was not bypassed.

### 2. The defect: the scheme's own answer field was never read

`scheme_check.scheme_expected_expression` built its candidate answer from each
criterion's `description` and `award_conditions` only. `marking_criteria.expected_answer`
— the field that exists to state the answer — was ignored. A criterion whose
description is prose ("a correct expansion", "Depends on the first M1") therefore
produced no comparable answer, and the mathematical check reported `SKIPPED` on a
question the scheme clearly answers: no `SCHEME_ANSWER_DIFFERENT` and no
`SCHEME_ANSWER_WITHHELD` could ever fire there.

The same transcription that fills `expected_answer` flattens superscripts: the pilot
stores `24x3 - 28x2 - 12x` and `a3b2`. Read literally those are 24 times a symbol called
`x3`, so a correct `24x^3 - 28x^2 - 12x` is judged **different** from the scheme.

Measured directly against the pilot bundle: the flattened forms occur only in
`expected_answer`; every `description` that states an answer already uses `^`. That is
why the defect was **latent** on this paper — the description happened to carry the
answer — and why the repair changes no verdict on it. The repair is a guard for the
schemes where it is not latent.

### 3. The repair

- `verification.restore_printed_superscripts` reads `12x3` as `12x^3`.
- `verification.equivalent_to_scheme` runs the strict comparison first and keeps its
  verdict; a second reading of the **scheme side** may prove equivalence, never create a
  difference. `None` still means "cannot decide".
- `scheme_check.scheme_expected_expression` now reads `expected_answer`, and groups
  candidates by one canonical key (`restore_printed_superscripts` + whitespace + case)
  so the same answer written with a caret and with a flattened digit is **one**
  candidate rather than a false ambiguity that switches the check off.
- `check_answer_against_scheme` and `answer_is_printed_form` compare through
  `equivalent_to_scheme`.

A different sign, coefficient or power is still `DIFFERENT`: the restored reading does
not swallow real differences.

### 4. Regression coverage

`backend/tests/unit/test_scheme_superscripts.py` — 15 tests: the artefact itself,
the four pilot answers with flattened superscripts, reordering, three genuine
differences (sign, coefficient, power), the `cao` printed-form interaction, a withheld
accuracy mark for an equivalent answer now producing `SCHEME_ANSWER_WITHHELD`,
`expected_answer` read when the description is prose, two notations of one answer not
treated as ambiguous, and two genuinely different answers still producing `SKIPPED`.

Effect on the one available paper, measured offline over the 38 comparable leaves:
scheme answers comparable 38/38 before and after; 0 verdict changes. Stated because it
is the honest result, not a shortcoming to hide.

### 5. Verification after the repair

```
ruff check app tests                                  All checks passed
pytest tests/unit -q                                  1131 passed in 12.69 s
pytest tests/integration/test_correction_pipeline.py
         test_aetrix_pipeline.py test_parallel_marking.py
         test_whole_paper_marking.py test_provider_calls.py
                                                      103 passed, 1 warning, 123.55 s, exit 0
frontend tsc --noEmit                                 exit 0
frontend vite build                                   exit 0
frontend playwright verification-ui                   12 passed in 20.7 s
```

The full integration suite (343 passed, 520.66 s, exit 0) was measured on the
unmodified baseline. After the edits only the five suites that exercise
`scheme_check` and the marking pipeline were re-run; the remaining integration files
do not import the changed modules. That is the smallest set that covers the change,
and it is stated rather than implying a second full run.

### 6. Real-paper comparison, and why it is not the controlled experiment

`experiment/real_paper_comparison/compare_modes.py` freezes the stored `WHOLE_PAPER` job
(read-only `SELECT`) and compares it with the archived parallel run against the
stored candidate reference. Results, confounds and per-question root causes are in
`experiment/real_paper_comparison/REPORT.md`. Headline: 24/38 and 26/38 item-exact,
76/80 and 77/80 marks, 1 request / 16.2k input tokens against 39 requests / 132.1k.

It is **not** Experiment A: the arms used different model pools, different builds and
different implementations. A controlled comparison on the current build needs a live
run, which needs either a production write or credential extraction. Neither was done.

### 7. Remaining, and what it costs

| Issue | Status |
| --- | --- |
| No teacher-certified reference | blocker: external material |
| Controlled WHOLE_PAPER vs PARALLEL run on HEAD | not performed: needs an approved live run |
| Evidence authenticity is only checked when transcription is enabled and the question is selected | open design gap; the stored 37(b) full-marks award on a blank answer is the live example |
| Development database schema predates `prompt_version`, `verification_status` on `correction_jobs` and `criterion_results.marks` | historical rows only; no migration was applied here |
