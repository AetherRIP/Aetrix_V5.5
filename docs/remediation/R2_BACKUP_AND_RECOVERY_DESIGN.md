# R2 Backup and Recovery Design

**Status:** RECOMMENDED. Supersedes `operations/BACKUP_AND_RECOVERY.md` §2–§3, which remains unmodified.
**Constraint honoured:** nothing here assumes R2 object versioning or native replication, because neither exists.

---

## 1. What R2 actually provides

Re-verified this phase against Cloudflare's documentation. The distinction between *native* and *built by us*
is the whole point of this document.

| Capability | Native? | Detail | Consequence for the design |
|---|---|---|---|
| Object versioning | **No** | `Get/PutBucketVersioning` are unimplemented; `R2Object.version` is a per-upload random string, not a retrievable version | History must be built as **new keys**, not as versions of one key |
| Cross-bucket replication | **No** | `Put/GetBucketReplication` unimplemented; "replication" in R2 means intra-region redundancy | We build the copy |
| Durability | Yes | 11 nines annual, synchronous writes | Protects against hardware, **not** against deletion — the docs say so explicitly |
| Event notifications | Yes (GA) | `object-create`, `object-delete`; target **Queues**; payload `{account, action, bucket, object{key,size,eTag}, eventTime}`; `size`/`eTag` absent on delete; overlapping rules rejected; ordering/at-least-once **undocumented** | Event-driven copy, but never trust the event as a change log |
| Server-side copy | Yes | `CopyObject`, `UploadPartCopy`; **Class A**, no egress, no Worker bandwidth; conditional-destination headers are beta and not atomic with source conditions | The copier moves **no bytes through a Worker** |
| Bucket locks | Yes (2025-03-06) | Prefix-scoped rules preventing delete **and overwrite**, up to 1,000 rules, strictest wins; 409 `ObjectLockedByBucketPolicy`; **no governance/compliance modes, no per-object lock, no legal hold** | Immutability for the backup prefix |
| Lifecycle rules | Yes | Expiration by days/date, transition to IA, abort incomplete multipart; **day granularity**; lock beats lifecycle | Retention in days, not hours |
| Whole-object checksum | Partly | `CRC64NVME` + `FULL_OBJECT` is the only whole-object digest for multipart; SHA-256 is **composite** for multipart; `CopyObject` cannot request a checksum | Verify with our own stored SHA-256, not with ETag equality |
| Managed backup | **No** | No snapshot, no restore product for R2 | Ours to build |
| D1 Time Travel | Yes | 30 days on Paid, **destructive in-place**, no clone/branch | The D1 half is PITR-plus-exports, not snapshots |

Two facts the original document got wrong and that shape everything below: **there is no undo for an overwritten
or deleted object**, and **"versioned by key prefix" is not a feature — it is what we must implement.**

---

## 2. Design

```
primary bucket  mc-files-{env}
   │  object-create ──▶ Queue  backup-events ──▶ copier Worker ──▶ CopyObject ──▶ backup bucket
   │  object-delete ──▶ (recorded, NOT propagated)                                  mc-files-backup-{env}
   │                                                                                 └─ lock: v1/ 90 days
   └─ nightly ListObjectsV2 reconciliation ──▶ missing objects enqueued for copy
```

**Three promises, stated precisely:**

1. **Every object written to the primary bucket is copied to the backup bucket within seconds**, and the copy is
   verified by size and by the digest recorded at upload.
2. **Deleting an object in the primary bucket does not delete the backup** for the retention period. This is what
   makes "a support engineer deleted the wrong prefix" recoverable.
3. **The backup is a copy of each object as of its copy time — not a consistent point-in-time snapshot.** Any
   claim stronger than that would be false.

### 2.1 Why not Worker byte-piping, and why not an off-provider copy

The original plan implied a Worker copying bytes. That would put 2.4 MB per submission — hundreds of GB per
month — through Worker duration for no benefit, and would fail outright on 200 MB multipart uploads.
`CopyObject`/`UploadPartCopy` is server-side, Class A-priced, and has no egress cost, so the copier is a control
plane, not a data plane.

An off-provider copy (S3/B2) is the only defence against account-level loss, and egress is free, so it is cheap.
It is **not** in the MVP because it adds a second vendor and a second credential set for a scenario the product
has not been asked to survive; it is recorded as the documented next step with its cost shape.

### 2.2 The copier

Triggered by a `backup-events` Queue message, one object at a time:

1. Parse `{bucket, object.key, object.size, object.eTag, eventTime}`; ignore any key not under `ws/`.
2. Compute `backupKey = v1/{yyyy}/{mm}/{dd}/{originalKey}` (UTC date of the event).
3. `HEAD` the source. If absent (deleted between event and processing), mark `state='source_missing'` and stop —
   the backup may still hold a prior copy, and restoring is a decision, not a reflex.
4. `CopyObject` from primary to backup with `metadata-directive: COPY`; for objects > 100 MB use
   `CreateMultipartUpload` + `UploadPartCopy` in 64 MB ranges.
   **Disable SDK default checksum headers** — several S3 SDKs send `x-amz-checksum-crc32` by default, which R2
   rejects; this is a known integration footgun, recorded so it is not rediscovered in production.
5. `HEAD` the destination; compare `Content-Length` and, for objects whose source digest is known, verify
   against `submission_files.sha256`.
6. Upsert `backup_objects`; on any failure, throw so Queues retries; after `max_retries`, the message lands in
   the DLQ and `state='failed'` with the error class.

Idempotency: `backupKey` is deterministic for a given object and day, so a duplicate event overwrites an
identical object. That is safe because the source object is immutable by design (§2.4).

### 2.3 Delete events

An `object-delete` event carries no `size`/`eTag`. The copier **records** it:

```sql
UPDATE backup_objects SET source_deleted_at = :eventTime
WHERE workspace_id = ? AND source_key = ? AND source_deleted_at IS NULL;
```

It never deletes the backup copy. Deletion of a backup object happens only by lifecycle expiry, and only after
the retention period. This inverts the failure mode from "unrecoverable" to "costs storage until retention
expires", which is the right trade for children's scripts.

**Documented limitation:** `object-delete` fires for `DeleteObject` and lifecycle deletion. A bucket emptied via
the dashboard or an object removed while no notification rule existed produces no event; that is why the nightly
reconciliation in §2.5 exists and why the backup is not described as a complete change log.

### 2.4 Why keys are immutable

`submission_files.r2_key` is `ws/{ws}/submissions/{sub}/ {fileId}` and a file is never rewritten in place: a
re-scan is a new `fileId`, a new object, a new row. That property is what lets the backup key be deterministic
without a version suffix, and it is worth stating as an invariant: **no process may `PUT` an existing key.** The
only exception is a presigned upload completing, which happens once per key by construction.

### 2.5 Reconciliation (the correctness backstop)

Nightly, per workspace prefix, paged `ListObjectsV2` compared against `backup_objects` for objects created in the
last 30 days:

- present in primary, absent in backup → enqueue for copy;
- present in backup, absent in primary → mark `source_missing` (do **not** delete);
- size mismatch → mark `state='drift'`, alert, re-copy.

Note the cost: `ListObjects` is a **Class A** operation, so the sweep uses large `max-keys` pages (1,000) and runs
once a day rather than hourly. Event-driven copying handles latency; reconciliation handles completeness.

### 2.6 Retention and lifecycle

| Prefix | Content | Lifecycle | Lock |
|---|---|---|---|
| `v1/` | Daily copies of every object | Expire at **90 days** | Bucket lock: no delete/overwrite for 90 days |
| `daily/` (primary bucket) | Not used — objects live at their own keys | — | — |
| `exports/` | Customer exports (not backups) | 7 days | — |
| `backups/d1/` | D1 SQL exports | 14 daily, 8 weekly, 12 monthly | Separate bucket `mc-d1-backup-{env}` |

The lock is what makes retention enforceable; lifecycle alone can be shortened by anyone with bucket-admin
rights. Lock rules are the only WORM-shaped primitive R2 offers, and there is **no governance bypass**, so the
period is a genuine commitment — hence 90 days rather than a year (`C6`).

---

## 3. Data model (platform tables, no `workspace_id` FK semantics beyond tenancy)

```sql
CREATE TABLE backup_objects (
  workspace_id      TEXT NOT NULL REFERENCES organization(id),
  source_key        TEXT NOT NULL,
  backup_key        TEXT NOT NULL,
  bytes             INTEGER NOT NULL,
  sha256            TEXT,                -- from submission_files.sha256
  state             TEXT NOT NULL CHECK (state IN
                      ('copied','verified','drift','failed','source_missing')),
  copied_at         INTEGER NOT NULL,
  verified_at       INTEGER,
  source_deleted_at INTEGER,
  error_class       TEXT,
  PRIMARY KEY (workspace_id, source_key)
);
CREATE INDEX idx_backup_state ON backup_objects(state, copied_at);
CREATE INDEX idx_backup_unverified ON backup_objects(copied_at)
  WHERE verified_at IS NULL AND state = 'copied';

CREATE TABLE ops_backup_log (
  id             TEXT PRIMARY KEY,
  kind           TEXT NOT NULL CHECK (kind IN
                   ('d1_export','file_verify','slice_restore','full_rebuild','object_recovery','migration_rehearsal')),
  started_at     INTEGER NOT NULL,
  finished_at    INTEGER,
  source         TEXT,
  rows_restored  INTEGER,
  objects_restored INTEGER,
  result         TEXT CHECK (result IN ('success','failure','partial')),
  notes          TEXT
);
```

`backup_objects` is capped by lifecycle at 90 days; a nightly prune removes rows whose `copied_at` is older than
the retention window **after** the objects are gone, so the manifest never claims a copy that no longer exists.

---

## 4. The D1 half

| Tier | What | Frequency | Retention | Where |
|---|---|---|---|---|
| D1-A | Full SQL export (schema + data) | Daily, 02:00 UTC | 14 days | `mc-d1-backup-{env}/backups/d1/YYYY-MM-DD/` |
| D1-B | Weekly full export | Weekly | 8 weeks | different prefix |
| D1-C | Monthly archive | Monthly | 12 months | Infrequent Access |
| D1-PITR | Time Travel | continuous | 30 days | platform |

Facts that shape this and were verified: `d1 export` **blocks other requests** on the database, so it runs in the
maintenance window; exports cannot include FTS5 tables (none are used); Time Travel restore is destructive and
in-place; there is no clone.

Each export writes `ops_backup_log(kind='d1_export', rows_restored=<total rows>, notes=<per-table JSON>)` plus a
`manifest.json` beside the SQL file with per-table counts and a schema digest. **An export without a manifest is
treated as a failed export**, because the restore tool needs counts to verify against.

---

## 5. Consistency between D1 and R2

The two are not transactional, and pretending otherwise is how restore operations corrupt data. The rule:

> **A file may exist without a row; a row must never exist without a file.**

Restore order is therefore: **objects first, then rows.** A row referencing a missing object is a broken record
the app cannot render; an object with no row is harmless garbage collected by the orphan sweep. The upload flow
enforces the same order — the object is uploaded, then the row is written by `POST /submissions` after a `HEAD`
confirms existence.

The export manifest carries `submission_files` rows with their `r2_key` and `sha256`, so a restore can verify
every referenced object exists in the bucket before it writes any rows.

---

## 6. Restore procedures

| Scenario | Procedure | RTO target | RPO |
|---|---|---|---|
| **One file deleted** | Look up `backup_objects` for the key; `CopyObject` back from `v1/…` (locked, intact); verify digest; re-point if the row is missing | < 15 min | ≤ copy latency |
| **Prefix deleted** | Same, enqueued per object from `backup_objects` where `source_deleted_at IS NOT NULL`; batch of 100 per Workflow step | 1–4 h | ≤ copy latency |
| **Rows deleted** | `slice` restore from the latest export: `WHERE workspace_id = ?` per table, `INSERT OR IGNORE`, batch 1,000; audit row visible to the customer | 1–2 h | ≤ 24 h |
| **Bad migration** | Forward fix; if impossible, Time Travel restore to a minute before the migration (destructive, needs an incident commander) | 1–4 h | minutes |
| **Database loss** | New database from the latest export + manifest verification, then re-point the binding in a deploy | 4–8 h | ≤ 24 h |
| **Total account loss** | Rebuild from exports (primary bucket may be gone; the backup bucket is in the same account) — hence the off-provider option in §7 | 1–3 days | ≤ 24 h |

**Restoring files requires an explicit operator action**, is executed by the copier (not by hand), and writes
both `ops_backup_log` and `platform_audit`. There is no "undelete" button in the product, deliberately: a
customer-visible undelete would turn a bounded retention window into a support contract.

---

## 7. Drills

| Drill | Frequency | Success criterion | Evidence |
|---|---|---|---|
| Verify 100 sampled objects (digest) | Weekly, automatic | 100 % match | `ops_backup_log` |
| Restore one object | Monthly | digest matches | `ops_backup_log` |
| Restore a tenant slice into staging | Monthly | row counts match manifest; app reads it | `ops_backup_log` |
| Full rebuild into a scratch DB | Quarterly | sign-in, list, result read all work | `ops_backup_log` |
| Time Travel restore (staging) | Once, then after any D1 plan change | database usable, bookmarks understood | `ops_backup_log` |
| Migration rehearsal on latest export | Every migration | completes within 50 % of the query budget | `ops_backup_log` |

**RTO is measured, then published.** The figures above are targets; the first drill's actual duration replaces
them in the operations document. A backup that has not been restored is a rumour, and a target that has not been
measured is marketing.

---

## 8. Alerts

| Signal | Threshold | Severity |
|---|---|---|
| `backup_objects` in `state='failed'` | any, after DLQ | P2 |
| `backup-events` DLQ depth | > 0 | P2 |
| Objects copied but unverified for > 24 h | > 50 | P3 |
| Reconciliation drift | > 0 | P2 |
| D1 export missing for a day | at 03:00 UTC | **P1** |
| `ops_backup_log` has no successful drill in 35 days | — | P2 |
| Backup bucket storage growth deviation | > 120 % of 7-day mean | P3 |
| Bucket lock rule absent | at deploy | **P1** (the lock is the retention control) |

---

## 9. Cost

Year-1 average at 100 workspaces (scripts ≈ 864 GB cumulative, average ≈ 432 GB):

| Line | Calculation | Monthly |
|---|---|---|
| Primary storage | 432 GB × $0.015 | $6.48 |
| Backup storage (90-day window ≈ 25 % of cumulative) | 108 GB × $0.015 | $1.62 |
| Copy operations | ~30 k objects/month × 1 Class A copy + 2 HEADs | < $0.50 |
| Reconciliation | 1 ListObjects page-set per workspace per day | < $1.00 |
| D1 exports | 14 × ~0.4 GB × Class A put | < $0.30 |
| **Total** | | **≈ $10/month** |

The honest comparison: replication adds **~25 %** storage at 100 workspaces, not 100 %, because retention is 90
days rather than forever. `COST-R` carries this line.

---

## 10. Failure modes this design does not fix

| Failure | Why not | Mitigation |
|---|---|---|
| Account deletion / compromise | Backup lives in the same account | Off-provider copy (documented, not built) |
| Ransomware with bucket-admin rights | Attacker can remove lock rules | Lock + scoped tokens + audit; a second account is the real fix |
| Backup object overwritten before its lock applies | Lock is prefix-scoped and applies at write; window is milliseconds | Deterministic keys per object mean an overwrite would be of an identical object |
| Region-level R2 outage during restore | Single-region bucket | Accepted; the primary bucket is equally affected |
| Silent bit rot | No R2-side scrubbing API | Weekly sampled digest verification |

These are stated because `BACKUP_AND_RECOVERY.md`'s original sin was claiming a capability the platform did not
have. The rule for this document: **if R2 does not do it, the document says we build it or that we do not have
it.**

---

## 11. What the original document said, and what replaces it

| Original claim | Status | Replacement |
|---|---|---|
| B4 "R2 file replication, continuous (on write), second bucket" | **False as written** | Built pipeline (§2), event-driven, verified |
| §3 "R2 objects are versioned by key prefix; recovered from the replication bucket" | **False** | Immutable keys + deterministic backup keys + 90-day lock |
| §4 "R2 bucket loss → restore from replication bucket, RPO ≤ 5 min" | Half true | RPO is copy latency for a single object; 24 h for a full bucket rebuild from a same-account copy is not a real recovery — stated |
| §6 "restore one table slice into staging, monthly" | Correct intent, no tooling | `backup-restore` CLI in P2, `ops_backup_log` per drill |
| §7 "exports are small, which makes daily full exports affordable" | Correct | Retained, now with a manifest and a verification tool |
| Deletion vs backup (§5) | Correct and important | Retained verbatim in spirit: bounded retention, disclosed, not browsable by support |
