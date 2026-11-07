---
name: aetrix-verification
description: The exact verification gate for Aetrix changes, with commands, exit-status handling and the honesty rules for reporting results. Use before saying work is complete, fixed, passing or ready to commit, and when deciding which checks a given change actually needs.
license: Proprietary (Aetrix project skill)
metadata:
  author: Aetrix
  version: '1.0.0'
---

# Verification for Aetrix

Success is evidence, not assertion. Run the smallest set that actually covers the change,
and report exactly what ran.

## Toolchain quirks

- `node`, `npm`, `npx` and `python` are **not** on PATH in this workspace.
  Use `.tools/node/node.exe` and `backend/.venv/Scripts/python.exe` explicitly.
- The frontend build is prerendered: a build log ending in `[prerender] - /...` lines with
  exit 0 and 17 pages is the expected shape.
- The e2e suite needs a running server: start `vite preview --port 3000` first, confirm
  `curl -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/dashboard` answers, then run
  Playwright. A 307 to the trailing-slash URL is normal.

## Matrix

| Change | Minimum gate |
|---|---|
| Backend Python (any) | `python -m ruff check app tests` + affected pytest file(s) |
| Backend schema/migration | ruff + `pytest tests/unit -q` + `pytest tests/integration -q` with `AETRIX_TEST_DATABASE_URL` |
| Auth / tenancy / grants | the above **plus** `pytest tests/integration/test_rls_guard.py -q` |
| Frontend TypeScript/React | `tsc --noEmit` + `vite build` |
| Frontend routing/auth/UI flow | the above + `vite preview` + `@playwright/test test` |
| Styles only | build, then look at it at 1440 and 390 in both themes |
| Docs/copy only | re-read the claim against the status list in `aetrix-architecture` |

```bash
# backend
cd backend && .venv/Scripts/python.exe -m ruff check app tests
cd backend && .venv/Scripts/python.exe -m pytest tests/unit -q

# frontend
cd frontend && ../.tools/node/node.exe node_modules/typescript/bin/tsc --noEmit
cd frontend && ../.tools/node/node.exe node_modules/vite/bin/vite.js build
cd frontend && ../.tools/node/node.exe node_modules/@playwright/test/cli.js test
```

## Rules

1. **Preserve exit status.** When filtering output, use `set -o pipefail` or capture `$?`
   separately; a pipeline can hide a failure.
2. **Read failures.** Paste the real error, fix the cause. Never skip, xfail or relax an
   assertion, and never add a type/lint suppression to silence a real defect.
3. **Re-run what you changed.** A passing run from before your last edit does not count.
4. **Distinguish compiled from exercised.** "Typechecks and builds" is not "the flow works".
   Anything visual or interactive needs the browser or a screenshot.
5. **Report the gaps.** If a check could not run (no database, no network, no browser),
   say which and why. Never present it as a pass.
6. **No invented capability.** A green build says nothing about marking, the live provider
   or the unbuilt data screens.

## Before you write "done"

- State what you changed and which gate you ran, with the command and result.
- Confirm the change did not introduce a claim the repository cannot support.
- If you touched `benchmark/`, confirm frozen digests and scoring are unchanged.
- If you touched deployment config, confirm you did not deploy as part of verification.
