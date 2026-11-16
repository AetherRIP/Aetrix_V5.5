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
submission whose assignment row predates review modes, so the two cannot silently disagree.
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
