# Checkpoint 2 Acceptance Evidence

Scope: provider boundary, document ingestion, page quality/ordering,
page-to-question mapping, blueprint extraction and versioned teacher overrides.

Status: **engine paths implemented and deterministically verified on the live
Supabase/PostgreSQL database**. The bounded live Gemini probe reached the
provider but was rejected at authentication, so the live provider/extraction
path is **UNVERIFIED**. This document records observed output, not intended
behavior.

---

## 1. Delivered surface

### Provider boundary

- `backend/app/providers/base.py`: provider-neutral `LLMProvider`,
  `LLMRequest`, `LLMInput`, `LLMResponse` and `TokenUsage`; no provider SDK
  type crosses this boundary.
- `backend/app/providers/gemini.py`: the only wire-format module. It uses the
  Gemini REST API through `httpx`, sends the key in `x-goog-api-key` (never in a
  URL), and maps authentication, quota, transient, request and malformed-response
  failures to typed errors.
- `backend/app/providers/factory.py`: live provider selection. When the feature
  is disabled, `UnavailableProvider` raises `ProviderNotConfigured` rather than
  inventing a result.
- `backend/app/services/provider_calls.py`: prompt resolution, credential
  leasing, durable quota reservation, retry/cooldown/invalidation, usage
  recording and cost accounting. A failed attempt is still recorded; an unknown
  price records no cost instead of a fabricated zero.
- `backend/app/prompts/registry.py` and `backend/prompts/manifest.json`: prompts
  are files pinned by id, version and SHA-256. Editing a file without a manifest
  version/hash update fails to load.
- New tables: `provider_quota_reservations`; `provider_usage` gained prompt,
  latency, status and request metadata.

### Ingestion and page assessment

- `backend/app/documents/validation.py`: empty, oversize, unsupported, MIME
  mismatch, corrupt/encrypted PDF, excess page count, corrupt image and excess
  image-pixel checks. The actual signature wins over the declared type.
- `backend/app/storage/`: storage protocol and local filesystem adapter.
- `backend/app/documents/rendering.py`: PDF page rendering at configured DPI,
  EXIF orientation normalization for images, per-page checksum, text extraction,
  duplicate-page detection, quality and order assessment.
- `backend/app/documents/quality.py`: typed `READABLE`, `LOW_QUALITY`,
  `ROTATED`, `PARTIALLY_UNREADABLE`, `UNREADABLE`, `EMPTY` states with
  code/message/severity reasons.
- `backend/app/documents/ordering.py`: printed page numbers are checked for
  missing/out-of-order values. With no readable numbers the document is
  `UNVERIFIED`, not silently assumed ordered.
- `backend/app/documents/service.py`: rejected uploads are persisted as
  `REJECTED` documents with typed reasons and an audit event; no page is silently
  dropped. Successful documents are `PROCESSED` with persisted pages.

### Mapping, extraction and overrides

- `backend/app/documents/mapping.py`: deterministic text-label matching first,
  model fallback only for pages without a usable label. The result is validated
  against the approved blueprint's identifier set and every unmapped page gets a
  visible reason. Mapping requires an `APPROVED` blueprint belonging to the same
  exam.
- `backend/app/documents/blueprint_extraction.py`: extracts from a processed,
  approved-in-the-scheme document through `BlueprintService.create_extracted_draft`.
  The result is always `DRAFT` with source `EXTRACTED`, prompt/usage provenance
  and a content hash. There is no extraction-to-approved path.
- `backend/app/services/blueprint_overrides.py`: creates a new `DRAFT`
  `exam_blueprint_versions` row and a `blueprint_overrides` record carrying the
  author and rationale. The base approved version is untouched.
- Migration `2c331690c5f0_cp2_ingestion_provider_and_overrides.py` adds the CP2
  tables, columns and the approved/superseded immutability trigger.
- Migration `0002_fix_blueprint_guard_fix` fixes PostgreSQL's lack of a `json`
  equality operator by comparing canonical text, and rejects an approved
  version returning to `DRAFT`.

### API endpoints

All are under `/api/v1`, use the CP1 principal tenant resolution, and return
tenant-scoped 404s for cross-tenant resources.

| Method | Path | Gate |
|---|---|---|
| POST | `/submissions/{submission_id}/documents` | exam manager; own submission |
| GET | `/documents/{document_id}` | tenant member |
| POST | `/documents/{document_id}/mapping` | exam manager; approved blueprint |
| POST | `/exams/{exam_id}/schemes` | exam manager; own exam |
| GET | `/schemes/{version_id}` | tenant member |
| POST | `/schemes/{version_id}/approve` | exam manager |
| POST | `/exams/{exam_id}/blueprint/extractions` | exam manager; processed scheme document |
| POST | `/exams/{exam_id}/blueprint/overrides` | exam manager; base version in exam |
| GET | `/exams/{exam_id}/blueprint/overrides` | tenant member |

---

## 2. Migration state (live Supabase/PostgreSQL)

Command:

```bash
cd backend
.venv/Scripts/python.exe -m alembic current
```

Observed:

```text
0002_blueprint_guard_fix (head)
```

The CP2 migration ran successfully against the live project:

```text
INFO  [alembic.runtime.migration] Running upgrade 0001_append_only -> 2c331690c5f0, cp2 ingestion provider and overrides
```

After the trigger repair, the guard migration was applied:

```text
INFO  [alembic.runtime.migration] Running upgrade 2c331690c5f0 -> 0002_blueprint_guard_fix, fix blueprint immutability trigger for json columns
```

A subsequent `alembic upgrade head` produced only context lines and exited 0 — there
was no pending revision. `alembic check` also reported:

```text
No new upgrade operations detected.
```

The first CP2 trigger used `NEW.structure IS DISTINCT FROM OLD.structure`. PostgreSQL
raised `operator does not exist: json = json` instead of rejecting the mutation.
The forward migration compares `NEW.structure::text` and
`NEW.extraction_metadata::text`; it also rejects `APPROVED -> DRAFT` status
changes. The integration tests below exercise both paths.

---

## 3. Engine verification

Command:

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
```

Observed:

```text
84 passed, 1 warning in 151.51s
```

The warning is the pre-existing Starlette `TestClient`/`httpx` deprecation; it
does not fail a test. The suite includes:

- CP1 tenant isolation, job lease/idempotency/lifecycle and API tests.
- Ingestion validation, page rendering, quality/ordering and rejection reasons.
- Page mapping with approved-blueprint enforcement and model fallback.
- Extraction draft-only behavior, prompt version/usage persistence,
  prose-prefixed and fenced JSON acceptance, and malformed model output
  rejection.
- Override version creation, author/rationale persistence and database-level
  immutability rejection.
- Provider retry, credential invalidation/cooldown, quota reservation and usage
  accounting with fake providers (the default test path; no live spend).
- Gemini adapter request shape (`responseMimeType`, `responseJsonSchema`, no
  legacy `responseSchema`) and thought-part filtering.

Ruff:

```bash
.venv/Scripts/python.exe -m ruff check app tests migrations scripts
```

Observed:

```text
All checks passed!
```

---

## 4. Frozen benchmark/holdout verification

Run from the repository root with the frozen harness interpreter:

```bash
.tools/python/python.exe -m pytest benchmark/tests benchmark/holdout/tests -q
.tools/python/python.exe -m benchmark.holdout.manifest --check-code
```

Observed:

```text
207 passed in 21.22s
```

```json
{
  "valid": true,
  "papers": 0,
  "certified_papers": 0,
  "status": "blocked_no_certified_papers",
  "decision_permitted": false,
  "problem_count": 0,
  "problems": []
}
```

Both commands exited 0. The seven frozen digests validate. The holdout remains
blocked because it has zero certified papers; this checkpoint does not change
that program or claim an accuracy result.

---

## 5. Bounded live Gemini probe

The probe is intentionally manual; it is not part of the test suite. It reads
`C:\Projects\MATH_CHECKER_V5\API_KEYS.txt` read-only and prints no key material.

After the adapter change, the smoke command was:

```bash
cd backend
.venv/Scripts/python.exe scripts/smoke_gemini.py
```

Observed:

```json
{"status": "UNVERIFIED", "keys_probed": 3, "failures": ["key#1:ProviderTransientError:503", "key#2:ProviderTransientError:503", "key#3:ProviderAuthenticationError:403"]}
```

Exit status 1. This used three post-change requests.

The canonical extraction probe then used one further key:

```bash
cd backend
.venv/Scripts/python.exe scripts/live_extraction.py --key-index 4
```

The provider call reached Gemini and was rejected. The append-only ledger records:

```text
status: UNVERIFIED
http_status: 403
error_class: ProviderAuthenticationError
success: false
model: gemini-3.6-flash
purpose: BLUEPRINT_EXTRACTION
prompt: blueprint_extraction@v1
prompt_hash: 3bc149e7717cf2a28264a70f329f248154469a91699cae39d893a9145159d682
usage_id: b0825110-7955-4ae7-a5eb-efdb097912a7
draft_blueprint_id: none
```

No `DRAFT` was created and no response text was produced. The extraction script's
first cleanup attempt tried to delete the temporary credential; PostgreSQL
correctly rejected the `ON DELETE SET NULL` update because `provider_usage` is
append-only. The cleanup path was changed to disable the credential and replace
its ciphertext with an encrypted empty string. The live row is now `DISABLED`
with an empty ciphertext; no raw key remains. The corrected script was not rerun
because the five-request cap was reached.

For context, the single pre-change probe authenticated and returned
`Here is the JSON requested` (17 input / 252 output tokens, 33,085 ms). That
probe preceded the `responseJsonSchema` change and therefore did not test
structured output. The four post-change requests were three smoke attempts
(503, 503, 403) and one extraction attempt (403). Total live requests: five,
which is the bound (one initial plus four further).

**Conclusion: the live provider/extraction path is UNVERIFIED.** The
`responseJsonSchema` request, prose/fence parser and malformed-output rejection
are verified only by deterministic fixtures. No key value was copied, logged,
echoed or written to a document; the key file remains outside this repository.

---

## 6. Defects found and repaired during acceptance

1. **JSON immutability trigger was non-functional.** PostgreSQL `json` has no
   equality operator. The trigger raised `UndefinedFunction` on every update of an
   approved/superseded blueprint. Fixed by text casts in `0002`; the approved
   version now rejects structural mutation and status regression with the
   intended exception.
2. **Trigger applied before repair.** The repair is a forward migration, so the
   live database did not depend on editing an already-applied revision. Fresh
   databases get the repaired function from the same head.
3. **Extraction spent quota before role check.** `BlueprintExtractionService` now
   calls `ensure_exam_manager` before loading or calling the provider. The mapping
   route now applies the same manager gate before writing mappings.
4. **Missing runtime dependencies.** `pymupdf`, `pillow`, `numpy` and
   `python-multipart` are declared in `backend/pyproject.toml`.
5. **Generated storage was not ignored.** `backend/data/` is now git-ignored.
6. **Sub-question mark overrides were impossible.** The first implementation
   rejected a sub-question `set_question_marks` operation and did not recompute
   the parent total. It now permits the sub-question edit, recomputes the parent
   mark from its non-excluded sub-questions, and lets canonical validation
   recompute the blueprint total. Regression test:
   `test_subquestion_mark_override_recomputes_parent_and_total`.
7. **The adapter did not enforce JSON at request time.** It sent the legacy
   `responseSchema` field and received prose. It now sends
   `responseMimeType: application/json` and `responseJsonSchema`, skips parts
   marked `thought: true`, and delegates to the shared tolerant parser.
8. **Fenced or prose-wrapped JSON was rejected.** `parse_json_text` now tries the
   whole string first, then balanced `{...}`/`[...]` substrings outside strings.
   It does not repair malformed JSON; a genuinely bad response still maps to
   `EXTRACTION_INVALID`. Unit and integration regressions cover prose, fences and
   malformed text.
9. **Credential cleanup collided with the append-only guard.** Deleting a
   credential referenced by `provider_usage` triggers the FK's `SET NULL` update,
   which the database correctly rejects. The live probe now disables the row,
   replaces its ciphertext with an encrypted empty string, and leaves usage
   provenance intact.
10. **The development `.env` Fernet key is malformed.** The live probe uses a
    generated in-process Fernet key for its temporary credential instead of
    editing the operator's untracked environment. Production must still use a
    valid, rotated key from the secret store.

---

## 7. Remaining limitations

- Marking, SymPy verification, review and results are still out of scope. The
  job pipeline remains `UnavailablePipeline`.
- Storage is the local filesystem adapter. Supabase Storage is not wired; the
  storage protocol is ready for it.
- Page mapping uses text labels and a vision fallback; it is not a certified
  accuracy claim.
- Live provider authentication is blocked: two keys returned 503 and two
  returned 403; no live extraction or draft exists. The structured-output path is
  verified by deterministic fixtures only.
- The development `.env` encryption key is malformed. The live probe uses a
  generated in-process Fernet key for a temporary credential; no operator env
  file was changed. Fix the env key before production.
- A credential referenced by append-only `provider_usage` cannot be deleted;
  disable it and replace its ciphertext instead.
- Extraction quality needs a reviewed mark scheme and a real paper run in a later
  checkpoint.
- No frontend, RLS, malware scan, rate limiter or production deployment is
  included.
- The holdout is still blocked at zero certified papers.
