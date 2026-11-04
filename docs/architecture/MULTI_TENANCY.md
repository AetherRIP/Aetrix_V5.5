# Multi-Tenancy

**Status:** RECOMMENDED. This is the highest-consequence document in the package.

## 1. The three options

| Option | Isolation | Ops cost | Fits D1? | Verdict |
|---|---|---|---|---|
| **A. Shared DB, shared tables, `workspace_id`** | Row-level, enforced in app | Lowest: one schema, one migration, cross-tenant analytics trivial | Yes — the documented D1 pattern | **Chosen** |
| **B. Database per workspace** | Physical | High: per-tenant migrations, fan-out, deletion, restore | **No** — see below | Rejected |
| **C. Hybrid (shared default, dedicated for enterprise)** | Mixed | Medium-high | Partially | Deferred, designed for |

### Why B is rejected on D1 (VERIFIED)

- **10 GB per database is a hard cap that cannot be raised** (Cloudflare D1 limits).
- **No dynamic bindings.** A Worker's D1 bindings are static in configuration; opening a *new* tenant's
  database at runtime requires redeploying config or falling back to the REST API — and the REST path hits
  account API rate limits (1,200 requests / 5 min default). Cloudflare has no announced ETA for first-class
  dynamic binding.
- **Cross-tenant reporting becomes fan-out**: every platform metric is N queries.
- **Migrations become N migrations** with partial-failure states.
- Note the counter-argument honestly: B would make *deletion* and *export* trivial (`DROP DATABASE`) and gives
  a genuinely physical boundary. That is why it stays on the table for an enterprise tier (option C).

### Why not Postgres (VERIFIED context)

Postgres + Hyperdrive buys real RLS, JSONB, advisory locks — at the cost of a second vendor, ~50 ms
per-query network hop, a 25-configuration limit, and a schema/query rewrite. For **10–100 workspaces whose
database holds metadata only** (bytes live in R2), the isolation gain does not justify latency on every page.

## 2. Chosen model: row-level isolation with four enforcement layers

```
Layer 1  Session      who you are            Better Auth session → userId
Layer 2  Membership   which workspaces       membership row (role, status)
Layer 3  Context      which workspace now    TenantContext built server-side only
Layer 4  Data access  every statement        workspace_id in every predicate + index lead
```

**Layer 3 is the load-bearing one.** `TenantContext` is a branded type that can only be produced by
`resolveTenant(request)` after layers 1–2 succeed. Repository functions accept `TenantContext`, never a raw
`workspaceId: string`. A handler therefore cannot accidentally run an unscoped query: it has nothing to pass.

```ts
// Only this factory mints a TenantContext.
async function resolveTenant(req, env): Promise<TenantContext> { /* session → membership → context */ }

// Repositories are tenant-bound, not tenant-aware.
const repo = tenantRepo(ctx, env.DB);
await repo.assignments.byId(id);        // SELECT ... WHERE id = ? AND workspace_id = ?
```

## 3. Schema rules (non-negotiable)

1. Every tenant-owned table has `workspace_id TEXT NOT NULL` referencing `workspaces(id)`.
2. Primary keys are `TEXT` UUIDv7. Never autoincrement — a sequential id plus one missing predicate is an IDOR.
3. Every index on a tenant table **leads with `workspace_id`** (`(workspace_id, status, created_at)`).
   SQLite uses one index per table reference; if `workspace_id` is not leading, "scoped" queries degrade to
   scans and D1 bills rows *scanned*.
4. Uniqueness is workspace-scoped: `UNIQUE(workspace_id, slug)`, never global.
5. Cross-tenant foreign keys are impossible by construction: child rows carry the parent's `workspace_id`,
   and application code asserts equality on insert.
6. Global tables (`users`, `sessions`, `workspaces`, `platform_audit`) are explicitly listed in
   `DATABASE_DESIGN.md` §5 and are the only ones without `workspace_id`.

## 4. Query rules

| Rule | Reason |
|---|---|
| `WHERE id = ? AND workspace_id = ?` for every object read | Prevents IDOR if a predicate is forgotten elsewhere |
| Return **404** for a row in another workspace | Never confirm existence (403 leaks it) |
| Ownership checks live *in* the UPDATE/DELETE predicate, not before it | Closes the check-then-use race |
| No `SELECT *` in API shaping | Prevents leaking columns added later |
| No client-supplied `workspace_id` trusted, even when it matches the URL | The URL is a hint; the session is the fact |
| Batches must be homogeneous in `workspace_id` | `db.batch()` runs in one transaction; mixing tenants in one batch is a leak vector |
| Reads that follow a write in the same request use the D1 session bookmark | Read-your-writes correctness (read replication is beta) |

## 5. Defence in depth, beyond the data layer

- **Route layer:** an object URL that resolves outside membership is 404 at routing, before any repository call.
- **Response layer:** shapers whitelist fields; a new column cannot leak by accident.
- **R2 layer:** every object key is `ws/{workspaceId}/...`; the download endpoint re-derives the key from the
  authorised row, never from the request body.
- **Cache layer:** any cache key includes `workspaceId`; there is no cross-tenant cache entry.
- **Realtime layer:** the Durable Object name is derived from `workspaceId`; the socket handshake re-checks
  membership and role, and a membership change closes the socket.
- **Job layer:** a job carries `workspaceId` from creation and every step re-asserts it against the row.
- **Export layer:** tenant export streams `WHERE workspace_id = ?`; `d1 export --table` is **forbidden**
  (it dumps every tenant's rows in that table).

## 6. Analytics without leaking

Platform metrics run on aggregate queries (`COUNT`, `SUM`) with **no** row-level detail, and the platform UI
shows counts, not names. Anything requiring row inspection needs a support grant (see `../security/SECURITY_REQUIREMENTS.md` §7).

## 7. Deletion, export, and the tombstone

| Operation | Mechanism |
|---|---|
| Export one tenant | Workflow streams `WHERE workspace_id = ?` per table into R2, zips, signs a 24 h URL |
| Soft delete | `workspaces.deleted_at` set; memberships revoked; all reads 404 |
| Hard delete | Batched `DELETE ... WHERE workspace_id = ?` (≈1,000 rows per statement), then R2 prefix purge |
| Tombstone | `workspace_tombstones(id_hash, purged_at)` keeps a hash so late jobs cannot resurrect rows |
| Cancel window | 14 days, owner-cancellable |

Large deletes must be chunked: a single statement touching hundreds of thousands of rows hits D1 execution
limits, and `d1 export` blocks other requests on that database.

## 8. If we ever need option C (enterprise tier)

The design permits it without rewriting: repositories already take `TenantContext`, so a
`TenantContext.database` can resolve to a dedicated binding for tiered tenants. The cost is real — a second
migration path, per-tenant restore, and a routing table — which is why it is deferred until a customer pays
for it.

## 9. Residual risks

| Risk | Residual | Control |
|---|---|---|
| Developer writes raw `env.DB.prepare` in a handler | Medium | Lint rule banning `env.DB` outside `data/`; review checklist |
| New table added without `workspace_id` | Medium | Migration test asserts the column set; CI schema lint |
| Cache key omits tenant | Low | Cache helper requires `TenantContext` |
| Aggregate endpoint exposes a single-row group | Low | Minimum group size of 5 in analytics responses |
| Support access misuse | Low | Consent, scope, expiry, per-read audit |
