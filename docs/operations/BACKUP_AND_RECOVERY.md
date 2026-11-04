# Backup and Recovery

**Status:** RECOMMENDED. Written around D1's real capabilities, including where they fall short.

## 1. What D1 gives us (VERIFIED)

| Capability | Reality |
|---|---|
| Time Travel (PITR) | 30 days (Paid) / 7 days (Free); restore to any minute |
| Restore behaviour | **Destructive and in-place** — overwrites the database, cancels in-flight queries |
| Restore rate limit | 10 restores per 10 minutes per database |
| Clone / fork | **Not available** (no clone or branch of a D1 database) |
| `d1 export` | Whole DB or single table; a running export **blocks other requests** on that database |
| Export limits | Not supported for FTS5 virtual tables; int64 values lose precision through JS |
| Cross-region copies | Not automatic |

Conclusion: **Time Travel is an undo button, not a backup strategy.** The backup strategy is scheduled exports
to R2 plus periodic verification.

## 2. Backup tiers

| Tier | What | Frequency | Retention | Store |
|---|---|---|---|---|
| B1 | Full tenant-aware SQL export (schema + data) | Daily 02:00 UTC | 14 days | R2 `backups/d1/YYYY-MM-DD/` (separate bucket) |
| B2 | Weekly full export | Weekly | 8 weeks | R2, different prefix |
| B3 | Monthly archive | Monthly | 12 months | R2 Infrequent Access |
| B4 | R2 file replication | Continuous (on write) | Life of object | Second bucket / location where available |
| B5 | Config as code | Every merge | Git history | Repository |
| B6 | Secret inventory (names only) | On change | – | Password manager, never R2 |

Exports run at low-traffic hours because they block the database; each export is verified by row counts per
table and a checksum, recorded in an `ops_backup_log` table (platform, not tenant).

## 3. Tenant-level restore (the common case)

A customer deletes 200 results by accident. We do **not** restore the whole database.

1. Identify the affected `workspace_id` and time window.
2. Pull the relevant table slice from the most recent export (`WHERE workspace_id = ?`).
3. Re-insert only the missing rows, in batches, guarded by primary keys (`INSERT OR IGNORE`).
4. Record the restore in the workspace audit log, visible to the customer.
5. Confirm with the customer which rows were restored.

Restoring **files** is separate: R2 objects are versioned by key prefix; a deleted object is recovered from
the replication bucket by re-putting the key and restoring the D1 reference row.

## 4. Full disaster recovery

| Scenario | Response | RTO | RPO |
|---|---|---|---|
| Bad deploy | Roll back Worker version | < 5 min | 0 |
| Bad migration | Forward fix; if impossible, Time Travel restore | 1–4 h | ≤ minutes |
| Accidental mass delete | Time Travel restore + replay audit | 2–6 h | ≤ 30 days window |
| D1 corruption / loss | New database from latest export, redeploy bindings, repoint | 4–8 h | ≤ 24 h |
| R2 bucket loss | Restore from replication bucket; verify file count | 4–12 h | ≤ 5 min |
| Region incident | Provider-level failover is limited (single-region D1 primary) | 8–24 h | ≤ 24 h |
| Total account loss | Rebuild from exports + config repo + secret inventory | 1–3 days | ≤ 24 h |

RTO/RPO are **targets**, not guarantees, and are only credible after a drill (see §6).

## 5. Deletion vs backup (a real conflict)

Customer deletes a workspace, but backups still contain it for 14–35 days. Resolution:

- The privacy policy must state that deleted data may persist in encrypted backups for a bounded period and
  is not restored except for disaster recovery.
- Backups are **not** browsable by support staff; restoring one requires an incident and is audited.
- On request, we do not selectively purge a tenant from immutable archives (technically impossible without
  rewriting archives); this is disclosed rather than promised.

## 6. Drills (non-negotiable)

| Drill | Frequency | Success criterion |
|---|---|---|
| Restore one table slice into staging | Monthly | Row counts match, app reads it |
| Full rebuild into a scratch environment from latest export | Quarterly | Sign-in + list + result read work |
| R2 object recovery | Quarterly | File hash matches original |
| Time Travel restore (staging) | Once, then after any D1 plan change | Database usable, bookmarks understood |

An untested backup is a rumour. The first drill must happen **before** the first paying customer.

## 7. Retention and cost note

Exports are small in this design (metadata only), which is what makes daily full exports affordable. Scripts
live in R2 and are replicated rather than exported; re-exporting terabytes of PDFs daily would be both slow and
unnecessary.

## 8. Ownership

| Responsibility | Owner |
|---|---|
| Backup schedule and verification | Platform operator |
| Restore decision (tenant vs full) | Incident commander |
| Customer communication | Workspace owner contact + support |
| Post-mortem | Incident commander within 5 working days |
