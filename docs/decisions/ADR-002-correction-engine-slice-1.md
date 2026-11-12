# ADR-002 — Correction engine ownership (Slice 1)

**Status:** implemented; superseded in part by ADR-003
**Date:** 2026-11-11

> ADR-003 records the engine set this seam selects: `aetrix_legacy` is the
> default and the only engine that marks, and `mathchecker_v5` is registered but
> raises `EngineNotImplemented`.  The seam, schema and safeguards recorded here
> still stand.

## Context

AETHRIX V5.5 already runs a real correction engine: per-question marking against
an approved blueprint, through an audited provider-call service, followed by
symbolic verification and human review/approval.  An earlier MIT-licensed
single-tenant desktop marking application supplied a methodology and several
safeguards that AETHRIX lacked, but it is a SQLite desktop application with
module-level singletons and a monolithic per-paper prompt.

Replacing AETHRIX's engine with that application wholesale would have discarded
tenant isolation, the PostgreSQL job/lease queue, the audit trail and the
existing review/approval records. Porting the safeguards into AETHRIX's engine
behind a seam delivers the behaviour without that loss.

## Decision

1. **AETHRIX owns the platform**: authentication, tenancy, jobs and leases,
   persistence, review, approval, audit, reports and notifications.
2. **An engine only marks a paper.** It receives a claimed job, its session and
   the settings, and returns a `PipelineOutcome`. It cannot transition a job,
   approve a result, or read another workspace.
3. **Selection is configuration.** `AETRIX_ENGINE__CORRECTION_ENGINE` accepts
   `aetrix_legacy` (default) and `mathchecker_v5`.  An unknown name is a
   configuration error, never a fallback, and a switch writes nothing.
4. **Every execution is recorded.** `correction_jobs.engine_name/engine_version`
   and an `engine_runs` row per stage say which engine and prompt produced a
   result, so switching back never rewrites history.
5. **Raw evidence is retained.** `question_results.raw_awarded_marks`,
   `normalised_awarded_marks`, `normalisation_anomaly`, `normalisation_detail`
   and `raw_response` keep what the model said when the engine changed the
   stored mark.
6. **Explicit processing state.** `processing_state` is one of `MARKED`,
   `CONFIRMED_ZERO`, `UNMARKED`, `NEEDS_REVIEW`. The API-facing `status` column
   is unchanged. The default engine writes the state in the same flush as
   `status`, from the single mapping in `app.correction.processing`, so the two
   columns cannot diverge on a committed row.

## Status mapping (historical rows and new writes)

| `status` | `processing_state` | Note |
|---|---|---|
| `AWARDED` | `MARKED` | a positive award was applied |
| `ZERO` | `CONFIRMED_ZERO` | only when `review_required` is false |
| `ZERO` + review | `NEEDS_REVIEW` | a zero nobody confirmed |
| `UNMARKED` | `UNMARKED` | no usable response |
| `REVIEW_REQUIRED` | `NEEDS_REVIEW` | awaiting a person |
| `EXCLUDED` | `UNMARKED` | not scoreable; `status` is kept as `EXCLUDED` |

Migration `0023_engine_provenance` backfills `raw_awarded_marks =
normalised_awarded_marks = awarded_marks` with
`normalisation_anomaly = 'LEGACY_BACKFILL'`, because the previous engine did not
retain the model's original value. Recording that gap is honest; inventing a
value would not be.

## Safeguards added in Slice 1

- **Targeted recovery** (`app/correction/recovery.py`): only questions with an
  unusable reply are retried, in chunks of at most six, within a budget recorded
  on `correction_jobs.recovery_rounds`. A gap covering ~the whole paper is
  refused as a failed run. A question that stays unresolved is `UNMARKED` with a
  stated reason — never a zero.
- **Mark integrity** (`app/correction/integrity.py`): deterministic checks for a
  negative award, an award above the maximum, a component total that contradicts
  the award, an award beyond the components' capacity, marks for a blank answer
  with no quoted evidence, and an awarded component worth no marks. Findings
  send the question to review; they never rewrite a mark and never claim
  mathematical correctness.
- **Result guard** (`app/correction/guard.py`): before a run's marks could stand
  as the submission's result, they are compared with the stored one. An approved
  result is never replaced (`BLOCKED`); a teacher override outranks the engine
  (`KEEP_EXISTING`); a zero where the stored run awarded marks, or a drop of 30
  percentage points or more, keeps the stored result and flags review.
- **Stale-write refusal** (`jobs/runner.py`): a write is applied only if the
  lease is still this worker's and `record_version` is unchanged since the claim.
  Refusals are audited as `job.stale_write_refused`.

## Consequences

- The default engine does not change in Slice 1; `mathchecker_v5` is selectable
  but refuses to run, so the seam is observable without pretending it marks.
- Recovery can re-mark a question whose only stored row is an unusable reply. It
  never touches `MARKED`, `CONFIRMED_ZERO`, or a review row created for a reason
  about the student's work.
- `grade_boundaries` exists but nothing reads it yet; grading remains out of
  scope until its own slice.
- Integration tests for these paths require a disposable PostgreSQL database
  (`AETRIX_TEST_DATABASE_URL`); the suite refuses to truncate anything else.
