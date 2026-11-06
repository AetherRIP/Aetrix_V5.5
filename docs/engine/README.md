# Aetrix V5.5 — engine implementation set

This directory preserves the implementation documentation developed in the standalone
`Engine_V5.5` repository. It describes the code now under [`backend/`](../../backend), the
frozen benchmark under [`benchmark/`](../../benchmark), and the acceptance evidence for the
CP1–CP2 checkpoints.

## Read in this order

1. [`architecture/SYSTEM_OVERVIEW.md`](architecture/SYSTEM_OVERVIEW.md) — runtime topology,
   module map, data model, job lifecycle, API surface and deliberate absences.
2. [`architecture/DATA_FLOW.md`](architecture/DATA_FLOW.md) — request, worker, ingestion,
   mapping, extraction and provider-call flows.
3. [`architecture/DECISIONS.md`](architecture/DECISIONS.md) — numbered ADRs, including the
   provider boundary, canonical blueprint and live-verification rules.
4. [`architecture/SECURITY.md`](architecture/SECURITY.md) — tenant isolation, credential
   handling and untrusted model output.
5. [`architecture/DEPLOYMENT.md`](architecture/DEPLOYMENT.md) — PostgreSQL/Supabase setup,
   configuration, migrations, API/worker operation and CI commands.
6. [`architecture/RLS_SECURITY_AUDIT.md`](architecture/RLS_SECURITY_AUDIT.md) — the Data API
   exposure audit, policy matrix and RLS lockdown plan.
7. [`audits/CP2_ACCEPTANCE.md`](audits/CP2_ACCEPTANCE.md) — deterministic evidence and the
   live-provider failure record.
8. [`audits/INITIAL_REPOSITORY_AUDIT.md`](audits/INITIAL_REPOSITORY_AUDIT.md) — the Phase 0
   inventory and corrected premise.

## Authority and scope

These documents govern the implemented engine. The older [`docs/`](../) tree is the original
Cloudflare/D1 planning set and is preserved as history; it is not a description of the running
Python engine. Where the two conflict, `docs/engine/` and the engine ADRs win.

The engine does **not** implement marking or production readiness. The worker parks jobs with
`PIPELINE_UNAVAILABLE`; the live Gemini probe is `UNVERIFIED` after authentication f
