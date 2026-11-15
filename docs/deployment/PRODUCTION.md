# Production deployment — Aetrix frontend

- **Production URL:** <https://aetrix.pages.dev>
- **Pages project:** `aetrix`
- **Source:** `AetherRIP/Aetrix_V5.5`, branch `main`
- **Last verified:** 2026-11-15
- **Serving commit:** pending the first publish of this runbook; confirm it in the
  Pages deployment record and the `Verify production deployment` workflow run.

This is the runbook for the public frontend. The FastAPI correction engine is not
hosted on Cloudflare Pages and has its own deployment and recovery instructions in
`docs/engine/architecture/DEPLOYMENT.md`.

## Topology

```text
GitHub main
  │
  ▼
Cloudflare Pages GitHub integration
  │  root: frontend
  │  build: npm ci && npm run build
  │  output: dist/client
  ▼
https://aetrix.pages.dev
  │  Supabase session and legal_acceptances
  ▼
FastAPI engine on the maintainer workstation (Tailscale Funnel, on demand)
```

Pages serves the static client. Supabase provides authentication and stores legal
acceptance rows. The correction engine is a separate process; when it is offline the
frontend must show its unavailable states rather than fabricated data.

## Deploy

1. Make the change on a branch, run the checks below, and merge it to `main`.
2. Pushing to `main` lets the Pages GitHub integration build and publish. Do not run
   a second upload for a routine release.
3. The [Verify production deployment](https://github.com/AetherRIP/Aetrix_V5.5/actions/workflows/verify-production.yml)
   workflow waits for the Pages deployment whose commit hash matches the pushed
   commit. It then checks the home page and all nine public legal routes. A failure
   means the deployment did not build, did not publish, or the live surface is wrong.
4. If the Pages build fails, open the project's deployment record, read the build log,
   fix the cause on `main`, and let Pages rebuild. Do not upload a hand-built `dist/`
   as the normal recovery path.

Pages reads these public build variables from the project environment (preview and
production are configured separately):

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_AETRIX_API_URL` — the public HTTPS engine origin, never a loopback address

The values must not be committed. A build without them would produce a sign-in page
that says authentication is unavailable.

## Verify

Local checks before pushing:

```bash
cd frontend
../.tools/node/node.exe node_modules/typescript/bin/tsc --noEmit
../.tools/node/node.exe node_modules/vite/bin/vite.js build
../.tools/node/node.exe node_modules/@playwright/test/cli.js test --reporter=line
```

The Playwright suite expects a preview on `http://127.0.0.1:3000`. Set `BASE_URL` to
point it at another origin. A production build must include the
`legal-clean-urls` step from `frontend/package.json`; do not replace the build command
with a bare `vite build`.

After publishing, confirm:

```bash
for path in / /sign-in /legal /terms /privacy /cookies /acceptable-use \
  /ai-disclosure /copyright /security /account-deletion; do
  printf '%-24s ' "$path"
  curl -sS -o /dev/null -w '%{http_code}\n' "https://aetrix.pages.dev${path}"
done
```

All should return `200`. Also confirm the Pages deployment's commit hash is the commit
you pushed and that the page title is the Aetrix shell. A deployment receipt alone does
not prove the site renders correctly; inspect the live home and sign-in pages.

The engine check is separate. `/health` and `/ready` on
`arthur-rip-zn02.tail06bb75.ts.net` currently fail DNS resolution. Start the workstation
stack with `START_AETRIX.bat`, check it with `STATUS_AETRIX.bat`, and remember that a
working demo engine is not an accuracy claim or a 24/7 service.

## Rollback

1. Revert the offending commit on `main` so Git history records the correction.
2. Let the Pages GitHub integration rebuild the revert.
3. If the integration cannot rebuild, use the Pages dashboard to roll back to the last
   known-good deployment, then still land the Git revert.
4. Re-run the production verification workflow and the URL checks above.

Do not rewrite `main` or force-push to recover a release. Do not delete the Pages
project or its environment variables to roll back.

## Emergency manual publish

Use this only when the GitHub integration is unavailable. It builds the same
`frontend` output and uploads it to the same project:

```bash
cd frontend
npm ci
npm run build
npm run deploy:manual
```

The command requires a Cloudflare API token with Pages edit access and the account id
in the local environment. It is not a routine deployment path and it does not satisfy
the commit-matching verification by itself; check the live routes manually and restore
the GitHub integration before the next release. `wrangler deploy` is not used.

## Known limitations

- Cloudflare Pages cannot host the Python/FastAPI engine. The demo backend depends on a
  workstation and its tunnel.
- The demo engine hostname is currently unresolved; engine-backed screens show explicit
  unavailable states until the stack is restored.
- There is no custom domain. The production origin is `aetrix.pages.dev`.
- Google OAuth still needs its matching Supabase provider client before an interactive
  consent round trip can be called complete.
- Legal acceptance is stored in Supabase and enforced by the authenticated gate. A
  failing legal read closes the workspace rather than assuming consent.
- The project is pre-release; see the root `README.md` for the current claim boundaries.
