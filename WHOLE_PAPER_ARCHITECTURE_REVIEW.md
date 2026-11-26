# Whole-paper marking — architecture review, revision 3 (final evidence reconciliation)

**Status:** read-only investigation, documentation only. No production code, prompt, migration,
database record, job, pilot file, provider setting or database state was modified, and no provider
request was made. All database access was `SELECT`/catalogue-read only; `alembic current` and
`alembic heads` were run and are non-mutating.

**Labels used throughout:** **VERIFIED** (observed in this database, repository or official provider
page), **DERIVED** (arithmetic on verified values), **ESTIMATE** (projection, method stated),
**ASSUMPTION** (unresolved).

---

## 0.1 Corrections carried forward from revision 2

| # | Revision 1 | Corrected |
|---|---|---|
| 1 | next migration `0027` | next free number is **0028**, and it must be a **merge** revision: the graph has two live branches (§1) |
| 2 | "39 requests/paper → five papers/day" | policy allows **4** more per-question papers today (162 of 200 left), and the provider allows **20 requests per key**, not per project (§2) |
| 3 | marking requests only | a clean per-question paper is **46** requests (7 mapping + 39 marking), worst case 90 (§2.6) |
| 4 | "raise the cap to 32768" | correct, but only feasible if evidence/reason are **bounded in the schema**; at the contract's own 2,000-char caps a paper needs up to 280k output tokens (§3.4) |
| 5 | fallback implied | seven explicit gates (revision 2 §8, retained in §4) |
| 6 | stages "unchanged" | verified call-by-call; plus **one live incompatibility found** in this revision (§1.5) |

## 0.2 Evidence obtained in this revision

| Evidence | Result | Status |
|---|---|---|
| `alembic_version` | `0027_transcription_checks` | VERIFIED |
| Migration sources present | trunk ends at `0026_verification_kinds`; **two** missing sources | VERIFIED |
| Bytecode of both missing revisions | recovered revisions, tables, columns, constraints, RLS | VERIFIED |
| Live schema of branch-X changes | 15 new columns + `transcription_checks` (17 columns, 40 rows) | VERIFIED |
| `ck_verification_results_kind` live | allows only `MATHEMATICAL`, `INTEGRITY`, `DOUBLE_CHECK` | VERIFIED |
| Code's verification kinds | includes `SCHEME_MATHEMATICAL`, `TRANSCRIPTION` | VERIFIED (source) |
| Pilot mapping ledger | 38 attempts, 2 credentials, 1 project label, 1×503, 1×429 | VERIFIED |
| Pilot documents | five scripts with page counts 7,7,7,7,8 = **36 pages** | VERIFIED |
| Selected marking model | `primary = gemini-3.6-flash`, updated 2026-11-11 | VERIFIED |
| `gemini-3.6-flash` limits | 1,048,576 input / **65,536 output** | VERIFIED (official model page) |
| Leaf JSON size under the production schema | 233 / 399 / 1,132 tokens by verbosity | DERIVED (computed) |

---

## 1. Migration recovery

### 1.1 The graph, reconstructed (VERIFIED)

```
5828eae7d57d  initial_schema
 └─ 2c331690c5f0  cp2_ingestion_provider_and_overrides
     └─ 0001_append_only → 0002_blueprint_guard_fix → 0003_identity_demo_tenants
        → 0004_audit_actor_label → 0005_rls_lockdown → 0006_provider_fleet
        → 0007_contributors → 0008_platform_owner → 0009_verification_grants
        → 0010_invitations → 0011_job_approvals → 0012_classes_students
        → 0013_service_heartbeat → 0014_validation_health → 0015_model_selection
        → 0016_platform_audit → 0017_classroom_allocations
        → 0018_provider_usage_diagnostics → 0019_classroom_oauth
        → 0020_google_cloud_quota → 0021_google_quota_reset_time
        → 0022_rls_security_tables → 0023_engine_provenance
        → 0024_double_check_verification → 0025_job_recovery_link
             │
             ├── 0026_verification_kinds        ← present in the repository, HEAD of the code
             │      (creates NO branch on the database)
             │
             └── 0026_scheme_criteria_approval  ← source missing; exists only as .pyc
                   └─ 0027_transcription_checks ← source missing; .pyc only; DB is stamped here
```

Both 0026 revisions declare `down_revision = "0025_job_recovery_link"`, so they are **siblings**, not
a chain. The repository therefore contains one branch; the database was migrated along the other.
`alembic heads` says `0026_verification_kinds (head)` because the file set contains only that branch;
`alembic current` fails outright:

```
Can't locate revision identified by '0027_transcription_checks'
```

No copy of either file exists anywhere in the workspace or in `git` history: `git ls-files` and
`git log --all -- '*0027*'` return nothing, and the two `.tmp` repository snapshots stop at 0025 and
0008. The only surviving artefacts are the `.pyc` files and the live schema.

### 1.2 `0026_scheme_criteria_approval` — exact effects (VERIFIED)

Recovered from bytecode constants and confirmed against `information_schema`:

| Table | Change | Type |
|---|---|---|
| `mark_scheme_versions` | `criteria_blueprint_version_id` | `uuid`, nullable, FK → `exam_blueprint_versions`, `ON DELETE SET NULL` |
| | `criteria_blueprint_hash` | `varchar`, nullable |
| | `criteria_approved_at` | `timestamp with time zone`, nullable |
| | `criteria_approved_by` | `uuid`, nullable, FK → `users`, `ON DELETE SET NULL` |
| | `criteria_approval_reason` | `text`, nullable |
| `marking_criteria` | `blueprint_version_id` | `uuid`, nullable, FK → `exam_blueprint_versions`, `ON DELETE CASCADE` |
| | `question_text` | `text`, nullable |
| | `expected_answer` | `text`, nullable |
| | `source_page` | `integer`, nullable |
| | `source_quote` | `text`, nullable |
| | index | `ix_marking_criteria_blueprint` |

Purpose (from the docstring's first lines): make the scheme reviewable and approvable as structured
criteria rather than only as an uploaded PDF, which is what a marking prompt needs.

### 1.3 `0027_transcription_checks` — exact effects (VERIFIED)

Creates `transcription_checks`:

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | uuid | NO | — (PK) |
| `tenant_id` | uuid | NO | — (FK tenants, CASCADE) |
| `job_id` | uuid | NO | — (FK correction_jobs, CASCADE) |
| `question_id` | varchar(40) | NO | — |
| `status` | varchar(20) | NO | — (`AGREES/DIFFERS/ABSENT/UNVERIFIABLE`) |
| `transcribed_answer` | text | YES | — |
| `transcribed_question_id_seen` | varchar(40) | YES | — |
| `quote` | text | YES | — |
| `legible` | boolean | NO | `true` |
| `confidence` | double precision | YES | — |
| `marker_answer` | text | YES | — |
| `provider` | varchar(40) | YES | — |
| `model` | varchar(120) | YES | — |
| `model_role` | varchar(20) | YES | — |
| `prompt_version` | varchar(80) | YES | — |
| `detail` | json | NO | `'{}'::json` |
| `created_at` | timestamptz | NO | `now()` |

Constraints: `pk_transcription_checks`, `uq_transcription_job_question (job_id, question_id)`,
`ck_transcription_checks_status`, `ix_transcription_checks_tenant_id`; RLS **enabled**, with
`REVOKE ALL ... FROM anon, authenticated`. **40 rows exist**, so this branch was used in practice.

### 1.4 Why the divergence happened

The tree's `models.py` maps neither the branch-X columns nor a `TranscriptionCheck` model: the current
ORM stores transcription verdicts as `VerificationResult(kind="TRANSCRIPTION")`. So branch X and the
current code are two **different implementations of the same feature**, forked at 0025. The database
kept branch X; the repository kept branch Y and a rewritten transcription path.

### 1.5 The live consequence (VERIFIED constraint + code; INFERRED failure)

The database's constraint is branch Y's *absence*:

```
ck_verification_results_kind CHECK (kind IN ('MATHEMATICAL','INTEGRITY','DOUBLE_CHECK'))
```

The current engine writes `MARKING_VERIFICATION_KINDS = ("INTEGRITY", "MATHEMATICAL",
"SCHEME_MATHEMATICAL")` (`pipeline.py:96-99`) and, when transcription is enabled,
`kind="TRANSCRIPTION"`. On this database, the first marking run that reaches
`_persist_verifications` with a `SCHEME_MATHEMATICAL` record will violate the CHECK and raise
`IntegrityError`.

`check_answer_against_scheme` returns `SKIPPED` only when the scheme states no expected answer, so on
a 39-question paper with an approved scheme this is effectively certain. **This is an inference from
the constraint definition and the code path — no marking run has been attempted on this database, so
it has not been observed.** It is also the most likely reason a resumed pilot would fail even after
the prompt-provenance issue is resolved.

### 1.6 Is reconstruction possible?

**Yes, to high fidelity**, because three independent sources agree:

| Source | Provides |
|---|---|
| `.pyc` bytecode constants | revision ids, table/column/constraint/index names, FK actions, RLS statements |
| Live `information_schema` / `pg_constraint` / `pg_indexes` / `pg_class` | exact types, lengths, nullability, defaults, constraint definitions, index definitions, RLS flags |
| The ORM and surrounding code | column semantics for the criteria-approval fields |

What cannot be recovered exactly: operation order inside `upgrade()`, the `downgrade()` body, and
comments/docstrings. None affects the resulting schema. The recovered pair must be validated by
applying it to a scratch database and diffing the result against the live schema.

### 1.7 Safe repair strategy

**Never** `alembic stamp` past the gap, and never delete the branch-X migration: 40 rows and 15
columns depend on it.

**Fresh database**

1. Restore both sources: `0026_scheme_criteria_approval.py`, `0027_transcription_checks.py`.
2. Keep `0026_verification_kinds.py` (needed by the code).
3. Two heads now exist. Add **`0028_merge_heads.py`**, a no-op revision with
   `down_revision = ("0026_verification_kinds", "0027_transcription_checks")`.
4. `alembic upgrade head` on a scratch database; diff the result against the live schema; the diff
   must be empty except for data.
5. Only then add `0029_whole_paper_marking.py`.

**Existing database (stamped `0027_transcription_checks`)**

1. Restore the two sources — `alembic current` resolves again.
2. `alembic upgrade head` applies `0026_verification_kinds` (the sibling branch) and then the merge.
   This is **required**, not optional: without it `SCHEME_MATHEMATICAL` verdicts cannot be stored.
3. Verify the new constraint directly (`pg_get_constraintdef`) before any job runs.
4. Take a schema dump before and after; the only change must be the widened `kind` constraint.

**Numbering.** `0028` = merge (no schema change). `0029` = whole-paper marking. If the team prefers
one revision, the merge may carry the whole-paper columns, but separating them keeps the repair
auditable on its own.

### 1.8 Effect on the pilot

The four parked jobs are unaffected by the repair itself. But **the engine cannot complete a marking
run on this database until `0026_verification_kinds` is applied** (§1.5). Restoring migrations is now
a prerequisite for pilot readiness, not merely for a fresh install.

---

## 2. Quota reconciliation

### 2.1 All 38 mapping attempts (VERIFIED, `provider_usage`)

Every attempt today is `gemini-3.6-flash`, `purpose=PAGE_MAPPING`, prompt `page_question_mapping:v1`,
project label `user-downloads-pool`.

| # | Time (UTC) | Key fingerprint | HTTP | Outcome | In | Out | Latency |
|---|---|---|---|---|---|---|---|
| 1–4 | 05:41:05 – 05:42:38 | `ef3ee6b22a48` | 200 | STOP | 1,545 | 37/34/37/41 | 8.7 / 30.1 / 35.6 / 23.1 s |
| 5 | 05:42:44 | `ef3ee6b22a48` | **503** | `ProviderServerError` UNAVAILABLE | — | — | 3.5 s |
| 6 | 05:43:11 | `ef3ee6b22a48` | 200 | STOP, `retry_count=1` | 1,545 | 37 | 24.9 s |
| 7–20 | 05:43:42 – 05:57:24 | `ef3ee6b22a48` | 200 | STOP | 1,519–1,571 | 26–59 | 12.1–84.6 s |
| 21 | 05:58:10 | `ef3ee6b22a48` | **429** | `ProviderQuotaError` RESOURCE_EXHAUSTED | — | — | 43.1 s |
| 22 | 05:59:03 | `92d6df4e3aec` | 200 | STOP, `retry_count=1` | 1,533 | 33 | 53.0 s |
| 23–38 | 05:59:37 – 06:05:15 | `92d6df4e3aec` | 200 | STOP | 1,533–1,545 | 14–59 | 3.3–70.9 s |

Totals: **36 successes, 2 failures, 2 retries**, 55,578 input + 1,312 output tokens, span
05:41:05–06:05:15 (24 min 10 s). Latency 3.3–87.2 s, mean ≈ 31 s. `finish_reason` is `STOP` on every
success — **the ledger already records finish reasons**, which the whole-paper design can rely on.

### 2.2 Reconciling "7 requests per document" with 38 attempts

The pilot's five scripts have page counts **7, 7, 7, 7, 8 = 36 pages** (VERIFIED, `documents` table).

```
36 pages (one per page, not per document)
+ 1 retry after the 503
+ 1 retry after the 429
= 38 attempts
```

So the estimate was wrong twice: one document has 8 pages, and retries are separate ledger rows. The
correct per-document figure is **ceil(pages) requests + retries**, i.e. 7.2 requests/document on this
paper, not a flat 7.

### 2.3 The quota unit — per key, not per project (VERIFIED behaviour)

`ef3ee6b22a48` was given **20 requests that reached the provider** — 19 succeeded and 1 returned a
503 — and the **next (21st) request was a 429**. Rotating to `92d6df4e3aec` restored capacity for 17
more. That is consistent with the catalogue's `_q(5, 250_000, 20)` — **20 requests per key per day,
5 per minute, 250k tokens per minute** — treating the 503 as a counted attempt.

Yet all 15 credentials share `project_id = 'user-downloads-pool'` (VERIFIED), which is an
operator-supplied label, not a Google Cloud project. The code counts quota **per project label**
(`CredentialPool._within_quota`) and enforces a **200/day** policy, while the provider allows **20 per
key**. The two models disagree in both directions:

| | Code's model | Observed provider behaviour |
|---|---|---|
| Unit | project label | credential (key) |
| Daily limit | 200 (policy) | 20 per key → 300 across 15 keys |
| Consequence | will hand out a key already at its limit | 429 forces rotation mid-run |
| Effect on a 39-request paper | treated as one 200-unit pool | needs ≥2 keys |

**Correction to revision 2:** the "3+ projects" figure came from the *benchmark* fleet
(`POOL_SHARED_1`, `POOL_OBSERVED_2/3`), not from this deployment. In this database there is exactly
one project label, so **no independent project-level quotas exist across these 15 keys**. Capacity
must be planned per key.

### 2.4 The two budgets, kept separate

| Budget | Value | Nature |
|---|---|---|
| Aetrix pool policy | 10 req/min, **200 req/day per project label** | operator policy (`QuotaSettings` defaults) |
| Provider allowance | 5 req/min, **20 req/day per key**, 250k tokens/min | observed today (20 successes → 429) and matching the 2026-11-10 inventory snapshot |

Effective daily ceiling for this fleet: `min(200 policy, 15 × 20 provider) = 200` requests — **policy
binds**, and it binds at the same place regardless of key count, which is precisely the flaw: the
policy ceiling is not derived from the provider allowance and will not move if keys are added.

### 2.5 What is actually left today

| Quantity | Value | Derivation |
|---|---|---|
| Attempts made | 38 (37 consuming, 1 × 503 non-consuming) | VERIFIED |
| Policy remaining (200/day, one label) | **162** | DERIVED |
| Provider remaining, per key | key A exhausted (20/20); key B 17/20 → 3; 13 untouched keys × 20 = 260; total **≈ 263** (and key A's 21st request was refused, so its 20 are spent) | DERIVED |
| Per-question papers left (39 marking + 7 mapping = 46 each) | policy: floor(162/46) = **3**; provider: floor(263/46) = **5** | DERIVED |
| Whole-paper papers left (1 + 7 = 8 each) | policy: **20**; provider: **32** | DERIVED |

Revision 2 said "4 papers" using marking requests alone. Counting the 7 mapping requests a new
document needs, the policy allows **3** more per-question papers today — one short of the five-student
pilot. Whole-paper mode allows 20.

### 2.6 Marking vs total pipeline requests (per paper)

| Stage | Per-question | Whole-paper |
|---|---|---|
| Page mapping (per document, once) | 7 | 7 |
| **Marking** | **39** | **1** |
| Recovery / fallback (gap guard caps at 34) | 0–34 | 0–34 |
| Double check (`BALANCED` / `ACCURACY`, if enabled) | 0–8 / 0–12 | same |
| Transcription (`BALANCED` / `ACCURACY`, if enabled) | 0–2 / 0–4 | same |
| Human review | 0 | 0 |
| **Clean paper, flags off** | **46** | **8** |
| **Worst case, `BALANCED`, all on** | **90** | **52** |

Recovery issues **one request per unresolved leaf**; the "chunk of 6" is a budget-accounting unit
(`job.recovery_rounds` increments per chunk), not a request count.

---

## 3. Output feasibility

### 3.1 The intended marking model (VERIFIED)

`provider_model_selections` contains exactly one row: `role='primary', model='gemini-3.6-flash'`,
updated 2026-11-11. `ProviderCallService._model_for` reads that row before the environment default, so
`gemini-3.6-flash` is the model the engine will call. The four parked jobs also record
`primary_model='gemini-3.6-flash'`.

### 3.2 Documented limits (VERIFIED, official model page)

| Limit | Value |
|---|---|
| Input tokens | 1,048,576 |
| **Output tokens** | **65,536** |
| Structured outputs | supported |
| Thinking | supported, billed against `maxOutputTokens` |

Locally, the ceiling is not recorded: `model_versions` is empty, and `model_inventory._text` passes
neither `context_window` nor `max_output_tokens`, so every `MODEL_RECORDS` entry has `None`.
`model_catalogue` can read `outputTokenLimit` from `models.list`, but nothing in marking consumes it.
A runtime gate therefore has to be added; it cannot be asserted from stored data today.

### 3.3 How truncation is exposed (VERIFIED, `providers/gemini.py:180-221`)

| Provider outcome | Code behaviour |
|---|---|
| `finishReason=MAX_TOKENS` **and zero content parts** | raises `ProviderTruncatedResponse` (a `ProviderResponseError`, **not** a transient subclass) → `ProviderCallService` maps it to `AppError(PROVIDER_UNAVAILABLE)` → `RetryablePipelineError` → job parked |
| `finishReason=MAX_TOKENS` **with partial text** | returns the partial text; `finish_reason` is carried on `LLMResponse` and written to the ledger — **and nothing in the pipeline checks it** |
| `SAFETY`/`RECITATION`/`BLOCKLIST`/`PROHIBITED_CONTENT` | raises `ProviderResponseError` |
| normal | returns text, `finish_reason="STOP"` |

The ledger proves the field is populated: all 36 successful mapping calls recorded `STOP`.

### 3.4 Validating 840 tokens per leaf (DERIVED)

Computed by serialising a leaf that satisfies the production `QuestionMark` contract (question id,
answer, award, components with code/description/marks/awarded/reason/evidence, confidence, page refs,
notes) and converting at ~3.5 characters per token:

| Leaf shape | Tokens/leaf | × 39 leaves |
|---|---|---|
| compact — 2 components, 60-char quote, 80-char reason | 233 | 9,081 |
| typical — 3 components, 120-char quote, 120-char reason | 399 | 15,567 |
| verbose — 5 components, 300-char quote, 300-char reason | 1,132 | **44,137** |
| worst — 6 components at the contract's 2,000-char caps | 7,172 | **279,719** |

Cross-check: benchmark Strategy A produced 11,371 output tokens for 38 items = **299 tokens/item**
*without* evidence quotes; production adds `marks`, `description` and a quoted `evidence` per
component, which is consistent with the 399-token "typical" row.

**Conclusion on the 840 estimate:** it is defensible **only if the prompt and schema bound supporting
text**. At the contract's own 2,000-character caps, one paper needs up to 280k output tokens — four
times the model's ceiling — so whole-paper marking is *impossible* without bounds, not merely tight.

**Required bounds:** `evidence` ≤ 200 chars, `reason` ≤ 200 chars, `description` ≤ 120 chars,
components ≤ 6 per leaf, expressed as `maxLength`/`maxItems` in `WHOLE_PAPER_RESPONSE_SCHEMA` and
repeated as an instruction in the prompt. That yields ≈650–840 tokens/leaf, so a 32,768 cap covers
39 leaves with ~2× headroom. The parser must still clip (it already does), but clipping after paying
is a cost failure, not a safety one.

### 3.5 Safe handling of partial, truncated and malformed responses

| Case | Handling |
|---|---|
| **Truncated, partial text** | detect `finish_reason == "MAX_TOKENS"` before parsing; salvage only brace-balanced, `QuestionMark`-valid items whose id is expected; persist salvaged leaves; send the rest to fallback; record `TRUNCATED_RESPONSE` with the cap, `finish_reason`, salvaged/missing counts; **never retry the whole paper** |
| **Truncated, no text** | `ProviderTruncatedResponse` → job parked with a reason naming the output budget; no rows written |
| **Malformed JSON** | request-level failure; no salvage attempt unless the brace scanner finds complete objects; fallback for all leaves |
| **Valid JSON, wrong shape** | request-level failure; fallback all |
| **Missing leaves** | leaf-level; fallback exactly those (§4) |
| **Invalid leaf** (no evidence on an award, bad confidence) | leaf-level; fallback that leaf |
| **Over-max award** | `OVER_MAX_AWARD` → stored 0 + review; **not** retried, because a second opinion cannot make an impossible award valid |

---

## 4. Fallback and persistence (condensed, unchanged from revision 2)

**Gates (all required):** G1 paper attempt persisted; G2 leaf has no scoreable row (absent or
`MODEL_RESPONSE_INVALID`); G3 leaf in this blueprint; G4 < 90% missing (≤34 of 39); G5 round budget
allows; G6 prompt asset stable; G7 job leased and not cancelled.

**Duplicate/conflict prevention:** unique `(job_id, question_id)`; read-before-write `_retryable`;
`existing=...` passed so a retry updates one row; `response_source`/`response_sequence` provenance;
`_discard` on cancel removes paper and fallback rows alike.

**Persistence:** parse and validate everything in memory, write all rows, **commit once**; the usage
row is already committed inside `ProviderCallService.call`, so cost survives a persistence failure.
`provider_responses` archives one body with its sha256; each row keeps its own slice.

**Prompt identity:** a separate asset id (`aetrix_v5_5_marking_whole_paper` v1); the stability check
must accept an allowed set of two identities.

**Stages:** `check_mark`, `check_against_scheme`, `check_answer_against_scheme`, `verify_question`,
`_recover`, `_transcribe`, `_double_check`, `_apply_guard` are all unchanged and all operate per row.
The only deliberate changes are the allowed-set stability check and new review-only findings.

---

## 5. Final architecture decision table

| Area | Decision | Evidence | Confidence | Prerequisite |
|---|---|---|---|---|
| **Migration repair** | Restore `0026_scheme_criteria_approval` and `0027_transcription_checks` from bytecode + live schema; add empty **`0028_merge_heads`** joining both branches; whole-paper becomes **`0029`**. Never stamp past the gap. | Graph, DDL, 40 rows and 15 columns recovered; `alembic current` fails today | **VERIFIED defect**, repair plan DERIVED | User authorization (migrations are read-only here) |
| **Verification-kind incompatibility** | Apply `0026_verification_kinds` to the live database before any marking run. | Live CHECK allows 3 kinds; code writes `SCHEME_MATHEMATICAL` and `TRANSCRIPTION` | VERIFIED constraint + code; failure INFERRED | Same repair as above |
| **Whole-paper implementation** | Add one paper request returning 39 items, bounded supporting text (evidence/reason ≤200, ≤6 components), cap 32,768, runtime gate on the catalogue's `outputTokenLimit`. Default `PER_QUESTION`; opt-in. | Model 1,048,576/65,536; leaf size 233/399/1,132 tokens; 840/leaf valid only with bounds | Design DERIVED; behaviour untested | Migration repair; new prompt asset; catalogue gate |
| **Atomic result persistence** | One transaction for all 39 rows, one archived body, per-row provenance (`provider_usage_id`, `response_source`, `response_sequence`). | 39 commits today; 32 KiB per-row raw cap | Design DERIVED | Migration `0029` |
| **Per-question fallback** | Retain the existing engine unchanged as the only fallback; seven gates; never re-mark a decided leaf; one request per unresolved leaf; gap guard at 34/39. | `_retryable`, `_recover`, `plan_recovery` | VERIFIED code path, reused | None (works today, subject to the kind constraint) |
| **Existing verification stages** | Keep all: integrity, scheme comparison, SymPy, verification records, double check, transcription, result guard, review routing. Only the prompt-stability check widens to an allowed set. | Call sites verified | VERIFIED | Constraint repair for `SCHEME_MATHEMATICAL` |
| **Pilot execution readiness** | **NOT READY.** Three independent blockers: (1) prompt v2 provenance mismatch parked the jobs; (2) `ck_verification_results_kind` rejects `SCHEME_MATHEMATICAL`, so a resumed run would fail at its first scheme-verified question; (3) only 162 policy requests remain today — 3 per-question papers, not 5. | §1.5, §2.5, parked jobs | Blocks 1–2 VERIFIED/INFERRED, 3 DERIVED | Repair migrations, resolve prompt provenance, then re-plan the run |

---

## 6. Unresolved assumptions

1. **Exact provider daily quota per key.** 20 successes then a 429 is consistent with 20/day, but one
   observation cannot distinguish "20/day" from "a burst window exhausted". Confirm with a fresh
   snapshot or a controlled probe (not performed here).
2. **Whether all 15 keys bill to one real Google project.** The label is identical for all 15, but a
   label is not a project id; the 429-then-rotate pattern suggests per-key allowances.
3. **Whether a reconstructed 0027 must match the original byte-for-byte.** Not required for schema
   correctness, but the original's `downgrade()` behaviour is unrecoverable.
4. **Whether `0026_verification_kinds` is the only difference the code needs.** It is the one that
   demonstrably conflicts; other branch-Y changes were not exhaustively diffed.
5. **Whole-paper accuracy.** Still unmeasured for production; the only frozen evidence is Strategy A at
   86.84% item-exact against an uncertified reference.
6. **Request byte size** for 7 PNG pages at 144 dpi: not measured. Must be measured before enabling,
   or transcoded to JPEG for request use.

---

## 7. Evidence index

| Claim | Source |
|---|---|
| DB revision `0027_transcription_checks`; `alembic current` fails | `alembic current`, `alembic heads`, `alembic_version` |
| Missing revisions' DDL | `migrations/versions/__pycache__/0026_scheme_criteria_approval...pyc`, `.../0027_transcription_checks...pyc` |
| Live branch-X schema | `information_schema.columns`, `pg_constraint`, `pg_indexes`, `pg_class` |
| `ck_verification_results_kind` contents | `pg_get_constraintdef` on `verification_results` |
| Code's verification kinds | `backend/app/correction/aetrix/pipeline.py:96-99` |
| 38 attempts, 2 keys, 1 project, 503 + 429 | `provider_usage` joined to `provider_credentials` |
| 36 pages (7,7,7,7,8) | `documents` / `document_pages` |
| Selected model | `provider_model_selections` |
| 65,536 output | `ai.google.dev/gemini-api/docs/models/gemini-3.6-flash` (official) |
| Truncation handling | `providers/gemini.py:180-221`, `providers/errors.py:84-93` |
| Row uniqueness, provenance columns | `db/models.py:499-547` |
| Recovery gates | `correction/recovery.py`, `pipeline.py:1129-1218` |
| 61 tenant question_results, none for the parked jobs, legacy rows `prompt_version IS NULL` | `question_results` |

No provider call was made; no file other than this document was written.
