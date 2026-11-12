# ADR-003 — Two engines: legacy default, V5 registered but not implemented

**Status:** implemented
**Date:** 2026-11-11
**Supersedes:** the single-engine ending state previously recorded under this ADR
number, and ADR-002 §"Consequences" where it described the engine set.

## Context

ADR-002 introduced a correction-engine seam and kept AETHRIX's existing
per-question marking pipeline as `aetrix_legacy`, with `mathchecker_v5`
registered but deliberately unimplemented.  Slice 1 of the approved plan stops
at exactly that point: seam, registry, legacy adapter, the additive provenance
migration and the safeguards — no default change and no replacement of the
working pipeline.

An intermediate state had collapsed the registry to a single `aetrix_v5_5`
engine and deleted the legacy package.  That is not the approved arrangement:
it changed the default, removed the working engine and made the V5
implementation the only path before its slice was reviewed.  This ADR restores
the two-engine seam and records it.

**Filename.** This decision was first filed as
`ADR-003-aetrix-v5-5-sole-engine.md`.  That revision recorded a single-engine
state this ADR reverses, so the file was renamed rather than keep a title that
would misstate the record.  No other file was removed by this change.

## Decision

1. **Two names, one working engine.** `AETRIX_ENGINE__CORRECTION_ENGINE`
   accepts `aetrix_legacy` (default) and `mathchecker_v5`.  Any other name is a
   `CONFIGURATION_ERROR`; there is no fallback and no alias.
2. **`aetrix_legacy` marks every paper.** Its adapter delegates to
   `app.marking.pipeline.QuestionMarkingPipeline`, restored from version control
   and unchanged in behaviour: same per-question idempotency, same review
   escalation, same retryable provider failures.
3. **`mathchecker_v5` refuses to mark.** It is registered and selectable, and
   raises `EngineNotImplemented`.  The runner records a failed job; no question
   result is written, so a half-built engine cannot look like a finished mark.
4. **The V5 implementation is not registered.** `app/correction/aetrix/`
   (pipeline, strict schema, verification, double check) and
   `AetrixEngine` remain in the tree for the slice that implements the
   `mathchecker_v5` slot.  Configuration cannot reach them yet.
5. **Selection is reversible by environment only.** Switching engines writes
   nothing and migrates nothing.  A job records `engine_name` and
   `engine_version` when it runs, and existing rows keep the engine that
   produced them; no stored result is rewritten to match a new setting.
6. **Provenance is recorded per execution.** `correction_jobs.engine_name` /
   `engine_version`, the per-question `engine_version` / `prompt_version`
   columns and `engine_runs` are unchanged from `0023_engine_provenance`.

## Safeguards that stay in place

`processing_state` (with its four values and the `status` mapping), the result
guard, bounded recovery, deterministic integrity checks, retained raw model
output with normalisation reasons, and the double-check verdict columns all
remain as built.

`aetrix_legacy` writes `status` and `processing_state` in the **same flush**.  A
session `before_flush` hook installed by its adapter sets `processing_state`
(and the per-question `engine_version`) from the single `STATUS_TO_STATE`
mapping that the `0023_engine_provenance` backfill also generates its SQL from:
`AWARDED → MARKED`, a `ZERO` that does not need review → `CONFIRMED_ZERO`,
`UNMARKED → UNMARKED`, `REVIEW_REQUIRED → NEEDS_REVIEW`, and `EXCLUDED →
UNMARKED` without rewriting its status.  Because the hook runs inside the flush,
a crash cannot leave a committed row with a status and no state.  A status the
mapping cannot express consistently makes the hook raise and aborts that flush,
so a NULL state or a contradicting claim is never persisted, and a failed or
retry-exhausted execution never turns an unresolved question into
`CONFIRMED_ZERO`.  The V5 pipeline writes the states itself when its slot is
implemented.

## Consequences

- The default configuration marks papers as it did before the seam existed.
- Selecting `mathchecker_v5` today fails the job with `EngineNotImplemented`
  rather than marking, which is the intended cost of shipping the slot early.
- A rollback is an environment change, not a code restoration, because the
  legacy package is present.
- Every new legacy result carries both `status` and `processing_state` in one
  flush, so the default engine satisfies the explicit-state rule without
  changing an award.
- Migration `0024_double_check_verification` was added during this campaign and
  lies outside Slice 1's chain, which ends at `0023_engine_provenance`.  It is
  retained, not deleted: removing it would require deleting the in-tree V5
  double-check implementation or leaving its `DOUBLE_CHECK` verdicts
  unpersistable.  It only widens two CHECK constraints on
  `verification_results`, rewrites no row, and has been applied to no project
  database.
- Prompt assets for both paths must exist: `question_marking` for the default
  engine, `aetrix_v5_5_marking` and `aetrix_v5_5_double_check` for the
  unregistered V5 implementation.
