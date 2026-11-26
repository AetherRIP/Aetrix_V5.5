# The correction engine

Status: **pre-release integration checkpoint.** This document describes the code
in `backend/app/correction` and the production path that runs it. Where a
capability is not exercised by a passing check, it says so.

## 1. One engine, one orchestration path

`aetrix_v5_5` is the only correction engine in this build.

```
worker process
  JobRunner.run_once                     backend/app/jobs/runner.py
    -> claim + lease + heartbeat
    -> build_pipeline(settings)          backend/app/jobs/pipeline.py
         -> AetrixEngine                 backend/app/correction/engine/aetrix.py
              -> AetrixPipeline.run      backend/app/correction/aetrix/pipeline.py
    -> terminal state / retry / review
```

- There is no registry, no engine-selection setting, no fallback engine and no
  second pipeline. `AETRIX_ENGINE__CORRECTION_ENGINE` is refused at startup
  unless it names `aetrix_v5_5`.
- The production executor is the worker process (`backend/app/worker.py`) and
  its `worker.concurrency` `JobRunner` threads. This Aetrix build has no separate
  `WorkerPool` class; the pool is those runner threads sharing one lease-aware
  claim loop. `JobRunner` owns the PostgreSQL lease, the heartbeat thread,
  cancellation, stale-write refusal and the terminal transition. The engine may
  not transition a job or approve a result.
- `AetrixEngine` only stamps provenance (engine name/version, result source,
  configured model, secondary model) and delegates to `AetrixPipeline.run`.
- A job created or already marked under a different engine name is refused, not
  re-marked. Historical rows keep `aetrix_legacy` / `mathchecker_v5` exactly as
  stored.

There is no `engine/service.py` in this backend. The experiment checkout under
`experiment/mathchecker_v5_test/repo` contains the reference Math Checker V5
engine; production code never imports it and no `sys.path` shim, monkey patch or
test shim is used. The V5 lifecycle is implemented natively in the Aetrix
contracts described below.

## 2. Marking pipeline stages

`AetrixPipeline.run` is the whole production marking lifecycle. In order:

1. **Reload and refuse.** Re-read the claimed job in the run's own session;
   return `CANCELLED` if cancellation was requested. Blueprint and scheme must
   be `APPROVED` and belong to the job's tenant, otherwise the outcome is
   `REVIEW_REQUIRED` and nothing is sent to a provider.
2. **Model policy gate.** A job whose recorded primary model is a disabled Lite
   model returns `REVIEW_REQUIRED` with `MODEL_POLICY_MISMATCH` before any page
   is read. See §5.
3. **Blueprint structure and leaves.** The approved immutable blueprint version
   is parsed into `BlueprintStructure`; scoreable *leaves* (sub-questions, or the
   question when there are none) are the units of marking.
4. **Criteria readiness.** Imported criteria must be approved against *this*
   blueprint version and complete. An unapproved or incomplete scheme stops
   before a provider call.
5. **Page coverage.** Every processed document and every declared page is
   accounted for. A declaration/storage mismatch is blocking and returns
   `PAGE_COVERAGE_INCOMPLETE`; a question whose script exceeds one request's page
   cap is marked with a `PAGE_LIMIT_TRUNCATED` review concern instead of a
   silently thinned script. `PAGE_COVERAGE_EXCEEDED` is the provider-level guard
   in `page_coverage`; it is not bypassed.
6. **Marking.** One of three execution strategies for the same contract:
   - `WHOLE_PAPER` (default): one request for the whole script and scheme; the
     reply is archived before parsing, and questions it did not decide fall back
     to the per-question request.
   - `PER_QUESTION`: one request per leaf, sequentially.
   - `PARALLEL`: the same per-question requests, concurrently in
     dependency-aware waves; acceptance is single-threaded per reply.
   The mode is fixed on the job's first marking execution, so a resumed paper
   cannot switch strategy half way through. These are request strategies of the
   single orchestration path, not alternative engines: all three parse, persist,
   check and guard through the same contract. `PARALLEL` is the same request as
   `PER_QUESTION`, only concurrent; `WHOLE_PAPER` falls back to those requests for
   leaves it did not decide.
7. **Normalisation and persistence.** A reply is untrusted until parsed against
   the marking contract. The model's award is normalised only where the contract
   requires it (over-maximum awards become a review item, not a clamp); the raw
   award and raw reply are retained. Components, their evidence quotations,
   criterion identity, page attribution and verification records are stored with
   the question row.
8. **Missing-question recovery.** `app/correction/recovery.py` plans bounded
   re-marking chunks for questions with no usable result. A gap covering almost
   the whole paper is refused as a failed run rather than retried; an existing
   decided row is never overwritten; the round/chunk budget is recorded on the
   job so a restart does not spend it twice.
9. **Integrity, scheme and evidence checks.** `app/correction/integrity.py`,
   `scheme_check.py`, `criterion_identity.py`, `provenance.py` and
   `evidence_check.py` compare the award with the reply and with the approved
   scheme. Findings are deterministic and never rewrite the award.
10. **Mathematical verification.** `app/correction/aetrix/verification.py` uses
    SymPy for the reply's own answer check; a scheme-level comparison is recorded
    separately. An unreadable expression is `UNVERIFIABLE`, never `VERIFIED`.
11. **Confidence and review.** Low confidence, an integrity finding, a definite
    scheme contradiction, missing evidence, incomplete coverage or a truncated
    read sets the question to `NEEDS_REVIEW`. A question is never a bare zero
    because the engine could not read it.
12. **Optional independent double check.** A separate review-role model re-marks
    selected uncertain questions within a bounded budget. Agreement is recorded;
    disagreement is `DOUBLE_CHECK_DISAGREEMENT` and sends the question to a
    person. The first award is never replaced.
13. **Result guard.** `app/correction/guard.py` decides whether this run's marks
    may become the submission's result. An approved prior result is never
    replaced; a teacher override outranks an automated pass; a zero where the
    stored result awarded marks, or a drop of 30 points or more, keeps the
    stored result and requires review.
14. **Persistence and terminal outcome.** Results land through the existing
    `QuestionResult` / `CriterionResult` / `MarkingEvidence` /
    `VerificationResult` tables and the existing job lifecycle. The engine
    returns `FINALIZING` (runner completes), `REVIEW_REQUIRED` (no result is
    presented as final) or `CANCELLED`.

A provider outage raises `RetryablePipelineError`; the runner parks the job with
`PROVIDER_UNAVAILABLE` and the lease is released. A partial paper stays
explicitly partial: unmarked questions are `UNMARKED`/`NEEDS_REVIEW`, never a
final total.

## 3. Contracts the engine enforces

| Contract | Where | Failure behaviour |
|---|---|---|
| `component_total == awarded_marks` | `correction/integrity.py` | `COMPONENT_TOTAL_MISMATCH`; question is `NEEDS_REVIEW`. The award is retained as evidence, never rewritten to the component total. |
| Award within the question maximum | `integrity.py`, `normalise_award` | `AWARD_ABOVE_MAXIMUM` / `OVER_MAX_AWARD`; stored award `0`, review, raw award kept. |
| Every awarded component names an approved mark point | `criterion_identity.py` | `UNKNOWN_CRITERION` / `CRITERION_NOT_IN_APPROVED_SCHEME`; review. |
| No mark point paid twice | `criterion_identity.py`, `scheme_check.py` | `DUPLICATE_CRITERION_AWARD`; the row keeps no second link. |
| Every quotation is located on a page | `provenance.py` | `EVIDENCE_UNLOCATED` / `EVIDENCE_PAGE_INVALID`; review. |
| Question identity matches the request | `aetrix/schema.py` | reply is an unusable row, never a mark for another question. |
| Duplicate questions in a paper reply | `aetrix/whole_paper.py` | that item is rejected and falls back individually; the reply is not trusted whole. |
| Missing questions | `omit_leaves`, `recovery.py` | explicit unmarked rows plus a targeted-retry plan; review when unresolved. |
| Coverage of every page | `page_coverage.py` | blocking `PAGE_COVERAGE_INCOMPLETE`, or review with `PAGE_LIMIT_TRUNCATED`. |
| Mathematical check | `aetrix/verification.py` | `VALID` / `INVALID` / `UNVERIFIABLE` recorded; an unverifiable check is not a pass. |
| Model trust | `core/marking_policy.py`, `services/provider_calls.py` | configuration refusal; explicit one-model marking call; no fallback. |

A syntactically valid reply is not trusted on that basis alone: schema
validation, integrity, scheme comparison, criterion identity, evidence and
verification all run before the award can be presented.

## 4. Persistence, idempotency and retries

- The worker claims with a real PostgreSQL lease and records every attempt.
- Results are written per question; recovery and re-execution reuse existing
  rows and do not re-run decided questions.
- Whole-paper replies are archived (`provider_responses`) before parsing, keyed
  by a digest, so a retry can rebuild rows without paying for the reply twice.
- A stale write (lease lost, record moved on) is refused and audited.
- A failed correction is a failed or review job, never a completed result.
- Mode, prompt version, engine and model provenance are recorded so a resumed
  job cannot silently change any of them.

## 5. Model configuration

The engine is the correction pipeline; the model is a configuration detail of
that pipeline.

- **Production marking model: `gemini-3.6-flash`** (`PRODUCTION_MARKING_MODEL`
  in `backend/app/core/marking_policy.py`).
- **Disabled marking models: `gemini-3.5-flash-lite` and
  `gemini-3.1-flash-lite`.** Neither can be selected for a production role, and
  neither is walked as a fallback. Any `*-lite` id is refused for marking, which
  is Math Checker V5's own trust rule. Prices, quota entries and historical usage
  for the disabled models are retained; nothing historical is rewritten.
- Configuration validation refuses:
  - a `model_primary` other than `gemini-3.6-flash`;
  - a primary chain that is not exactly one enabled entry naming
    `gemini-3.6-flash` (no automatic model fallback);
  - a `model_review` / `model_lightweight` or any chain entry that names a
    disabled Lite model.
- A marking request names its model explicitly (`ProviderCallService.call(...,
  model=...)`), so the provider service has a one-entry chain. If the model is
  unavailable, the job is parked with a clear `PROVIDER_UNAVAILABLE` message;
  no other model is tried.
- The job records `primary_model` from the model that **actually answered** the
  marking reply (`_MarkingRun._remember_marking_model`). A reply from any other
  model is a configuration error and nothing from it is stored. Every paid
  attempt is also recorded with its model in the append-only `provider_usage`
  ledger.
- The optional double check and the blind transcription use the `review` role;
  they are not marking. The double check only records agreement/disagreement and
  never replaces an award.
- 15 API keys are not 15 quota pools. Quota is counted per Google Cloud project
  and model; the existing project-aware pool and cooldowns are unchanged.

### Environment

```
AETRIX_PROVIDER__MODEL_PRIMARY=gemini-3.6-flash   # required value
AETRIX_PROVIDER__MODEL_REVIEW=<review model>      # never a *-lite id
AETRIX_PROVIDER__MODEL_CHAINS=...                 # primary: exactly one entry
AETRIX_MARKING__DOUBLE_CHECK_ENABLED=false        # optional second opinion
AETRIX_MARKING__MARKING_MODE=WHOLE_PAPER
```

A database `provider_model_selections` row is consulted first for a role. A
legacy `primary` row naming a disabled model fails before marking with an
actionable `CONFIGURATION_ERROR`; it is not silently replaced.

## 6. Human review conditions

A person is required when: the award exceeds the maximum, the component total
disagrees with the award, a mark point is unknown/duplicated, evidence is missing
or unlocated, the scheme contradicts the award, coverage is incomplete or a page
was withheld, confidence is below `AETRIX_MARKING__MIN_CONFIDENCE`, recovery
could not resolve a question, a double check disagrees, or the result guard
refuses an overwrite. Review is a real state, not a display label: the job ends
`REVIEW_REQUIRED` and the question keeps `processing_state=NEEDS_REVIEW`.

## 7. Known limits

- The integration suite (`backend/tests/integration`) requires a disposable
  loopback PostgreSQL and was not runnable on the migration machine.
- No live provider call was made during the migration; the model policy is
  verified with deterministic fixtures and a scripted provider.
- The benchmark holdout has zero certified papers; nothing here is an accuracy
  claim.
