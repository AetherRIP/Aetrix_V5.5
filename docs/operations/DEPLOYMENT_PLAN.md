# Deployment Plan

**Status:** RECOMMENDED. Nothing here has been executed; no account, resource or domain exists.

## 1. Environments

| Env | Purpose | Data | Access | Deploy trigger |
|---|---|---|---|---|
| Local | Development on workerd | Seeded synthetic | Developer | `wrangler dev` |
| Dev | Shared integration | Synthetic | Team | Push to `main` |
| Staging | Pre-production verification | Synthetic, prod-shaped | Team + Cloudflare Access | Tag `rc-*` |
| Production | Customers | Real | Public | Manual approval after staging sign-off |

Rules: no production dump is ever copied downward; migrations run forward-only; every environment has its own
D1, R2, Queue and DO namespace.

## 2. Pipeline

```
push ──▶ install (lockfile, --frozen-lockfile)
     ──▶ typecheck (tsc --noEmit)
     ──▶ lint (eslint + custom rules: no env.DB outside data/, no secrets in DTOs)
     ──▶ unit tests (vitest)
     ──▶ integration tests (workerd + local D1/R2/Queues)
     ──▶ build (vite + worker bundle; size budget check)
     ──▶ e2e (Playwright against preview URL) + axe scans
     ──▶ deploy dev  ──▶ smoke
     ──▶ [tag rc] deploy staging ──▶ migration ──▶ smoke + seeded e2e
     ──▶ manual approval ──▶ deploy production ──▶ migration ──▶ smoke ──▶ monitor 30 min
```

Fail-closed: any red step blocks the deploy. A hotfix follows the same path with a shortened test set —
never a direct production upload.

## 3. Migration strategy (D1)

1. Migrations are numbered SQL files, applied by `wrangler d1 migrations apply`, never edited after merge.
2. **Expand → migrate → contract** for anything destructive:
   - expand: add nullable column/index (no table rewrite),
   - backfill in batches via Workflow (≤ 1,000 rows/statement),
   - contract: add constraint / drop old column in a later release.
3. Adding a `NOT NULL` column without a default on a populated table is **forbidden** — it rewrites the table.
4. Every migration is accompanied by a rollback note. D1 has no down-migrations; the rollback is a forward
   fix or a Time Travel restore (destructive, last resort).
5. Migrations are applied **before** the new Worker serves traffic only when they are backwards compatible;
   otherwise deploy Worker first (tolerant of both shapes), then migrate.

## 4. Release procedure (production)

| Step | Detail |
|---|---|
| 1 | Staging green for ≥ 24 h, seeded E2E passing |
| 2 | Change log entry drafted; migration list reviewed |
| 3 | Backup: export affected tables to R2 (see `BACKUP_AND_RECOVERY.md`) |
| 4 | Deploy Worker (versioned); keep previous version id recorded |
| 5 | Apply migrations |
| 6 | Smoke: signup, login, create assignment, upload, mark one fixture script, approve, publish (sandbox Classroom) |
| 7 | Watch error rate, p95 latency, queue depth for 30 min |
| 8 | Announce in `/changelog` |

**Rollback:** redeploy the previous Worker version (seconds). Database rollback is *not* symmetric — prefer
forward fixes; a Time Travel restore requires an incident commander and accepts data loss since the bookmark.

## 5. Configuration and secrets

- Non-secret config in `wrangler.toml` per environment; secrets via `wrangler secret put` and CI's secret
  store. Never in the repo.
- Required secrets: session signing key, credential encryption key, upload-signing key, AI provider keys
  (optional if workspaces bring their own), email provider key, Classroom client id/secret.
- Rotation: 90 days for platform keys; provider keys per workspace on demand; documented in the runbook.

## 6. Domains and DNS

- Apex and `app.` as **Custom Domains** (exact-hostname), `www` redirect rule, proxy enabled.
- `r2.dev` disabled. No wildcard DNS. Email authentication (SPF/DKIM/DMARC) for the sending domain.
- Preview URLs are protected by Cloudflare Access, not by obscurity.

## 7. Pre-launch checklist

- [ ] Threat model reviewed; criticals closed
- [ ] Isolation suite green in staging
- [ ] Restore drill completed (successful restore from export)
- [ ] Load test at 10× expected 10-workspace load
- [ ] Quotas and alerts configured; kill switch tested
- [ ] Runbooks written (incident, rollback, credential rotation, provider outage)
- [ ] Privacy policy, DPA, sub-processor list published
- [ ] Support inbox and status page live
- [ ] Backup schedule verified for 7 consecutive days
- [ ] On-call rotation defined and reachable

## 8. Rollout

1. Internal workspace only (dogfood) for 2 weeks.
2. 2–3 design-partner schools, white-glove onboarding, weekly review.
3. Open signup behind a waitlist; watch cost per script weekly.
4. General availability only after two consecutive clean months and a second restore drill.

## 9. Things that will bite (pre-emptive notes)

- Workers bundle size limit will be tested by PDF libraries; keep them out of the Worker.
- `wrangler` config drift between environments causes "works locally" incidents; config is code-reviewed.
- Queue consumer concurrency defaults can starve the provider rate limit; tune per workspace quota.
- DO migrations (class renames) are not automatic — plan a versioned class name if the schema changes.
