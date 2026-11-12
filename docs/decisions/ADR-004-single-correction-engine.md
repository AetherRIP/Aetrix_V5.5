# ADR-004 — One correction engine: `aetrix_v5_5`

**Status:** implemented
**Date:** 2026-11-12
**Supersedes:** ADR-003 (the two-engine seam) for the engine set only. ADR-002 and ADR-003
remain in place as the record of how the seam and the legacy default were chosen; their text
is not rewritten.

## Context

ADR-003 kept `aetrix_legacy` as the shipped default, `aetrix_v5_5` registered beside it and
`mathchecker_v5` as a registered placeholder that refused to mark. Three names, one working
engine, a registry, a configuration switch and a legacy marking package maintained only to
serve the adapter.

That arrangement was a migration scaffold, not a steady state. It cost a configurable
selection surface, a second marking implementation that duplicated the same per-question loop
without any of the V5.5 safeguards, and a placeholder that could be selected but could never
produce a mark. Operating one engine is simpler to reason about and cannot silently mark a
paper with a different methodology than the one reviewed.

## Decision

1. **One engine.** `aetrix_v5_5` is the sole correction engine. `AetrixEngine` is the only
   adapter; `AetrixPipeline` is the only marking pipeline.
2. **No selection.** `EngineSettings` and `Settings.engine` are removed. There is no registry,
   no `build_engine`, no accepted engine name and no fallback. `build_pipeline()` returns the
   one engine.
3. **The obsolete variable is refused at startup.** `AETRIX_ENGINE__CORRECTION_ENGINE` is no
   longer a settings field. A deployment that still sets it to anything other than
   `aetrix_v5_5` fails validation when settings are built, from the process environment or
   from `.env` / `backend/.env`. Accepting it silently would mark papers with an engine the
   operator did not select.
4. **Legacy code is deleted, not disabled.** The `app.marking` package, the
   `question_marking` prompt asset, the legacy state hook and the `mathchecker_v5` placeholder
   are removed. Nothing in the tree imports them; the V5.5 pipeline has its own strict schema
   and verification modules.
5. **Provenance is history, not configuration.** `engine_name`, `engine_version`,
   `requested_engine_name`, `requested_engine_version` and `engine_runs` keep their columns,
   their values and their meaning. No migration is added and no historical row is rewritten:
   a job marked by `aetrix_legacy` still says so.
6. **The attribution guard stays.** A job recorded as created or marked by another engine is
   still refused by the runner (`ENGINE_MISMATCH`) and by the adapter, so a historical
   `aetrix_legacy` row cannot be re-marked by V5.5 as a side effect of a retry.
7. **Safeguards are unchanged.** Mark integrity, targeted recovery, the independent double
   check, the result guard, `EngineRun` stages, explicit processing states, idempotency and
   tenant scoping are untouched.

## Consequences

- A deployment that ran the default `aetrix_legacy` now marks with `aetrix_v5_5`. This is a
  change to the marking path, not a no-op: the result guard can refuse to replace a stored
  result, recovery is budgeted, and the double check is available (still disabled by default).
- A deployment whose configuration still selects another engine does not start. That is the
  intended cost of removing selection; the fix is to delete the variable.
- A job still queued or pinned under `aetrix_legacy` is refused rather than marked with V5.5,
  and its recorded provenance stays readable.
- Fewer files, one marking implementation and one contract for the worker to satisfy.
