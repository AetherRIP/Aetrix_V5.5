# Aetrix V5.5 — engine implementation set

This directory preserves the implementation documentation developed in the standalone
`Engine_V5.5` repository. It describes the code now under [`backend/`](../../backend), the
frozen benchmark under [`benchmark/`](../../benchmark), and the acceptance evidence for the
CP1–CP2 checkpoints.

## Read in this order

1. [`architecture/SYSTEM_OVERVIEW.md`](architecture/SYSTEM_OVERVIEW.md) — runtime topology,
   module map, data model, job lifecycle, API surface and deliberate absences.
2. [`architecture/DATA_FLOW.md`](architecture/DATA_FLOW.md) — request, worker, ingestion,
   mapping, extraction and provider-call flows.
3. [`architecture/DECISIONS.md`](architecture/DECISIONS.md) — numbered ADRs, including the
   provider boundary, canonical blueprint and live-verification rules.
4. [`architecture/SECURITY.md`](architecture/SECURITY.md) — tenant isolation, credential
   handling and untrusted model output.
5. [`architecture/DEPLOYMENT.md`](architecture/DEPLOYMENT.md) — PostgreSQL/Supabase setup,
   configuration, migrations, API/worker operation and CI commands.
6. [`architecture/RLS_SECURITY_AUDIT.md`](architecture/RLS_SECURITY_AUDIT.md) — the Data API
   exposure audit, policy matrix and RLS lockdown plan.
7. [`architecture/PROVIDER_FLEET.md`](architecture/PROVIDER_FLEET.md) — Gemini key fleet,
   project-level quota, quota confidence and failure handling.
8. [`audits/CP2_ACCEPTANCE.md`](audits/CP2_ACCEPTANCE.md) — deterministic evidence and the
   live-provider failure record.
9. [`audits/INITIAL_REPOSITORY_AUDIT.md`](audits/INITIAL_REPOSITORY_AUDIT.md) — the Phase 0
   inventory and corrected premise.

## Authority and scope

These documents govern the implemented engine. The older [`docs/`](../) tree is the original
Cloudflare/D1 planning set and is preserved as history; it is not a description of the running
Python engine. Where the two conflict, `docs/engine/` and the engine ADRs win.

The worker builds exactly one correction engine — `aetrix_v5_5` — with no selection and no
fallback. `AetrixPipeline` marks each leaf question through the audited provider-call service,
persists the award with its quoted evidence, checks it against evidence the model did not produce
(deterministic integrity and arithmetic checks, SymPy equivalence with any answer the approved
scheme states, and the scheme's own criteria), retries only unusable replies within a recorded
budget, takes a second independent marking of the questions a suspicion ranking puts first, and
refuses to present a run that would replace an approved or overridden result. A malformed reply,
an unreadable page, a missing page or an exhausted retry budget produces a review item, never a
zero. `UnavailablePipeline` survives only as the explicit "nothing to run" object the
job-infrastructure tests use.

## Correction modes

A job records the mode it is corrected in (`correction_jobs.marking_mode`), fixed on its first
marking execution. The mode may be named when the job is created (`CorrectionCreate.marking_mode`)
or left to `settings.marking.marking_mode`; a resumed job and a teacher-requested recovery keep the
mode already recorded, so one paper never mixes request shapes. All three values execute different
paths in `AetrixPipeline` — none of them is a label on another path.

| Mode | Execution | Verification |
| --- | --- | --- |
| `WHOLE_PAPER` (default) | One audited request for the whole script and scheme; leaves the reply did not decide are marked individually by the retained per-question loop. | Same stages, per stored row. |
| `PER_QUESTION` | One audited request per scoreable leaf, sequentially. | Same stages, per stored row. |
| `PARALLEL` | The same per-question request and contract, with independent questions corrected concurrently in dependency-aware waves (`backend/app/correction/aetrix/parallel.py`). | Same stages, per stored row. |

Parallel execution plans every scoreable leaf first, chains sub-questions of one parent in paper order
(a later part is not dispatched until its prerequisite has a stored decision), and runs separate
parent questions together under `settings.marking.parallel_max_concurrency` (default 3, 1–8). Inputs
are built on the orchestrating thread; each worker opens its own session for the provider call and
its append-only usage row; parsing, validation and persistence happen on the orchestrating thread in
blueprint order, so one question cannot corrupt another's rows. A refused question is recorded and
the rest of the paper continues; a question with no stored decision makes the paper incomplete and
sends it to review instead of presenting a total. Totals are recomputed from stored rows in blueprint
order, and a missing, duplicated or over-maximum question blocks acceptance.

Every mode goes through the same credential pool, project/model quota accounting, project cooldown,
bounded retry policy and append-only `provider_usage` ledger. Parallel workers share a process lock
around the lease read-and-reserve; quota remains a project property, so additional concurrency cannot
create capacity the provider does not have. Each attempt records provider latency and the time it
waited for a lease (`provider_usage.latency_ms`, `provider_usage.queue_wait_ms`), so contention is
measured separately from the provider being slow. There is no automatic fallback to another mode: a
provider failure parks or reviews the job in the mode it recorded.

Not implemented: an operator UI control for the mode, an automatic mode fallback, and any measured
accuracy, reliability or speed comparison between the modes. No such comparison is claimed.

## Review modes

`assignments.review_mode` is read from the job's tenant-scoped assignment on every run; it is not
a request field. It selects a review policy (`backend/app/correction/sampling.py`), while
`settings.marking.double_check_enabled` remains the operator's switch: a mode narrows or widens
the double check, and no mode enables it against that setting.

| Mode | Second opinions | Confidence threshold | Confident sample | Blind transcriptions | Recovery rounds |
| --- | --- | --- | --- | --- | --- |
| `ECONOMY` | none; `double_check_status = NOT_REQUIRED` | — | — | none | 1 |
| `BALANCED` (default) | up to `double_check_max_questions` | `double_check_min_confidence` | none | up to 2 | 2 |
| `ACCURACY` | up to `max(double_check_max_questions, 12)` | `max(double_check_min_confidence, 0.95)` | 2 | up to min(`transcription_max_questions`, 6) | 3 |

`assignments.review_mode` is the authority; `settings.marking.review_mode` is the fallback for a
submission whose assignment row predates review modes, so the two cannot silently disagree. The
threshold is real: marking sends anything below `min_confidence` (0.6 by default) to review, so a
`MARKED` row may still carry 0.6-0.949 confidence, and `ACCURACY`'s 0.95 threshold reviews it while
`BALANCED` does not.

Validation preparation. `settings.marking.marking_prompt_version` pins the marking prompt to one
manifest version (`None` uses the newest); it exists so a controlled experiment can compare prompt
v1 and v2 on identical papers, and it is recorded on every result row and engine run like any other
prompt version. A retry may not change that version: if a job already has result rows
marked with a different version, the engine fails closed before spending another request, and
the harness refuses a run whose per-question versions disagree. Certified references are
validated twice: `experiment/live_validation/evaluate.py`
re-applies certification, two-marker and adjudication rules while scoring, and
`experiment/live_validation/validate_dataset.py` checks the whole directory and its SHA-256
manifest before a run is allowed to start. Neither tool can promote an uncertified paper, drop a
missing question from a denominator, or compare configurations on different papers.
Transcription additionally requires `settings.marking.transcription_enabled`: a mode can spend
more of that budget, never enable it against the operator, and `ECONOMY` never spends it.

Selection is deterministic (seeded by the job id) and ranked by suspicion: low confidence, an
award the pipeline had to normalise, marks beside a blank answer, full marks on a question worth
at least three marks, an outstanding scheme concern, and past double-check disagreements on the
same question in the workspace. Every chosen question is one provider request; the reasons that
chose it are stored with the verdict (`detail.selection`), and the `DOUBLE_CHECK` engine run
records the mode, budget, threshold, candidates and selection. `ECONOMY` therefore costs exactly
the marking requests, and `BALANCED`/`ACCURACY` never exceed their budget. `ECONOMY` still runs
every integrity, scheme and coverage check: the mode buys fewer opinions, never fewer checks.

## Scheme checks and page coverage

The approved scheme is read as a second account of the marking decision, not as a prompt. The
reply is checked for a mark point the scheme does not define, a scheme mark point the reply never
considered, an award larger than the scheme's capacity, and a dependent mark awarded without its
prerequisite; a scheme description that states a comparable answer is compared with the student's
by SymPy equivalence. A description that states no comparable answer ("M1 for expanding")
produces no mathematical verdict, and an `UNKNOWN` comparison produces no finding. Codes are
compared by mark point, so a reply that writes `1a_B1` or `M1FT` is naming the scheme's `B1` or
`M1`; `MISSING_MARK_POINT` fires only when the award is below the scheme's capacity.

Findings carry a severity. `DEFINITE_MISMATCH` is a contradiction the stored evidence proves —
an award above the scheme's capacity, a dependent point without its prerequisite, or an accuracy
mark awarded for an answer the scheme says is different — and is always reviewed. An award above
the scheme's capacity is only definite when the stored criteria themselves carry the question's
full marks; a scheme whose criteria sum to less than the question is an incomplete record, so the
finding is possible, not a contradiction.
`POSSIBLE_MISMATCH` is worth a look without proving an error (notation the scheme does not use, a
point nobody named, an accuracy mark withheld although the answer matches); `BALANCED` and
`ACCURACY` review it, `ECONOMY` records it as evidence. `VERIFIED` is nothing to dispute and
`UNVERIFIABLE` means this build could not compare. The attribution matters: a wrong final answer
is only a contradiction when the accuracy mark itself was awarded, because awarding method marks
and withholding the accuracy mark is correct marking. On the preserved benchmark replay the
attributed layer flags 6 of 228 item decisions — all 6 wrong, none of the correct ones — at no
provider cost.

## Blind transcription

When `settings.marking.transcription_enabled` is on, the pipeline spends a request on a second,
independent reading of selected answers (`correction/transcription.py`). The reader sees the
pages and the question only — never the award, the scheme or the first answer — and is asked to
copy what the candidate wrote. Its reading is compared with the first pass: `AGREES`, `DIFFERS`,
`ABSENT` (both see nothing) or `UNVERIFIABLE` (the reply was unusable). A difference raises
`TRANSCRIPTION_DIFFERS` and sends the question to a person; the award and the original evidence
are never changed. Selection targets the shapes where a misread is most expensive: a zero beside
a blank answer, incomplete pages, a low-confidence reading, or a decided result whose stored
concerns already doubt it (a question already with a person is not read again: the reading could
not change its state). The stage is off by default because it costs a request per selected
question, and `settings.marking.double_check_enabled` does not disable it — transcription is a
reading, not a second opinion.

The same reading answers a second question at no extra request: does the text the marking pass
quoted actually appear on the page? Each quotation is normalised and matched against the blind
transcript (`correction/evidence_check.py`). The verdict is `PASS` only when every quote is found,
`FAIL` when one is absent, and `UNVERIFIABLE` when there is no usable reading or the quote is too
short to be distinctive. A failure raises `EVIDENCE_NOT_FOUND`; an unverifiable quotation of an
awarded question raises `EVIDENCE_UNVERIFIED`. Neither changes an award.

The check runs only where a blind reading was bought, and that selection targets zero or
uncertain answers, so an awarded question whose citations were not selected reports `EVIDENCE`
as a missing required check (`PARTIALLY_VERIFIED`) rather than as a pass. Extending the reading
to every awarded question would add provider requests to every paper, which the transcription
budget deliberately bounds; that remains a stated limitation rather than a silent claim.

## Verification completeness

`correction/verification_status.py` derives a state per question from the stored verdicts, never
from the absence of review flags. `INTEGRITY` is required for every decided question;
`MATHEMATICAL` or `SCHEME_MATHEMATICAL` when the reply or the approved scheme defines an expected
answer; `EVIDENCE` whenever marks were awarded; `TRANSCRIPTION` and `DOUBLE_CHECK` when they ran.
A missing required check is a gap; a mathematical check that neither the reply nor the approved
scheme defines an answer for is `NOT_APPLICABLE`; and a contradiction outranks everything else. The states are `FULLY_VERIFIED`, `PARTIALLY_VERIFIED`,
`REVIEW_REQUIRED`, `VERIFICATION_FAILED` and `VERIFICATION_NOT_REQUIRED`; the paper reports the
worst of its questions, so `COMPLETED` never implies `FULLY_VERIFIED`. The state is stored on
`correction_jobs.verification_status` and returned with per-question detail by the results API,
which is how the screen shows completion and verification as two separate facts.

Page coverage is assessed before any request is spent: a document in the submission that is not
`PROCESSED` (`UNPROCESSED_DOCUMENT`), or a page the document declares but storage does not hold
(`MISSING_PAGE`), stops the run with no rows and no provider calls, because the unread pages may
hold the answer. The audit also reports a page whose number contradicts the
document's page count (`PAGE_SEQUENCE`), the same page image twice (`DUPLICATE_PAGE`), a readable
page no question is mapped to while some question has no mapping at all (`UNMAPPED_PAGE` — the
continuation risk), and a question mapped to more pages than one request carries (`PAGE_LIMIT`).
Those findings keep the award as evidence and attach a `PAGE_COVERAGE` concern to every stored
question, so an incomplete answer is reviewed instead of silently becoming an absent one. An
unmapped page is informative, not a concern, when every question has a mapping: a cover page
cannot hide a marked answer.

What is **not** established: the live Gemini provider is `UNVERIFIED`, the certified holdout
contains zero papers, and no marking-accuracy or production-readiness figure is supported. The
replay in [`experiment/paper01_engine_analysis`](../../experiment/paper01_engine_analysis)
measures the deterministic layer over preserved benchmark responses; it is not a live accuracy
measurement.
