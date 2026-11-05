# Aetrix V5.5 — consolidation report

**Date:** 2026-11-05
**Destination:** `AetherRIP/Aetrix_V5.5` (renamed from `AetherRIP/WebPage_UI_V5.5` on 2026-11-05)
**Source:** `AetherRIP/Engine_V5.5`

## 1. Pre-consolidation inventory

| Repository | Branch / HEAD | Working tree | Notes |
|---|---|---|---|
| `Engine_V5.5` | `main` at `5548762`; 5 commits ahead of `origin/main` | Clean; only ignored `.env`, `.venv`, caches, `.tools`, `backend/data` | Contains the Python engine, benchmark/holdout and engine docs |
| `WebPage_UI_V5.5` | `main` at `40770f4`; remote `feat/marketing-landing-foundation` at `22cd1dd` | Clean | Contains 60 planning/audit/remediation docs, `.agents` skills and no application code; the feature branch adds the marketing frontend |

No uncommitted work was present in either repository. The source repository was not changed.
The engine's ignored `backend/.env` and its local virtual environment were not copied.

## 2. What was consolidated

- `backend/` was copied from the engine's tracked tree, including application code, prompts,
  Alembic migrations, tests and `.env.example`.
- `benchmark/` was copied from the engine's tracked tree, including the frozen benchmark and
  holdout code, redacted fixtures, results and reports.
- The engine documentation was copied to `docs/engine/` so it cannot overwrite the destination's
  existing `docs/architecture`, `docs/audit` and `docs/remediation` set.
- The unmerged marketing frontend was fast-forwarded into the consolidation branch, then moved
  into `frontend/` as one coherent application directory.
- The old destination README and the marketing-branch README were preserved under
  `docs/history/` before the unified README replaced the front door.
- The Python `benchmark` extra (`sympy`) was added to `backend/pyproject.toml`; the root
  `.gitignore` now covers Python caches, the engine virtual environment and local data.

## 3. Deliberate exclusions

- `backend/.env` — contains a real database URL and configuration; never published.
- `.tmp_final/` — tracked temporary renders/scripts from the source repository; not part of the
  deliverable.
- `benchmark/final_tests/ch2-l3-final-01/source/*.pdf` — original student/scheme PDFs. The
  redacted page renders and evidence remain; the raw PDFs stay in the source repository.
- `.venv/`, `.tools/`, caches, bytecode, local storage and logs.

## 4. Architecture reconciliation

The destination planning set describes Cloudflare D1/Better Auth/R2/Queues. The implemented
engine uses PostgreSQL/Supabase and a Python worker. This is recorded as ADR-001 in the engine
set. The unified README and `docs/architecture/AETRIX_V5.5_SYSTEM.md` identify the engine as the
implemented authority; the older set is retained as history. No D1/R2/Queue binding was invented
for the marketing surface.

## 5. Repository identity

The project display name and package identity are **Aetrix V5.5**. The frontend package is
`aetrix-web`; the engine package is `aetrix-engine`. The GitHub repository was renamed from
`WebPage_UI_V5.5` to `Aetrix_V5.5` on 2026-11-05; the local `origin` was updated and remote
reachability was verified with `git ls-remote`.

## 6. Verification and commits

The final results, commands, commits and any blocked checks are recorded in
[`../audits/FINAL_VERIFICATION_REPORT.md`](../audits/FINAL_VERIFICATION_REPORT.md). This report is
not a substitute for that evidence.
