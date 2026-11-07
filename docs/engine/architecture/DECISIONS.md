# Architecture Decision Records

Status: **Accepted** unless stated otherwise.
Scope: Aetrix V5.5 correction engine, Checkpoints 1-2 (Phases 0-2).
Format: context → decision → consequences. ADRs are immutable once accepted; a later ADR supersedes an earlier one explicitly.

---

## ADR-001 — Supabase/PostgreSQL is the platform; the D1/Better Auth plan is deferred

**Context.** `UI_Webpage_V5.5` specifies Cloudflare Workers, D1, R2, Queues and Better Auth. The approved V5.5 brief specifies a Python engine with Oracle-portable application code, Supabase PostgreSQL/Auth/Storage and a Cloudflare frontend. The two cannot both be the backend of record.

**Decision.** The brief governs. The engine is Python + FastAPI + SQLAlchemy/Alembic + PostgreSQL (Supabase). Supabase Auth issues JWTs; the engine verifies them. Supabase Storage is the target document store. The D1/Better Auth design is not implemented. Frontend work is withheld until the conflict is reconciled.

**Consequences.**
- One authoritative persistence and auth model for the engine.
- The UI repository's data model, auth flow and Worker assumptions cannot be copied unchanged.
- A future frontend can be Cloudflare-hosted, but it must call this API and use Supabase-issued tokens.
- Reopening this decision requires a superseding ADR and an owner decision.

---

## ADR-002 — The engine lives in `backend/`; `benchmark/` is frozen

**Context.** The workspace contains a working benchmark harness whose scoring was pre-registered. Importing it from production would couple the engine to measurement code and make the frozen digests unstable.

**Decision.** The engine lives under `backend/`. Production code must not import `benchmark/`. The benchmark's seven frozen digests and scoring rules are not edited. Benchmark tests are run unchanged as a regression gate.

**Consequences.**
- Clear separation between measurement and product.
- Some concepts are duplicated deliberately (for example, retry classification) rather than imported.
- A change that requires editing the benchmark is out of scope for an engine checkpoint.

---

## ADR-003 — PostgreSQL only; SQLAlchemy 2.0 + Alembic; real row locking

**Context.** V5 used SQLite. The V5.5 brief requires a production database, real concurrency and Oracle portability. A local PostgreSQL server and Docker are unavailable on this machine.

**Decision.** PostgreSQL via Supabase is the integration target. SQLAlchemy 2.0 and Alembic own the schema. The worker claims jobs with `FOR UPDATE SKIP LOCKED`. SQLite is rejected by configuration at startup; there is no SQLite production path.

**Consequences.**
- Integration tests require a real PostgreSQL URL; they are not mocked on SQLite.
- The direct Supabase host is IPv6-only here; the session pooler is the supported connection path.
- The schema uses portable SQLAlchemy types. JSON maps to `json` on PostgreSQL and would map to a LOB on Oracle; an Oracle migration pass is still required.
- Supabase currently provisions PostgreSQL 17.11, not 15. The version difference is recorded rather than forced.

---

## ADR-004 — The blueprint is canonical, approved, immutable and gating

**Context.** V5's blueprint is best-effort, cached by file SHA outside the database, may silently fall back to `None`, and has no approval, versioning or audit. The brief's premise that the blueprint is never passed is only true for one V5 path.

**Decision.** A blueprint is a tenant-owned `exam_blueprint_versions` row. Drafts are created explicitly. Approval promotes only the exact stored draft (content hash must match) and supersedes the previous approved version. Approved versions are immutable. An assignment may reference only an approved blueprint, and a correction job stores the exact blueprint version id and content hash. The blueprint gates marking.

**Consequences.**
- A teacher cannot approve content they did not see.
- Re-marking a paper uses the same immutable contract, not a re-extracted file.
- Superseded versions remain readable for provenance.
- The marking pipeline must consume the stored structure; it may not re-derive it silently.

---

## ADR-005 — Provider independence; prompts are versioned assets

**Status:** Principle remains accepted; the “later phase” implementation clause
is completed by ADR-016 and ADR-017.

**Context.** V5 is coupled to the Google SDK and embeds prompt text in code. The brief requires provider independence and versioned prompts.

**Decision.** A `LLMProvider` protocol defines the provider boundary. A real Gemini adapter will implement it in a later phase. Prompts are files with ids and versions, recorded in `prompt_versions`; they are not embedded string literals. Model roles and provenance are recorded in `model_versions`.

**Consequences.**
- Swapping providers does not require rewriting the marking pipeline.
- Prompt changes are reviewable and attributable.
- Phase 1 ships no provider adapter; the pipeline is explicitly unavailable rather than mocked.

---

## ADR-006 — One primary correction, deterministic validation, selective review

**Context.** Blanket double-marking is expensive and does not by itself improve accuracy. The brief prioritises marking accuracy over speed and API cost, but forbids indiscriminate second marking.

**Decision.** Every question gets one primary AI correction. Deterministic validation runs on every result. A second, independent review is requested only when a named trigger fires (low confidence, verifier disagreement, scheme concern, integrity flag, quota policy). Review budgets are bounded by mode: ECONOMY, BALANCED, ACCURACY.

**Consequences.**
- The review budget is explainable per question.
- The engine must record the review reason and whether the reviewer was blind.
- Phase 1 stores the review tables but implements no reviewer.

---

## ADR-007 — Marks must be evidence-bound; no invented answers or marks

**Context.** A plausible explanation without evidence is worse than an honest "review required". The benchmark's criterion metrics penalise false awards and false deductions.

**Decision.** A question result must carry the student's answer/working evidence and criterion-level decisions. Missing pages, source mismatches and unprinted questions are explicit states, not zeros. Verification returns EQUIVALENT, DIFFERENT or UNKNOWN; UNKNOWN never silently becomes DIFFERENT. A result that cannot be supported is marked REVIEW_REQUIRED or UNMARKED, not guessed.

**Consequences.**
- More review work is possible; that is accepted.
- Evidence and verification tables are part of the schema from Phase 1.
- The pipeline cannot complete a job with fabricated results.

---

## ADR-008 — Tenant isolation is enforced in repositories and the schema, not RLS

**Context.** Supabase offers row-level security for PostgREST access. The engine connects directly with a database role, so RLS would not automatically protect its queries.

**Decision.** Every tenant-owned table carries `tenant_id`. Repositories require the tenant id and filter on it. Cross-tenant reads return 404. Tests exercise isolation through both services and the API. The schema uses foreign keys and indexes to make the tenant path explicit.

**Consequences.**
- A missing tenant filter is a code-review defect and a test failure.
- RLS may still be added as defence in depth for direct Supabase clients, but it is not the primary control.
- A future repository helper must not expose an unscoped `get(id)`.

---

## ADR-009 — Jobs are persistent, leased and idempotent

**Context.** A correction can outlive an HTTP request and a worker process. Retrying a request or a crashed job must not double-mark or lose work.

**Decision.** Correction jobs have 13 states with guarded transitions, an optimistic `record_version`, a tenant-scoped idempotency key bound to a request hash, a lease with heartbeat, an attempt budget and crash recovery. The API creates jobs; a separate worker process claims them. Cancellation is terminal and clears the lease. `RETRY_SUSPENDED` is a deliberate parking state, not a failure.

**Consequences.**
- Duplicate POSTs return the same job.
- A killed worker's job is reclaimed after lease expiry; repeated crashes exhaust the attempt budget and fail the job.
- The API and worker can be deployed and restarted independently.
- The pipeline must be checkpoint-idempotent before partial results are reused (Phase 5).

---

## ADR-010 — Audit, job events and provider usage are append-only

**Context.** Marking decisions must be explainable after the fact. A mutable audit table is not evidence.

**Decision.** `audit_events`, `job_events` and `provider_usage` reject `UPDATE` with a database trigger. Audit rows carry actor, action, entity, before/after content hashes and request id. Approved blueprint versions are immutable by service rule. Deletion is still possible for retention and tenant removal; the guard is against rewriting history.

**Consequences.**
- Corrections cannot quietly rewrite their own trail.
- Corrections are made by appending a new event or a new job, not by editing a row.
- Retention tooling must be explicit about deletion.

---

## ADR-011 — Secrets are encrypted and development auth is refused in production

**Context.** V5 stores provider keys and OAuth client secrets in plaintext files on disk. The engine will hold provider credentials.

**Decision.** Provider credentials are encrypted at rest with Fernet; only a fingerprint is stored in plaintext. The encryption key comes from `AETRIX_SECURITY__ENCRYPTION_KEY`. Production refuses development auth, the development encryption key, SQLite and wildcard CORS. Database and provider credentials live in an untracked env file or a secret store, never in git or logs.

**Consequences.**
- A leaked database dump does not directly expose provider keys.
- Rotating the encryption key requires a re-encryption procedure (not yet implemented).
- A missing key is a boot failure, not a silent fallback.

---

## ADR-012 — Frontend implementation is out of scope for Checkpoint 1

**Context.** The UI repository contains planning only, and its architecture conflicts with the approved backend. Building UI now would encode unresolved decisions.

**Decision.** No frontend code is copied or written in this checkpoint. The API contract is documented and stable enough for a frontend to consume, but the D1/Better Auth conflict and the 16 owner decisions remain open.

**Consequences.**
- The checkpoint stays backend-focused and verifiable.
- Frontend work needs a reconciliation ADR and owner decisions before it starts.

---

## ADR-013 — Phase 1 ships an unavailable pipeline, not a fake one

**Context.** The marking pipeline does not exist yet. A stub that returns zeros or canned marks would contaminate every downstream metric and violate the no-fake-implementations rule.

**Decision.** `UnavailablePipeline` raises `PipelineUnavailable`. The worker catches it and parks the job in `RETRY_SUSPENDED` with `PIPELINE_UNAVAILABLE`. No question results are written. A manual retry is required after the pipeline exists. Tests inject the unavailable pipeline explicitly; they do not use it as a production mark.

**Consequences.**
- The job infrastructure is testable without pretending marking works.
- A created job is visibly incomplete, with a reason.
- Phase 5 replaces the pipeline behind the same protocol; the runner does not change.

---

## ADR-014 — Live provider verification is bounded and never simulated

**Status:** The live probe was executed but the post-change provider path is
**UNVERIFIED**: two keys returned 503 and two returned 403. See
`docs/audits/CP2_ACCEPTANCE.md`. The bound and no-simulation rule still apply.

**Context.** Provider keys, quota and model names can fail independently of the engine. A simulated success would hide that.

**Decision.** When the provider adapter is built, one bounded smoke run (≤6 requests, ~$0.05) may use V5's authorized key file read-only. Keys are never copied, logged or echoed. If quota, keys or network fail, the result is reported unverified.

**Consequences.**
- Phase 1 makes no live-provider claim; it has no adapter.
- Provider work cannot be marked complete on a mock alone.
- Cost is bounded and observable.

---

## ADR-015 — Fixture exceptions stay fixture-scoped

**Context.** `ch2-l3-final-01` has specific anomalies: Q12 source mismatch, Q16d not printed, and Q30/Q31/Q34 "Working required" policy. It also has two candidate references (76/87 and 80/87).

**Decision.** These exceptions are recorded against the fixture and the evaluation harness, not as global engine rules. The engine may expose policies (for example, a scheme's working-required flag), but it must not hardcode this paper's answers.

**Consequences.**
- A second paper cannot inherit this paper's quirks.
- Global accuracy claims remain unsupported until the holdout has certified papers.

---

## ADR-016 — The provider boundary is real, narrow and quota-aware

**Context.** Checkpoint 1 defined a protocol but shipped no adapter. Checkpoint 2
needs model calls for blueprint extraction and image fallback mapping, while V5's
provider coupling and global retry state must not be carried over.

**Decision.** `LLMProvider` is the only dependency the services see. The Gemini
adapter is a REST implementation in `app/providers/gemini.py`; it uses `httpx`, not
the Google SDK, and translates the wire format into provider-neutral dataclasses.
Every call goes through `ProviderCallService`, which leases a credential, creates
a durable quota reservation, records a `provider_usage` row for success or
failure, and applies typed retry behavior:

- 401/403 invalidates the credential and excludes it for the rest of the call;
- 429 cools the credential down and excludes it;
- 5xx/timeout is retried without permanently excluding the key;
- 4xx request errors are not retried unchanged;
- unknown prices produce `NULL` cost, never a fabricated zero.

**Consequences.**
- No provider SDK object, exception or response type crosses the boundary.
- A failed attempt is auditable, not silently discarded.
- A future provider implements the same protocol without changing extraction or
  mapping services.
- Provider cost and quota are per-call facts rather than in-memory counters.

---

## ADR-017 — Prompt assets are content-addressed and version-pinned

**Context.** Embedded prompt strings cannot be reviewed as a unit and can change
without leaving a reliable provenance trail. V5's prompt behavior was coupled to
code and configuration.

**Decision.** Prompts live under `backend/prompts/` and are listed in
`manifest.json` with an id, positive integer version, model role, path and
SHA-256. The registry refuses a file whose content does not match its manifest
hash, and refuses an unknown id/version. Every provider call resolves the asset
before the call, records the exact prompt id/version/hash in `prompt_versions`,
and links the usage row to that version.

**Consequences.**
- A prompt edit requires a new version and a new hash; a silent content change
  fails to load.
- The database can answer which prompt produced a usage row.
- Prompt review is a file review, not a search through Python strings.
- Old prompt versions remain recorded even when a newer one becomes the default.

---

## ADR-018 — Ingestion is synchronous, validating and non-destructive

**Context.** Uploaded answer scripts can be empty, mislabeled, corrupt, encrypted,
oversized, rotated, blurred or out of order. Silently dropping a page or assuming
the PDF order is correct would make later marking unexplainable.

**Decision.** Ingestion validates signature, declared type, extension, size,
page/image limits and integrity before storage. Accepted files are stored through
the `Storage` protocol, rendered page-by-page to PNG, checksummed, assessed for
quality and order, and persisted with every page. Rejected files are persisted as
`REJECTED` documents with typed code/message/severity reasons and an audit event;
they are never silently discarded. Quality and ordering are advisory statuses plus
reasons, not automatic deletion.

**Consequences.**
- A teacher can see exactly why a page is `LOW_QUALITY`, `ROTATED`, `EMPTY` or
  `ORDER_SUSPECT`.
- A page with no readable number makes the document `UNVERIFIED`, not `ORDERED`.
- Ingestion is synchronous in this checkpoint; a long PDF can hold the request.
  A background job is a later scaling change, not a hidden stub.
- Local filesystem storage is the current adapter; the protocol is the seam for
  Supabase Storage.

---

## ADR-019 — Extraction is draft-only; overrides create new versions

**Context.** A model-extracted blueprint is untrusted content. Letting it become
approved, or mutating an approved blueprint in place, would bypass the teacher's
review and destroy provenance.

**Decision.** Extraction has exactly one canonical write path:
`BlueprintService.create_extracted_draft`. It always writes `DRAFT`, records the
source document, prompt id/version/hash and usage id, and returns it for teacher
review through the existing save-then-approve gate. Teacher overrides copy the
base structure, apply typed operations, create a new `DRAFT` version and a
`blueprint_overrides` row with author and rationale. The database trigger rejects
structural mutation or status regression of `APPROVED`/`SUPERSEDED` versions.

**Consequences.**
- Extraction cannot approve a blueprint, even if the model says it is complete.
- An override never edits the base version; the base remains readable.
- Approval still requires the exact stored draft content hash.
- A rejected model output leaves a usage row but creates no blueprint version.

---

## ADR-020 — Mapping requires an approved blueprint and prefers deterministic labels

**Context.** Page-to-question mapping is the bridge between document pages and the
canonical marking contract. A model guess must not become a mapping silently, and
a mapping must not target a draft blueprint.

**Decision.** Mapping loads a tenant-scoped document and blueprint version, rejects
the request unless the blueprint is `APPROVED` and belongs to the document's exam,
and tries text-label matching first. Only pages without a usable label may use the
model fallback. Model identifiers are validated against the approved blueprint's
identifier set. Every page that cannot be mapped gets a typed `NO_QUESTION_MATCH`
reason; the document records `MAPPED`, `PARTIAL` or `UNVERIFIED`. Mapping writes
require an exam manager.

**Consequences.**
- A draft blueprint cannot drive page mapping.
- A model cannot invent an identifier outside the approved contract.
- Unmapped pages are visible in the API, not omitted.
- Mapping is not an accuracy claim; it is evidence for a later marking phase.

---

## ADR-021 — Structured output is requested at the wire level and parsed defensively

**Context.** The first live probe returned a prose preamble (`Here is the JSON
requested`) instead of an object. Prompt wording alone is not a reliable JSON
contract, and a model can still wrap a valid object in a fence or commentary.

**Decision.** For extraction, the Gemini adapter sends
`responseMimeType: application/json` together with `responseJsonSchema`; it does
not send the legacy `responseSchema` field. Response parts marked `thought: true`
are skipped. The response goes through `parse_json_text`, which accepts a clean
JSON string, a balanced object/array, or an object embedded in prose or a
Markdown fence, without repairing malformed JSON. Canonical
`BlueprintStructure` validation remains the final gate; parse or schema failure is
`EXTRACTION_INVALID`.

**Consequences.**
- JSON compliance is requested in the wire protocol, not only in the prompt.
- A prose preamble or fence no longer causes a spurious extraction failure.
- Malformed JSON is still rejected; the parser does not guess or patch content.
- The tolerant parser is shared by extraction and mapping response handling.

---

## ADR-022 — Credentials referenced by append-only usage are neutralised, not deleted

**Context.** `provider_usage` rejects `UPDATE` by trigger. Deleting a credential
with usage rows causes the `ON DELETE SET NULL` foreign key to issue an update,
which the guard rejects.

**Decision.** An ephemeral or retired credential that has been used is disabled
and its ciphertext replaced with an encrypted empty string. The credential row is
retained so the append-only usage row keeps its provenance. A future archival or
retention procedure must handle both tables deliberately.

**Consequences.**
- A used credential cannot be deleted through the ordinary ORM path.
- No reusable provider secret remains in the disabled row.
- Usage history stays intact and auditable.
- Test fixtures and acceptance scripts must neutralise, not delete, used
  credentials.

---

## ADR-023 — Keys belong to contributors; capacity still belongs to projects

**Context.** The Gemini fleet will draw free-tier keys from several independent individuals, not from one operator. A flat credential list cannot say who lent a key, whether they still consent, or whose withdrawal must stop scheduling. It also tempts the opposite mistake: treating each new key as new capacity, which this repository already rejected for projects.

**Decision.** `provider_contributors` records the contributor, an optional linked user, consent version and timestamp, status, and suspension/withdrawal timestamps. `provider_credentials.contributor_id` links each key to its contributor and stays nullable so platform-owned keys remain valid and are not misreported as unattributed contributions. Eligibility is decided in `CredentialRepository.claim_candidates`, which requires an active contributor and no `revoked_at`, so suspension and withdrawal take effect before the next lease. Withdrawal destroys the stored ciphertext and keeps the row; suspension keeps the ciphertext and withholds the key; reinstatement returns keys to `UNKNOWN`. Capacity is still computed per Google Cloud project per model, never per key, and usage is attributed to contributor, key, project, model and correction job.

**Consequences.**
- One contributor may hold many keys across many projects, and one project may serve several contributors; shared allowances are counted once.
- A single contributor's keys going invalid, exhausted or withdrawn removes only their candidates from rotation, so the correction pipeline continues on every other eligible project.
- No administrator or contributor response can return key material, so revocation is the only way to stop a key being used.
- The contributor ledger is append-only via `provider_usage`; a withdrawn contributor's history remains readable.
- Contributor management is an operator responsibility with an audit trail, not an implicit side effect of adding a key.

---

## ADR-024 — Platform ownership is a fourth account role, assigned only by the identity provider

**Context.** The product shipped three account types: `platform_operator`, `supervisor` and `assistant`. The platform's owner needs the operator surfaces *and* the teacher and assistant dashboards, and must not be creatable or removable by an ordinary administrator. The engine already used `OWNER` for workspace ownership, so reusing that value for platform ownership would have silently widened every workspace owner's reach.

**Decision.** `owner` is a fourth `aetrix_role` in the identity provider's `app_metadata`, whose permission set is the union of the platform and workspace capabilities. The engine carries it as `PLATFORM_OWNER` in `users.role` (migration `0008_platform_owner`), admits it to `FLEET_ADMIN_ROLES`, and keeps the workspace capabilities the account had as `OWNER` (`is_reviewer`, `can_manage_exams`). No endpoint or screen writes a role: assignment is an identity-provider action, so there is no application path that grants, edits or removes ownership.

**Consequences.**
- Platform ownership cannot be self-granted: `user_metadata` is user-writable and is never read for a role.
- An ordinary administrator has no control to promote or demote the owner; a downgrade requires identity-provider administrator access, and that action is outside this codebase by design.
- Tenant isolation is unchanged: `PLATFORM_OWNER` widens *platform administration*, not the tenant scope of engine data queries, which still come from the verified token claim.
- A new role must be added in three places deliberately (identity provider claim, frontend role table, engine check constraint), so forgetting one fails closed rather than half-working.
