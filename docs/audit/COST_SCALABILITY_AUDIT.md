# Cost and Scalability Audit

**Audit date:** 2026-11-03. Unit prices were re-verified against official Cloudflare pricing on the audit date.
Nothing here is a quote. Values are labelled: **[V]** verified from documentation, **[E]** estimate derived from
stated assumptions, **[A]** assumption.

## 1. Workload model used for this audit

The source document's assumptions were accepted where stated, then extended to cover the rows it omits.

| Quantity | 2 ws | 10 ws | 50 ws | 100 ws | Basis |
|---|---|---|---|---|---|
| Users (assistants) | 16 | 80 | 400 | 800 | briefing table (10/20 per ws) |
| Students per assignment | 25 | 25 | 25 | 25 | [A] |
| Assignments / ws / month | 12 | 12 | 12 | 12 | [A] |
| Submissions / month | 600 | 3,000 | 15,000 | 30,000 | [E] 12 × 25 × ws |
| Pages per script | 6 | 6 | 6 | 6 | [A] |
| Bytes per submission | 2.4 MB | | | | [E] 6 × 400 KB |
| AI calls per submission | 1.3 | | | | [A] retries + re-marks |
| API requests / month | 0.6 M | 2.9 M | 14 M | 29 M | [E] ~120 page views/user/day |
| Real-time sockets (if DO kept) | 24 | 120 | 600 | 1,200 | [E] 1.5 tabs/user |

## 2. Unit prices (re-verified 2026-11-03) [V]

| Item | Price | Note |
|---|---|---|
| Workers Paid | $5/mo, 10 M requests, 30 M CPU-ms included; +$0.30/M requests, +$0.02/M CPU-ms | max CPU 5 min/invocation |
| D1 | 5 GB storage, 25 B rows read, 50 M rows written included; +$0.75/GB-mo, +$0.001/M reads, +$1.00/M writes | 10 GB hard cap/database |
| R2 | $0.015/GB-mo; Class A $4.50/M; Class B $0.36/M; egress free | 10 GB free tier |
| Queues | 1 M ops included; +$0.40/M | 1 op = 64 KB written/read/deleted → a 128 KB message = 2 ops |
| Workflows | 10 M requests + 30 M CPU-ms + **500 k steps** included; +$0.80 per 100 k steps | 8 steps × 30 k jobs = 240 k/mo |
| Durable Objects | 1 M requests + 400 k GB-s + 5 GB-mo SQL included; +$0.15/M req, +$12.50/M GB-s, +$0.20/GB-mo | incoming WS messages billed 20:1 |
| Rate limiting / WAF managed rules | **Pro or above** | not in the source cost model |

## 3. Findings

### COST-01 — HIGH — The cost model omits the component the architecture says it needs
**Documents:** `operations/COST_AND_SCALABILITY.md` §4, `architecture/SYSTEM_ARCHITECTURE.md` §7.

The architecture's recommended PDF strategy is **Workers Containers** (or a paid external render API), yet the
infrastructure table has no container line, no external-service line, and the service table explicitly excludes
Containers from the MVP. Whichever option P1 selects adds a cost class the budget does not contain, and containers
bill on allocated memory × wall-clock — for 15,000–30,000 report generations per month that is not a rounding
error.

**Resolution.** Cost both options in P1 with measured render time; add the winning line to §4 before P5. If an
external API is chosen, add its per-document price and the DPA review.

### COST-02 — MEDIUM — Storage arithmetic under-counts by roughly 4×
**Documents:** `operations/COST_AND_SCALABILITY.md` §3, `architecture/DATABASE_DESIGN.md` §9.

The model assumes ≈1 KB of D1 metadata per submission and projects 0.75 GB at 100 workspaces. Counting the rows a
submission actually creates — `submissions` + `submission_files` (1–3) + `results` + **12 `question_results` with a
text `explanation`** + `jobs` + 1–3 `job_attempts` + `usage_events` + `audit_log` + `overrides`/`approvals` — the
realistic figure is **4–6 KB per submission**, dominated by the per-question explanations.

| | Source estimate | Audit estimate [E] |
|---|---|---|
| D1 per submission | ~1 KB | 4–6 KB |
| 100 ws, monthly growth | ~90 MB | ~0.35–0.45 GB |
| 100 ws, 12 months | ~0.75 GB | ~2.5–3 GB (with retention pruning) |
| Years to the 10 GB wall at 100 ws | >10 | ~3–4 |

The wall is still years away — the design shape holds — but the document's central reassurance is wrong by a
factor of four, and the retention plan (jobs 90 days, usage 24 months) is what keeps it that low. That dependency
should be stated.

**Resolution.** Correct the arithmetic, state which retention rules the projection depends on, and alarm at 70 %
of 10 GB (already specified) with a quarterly actual-vs-projection check.

### COST-03 — MEDIUM — The Durable Object line is not derived from anything
**Documents:** `operations/COST_AND_SCALABILITY.md` §4 ("Durable Objects ~$24 at 100 ws").

No derivation is shown. With hibernation, duration billing accrues only while awake; the real driver is **requests**
(1 per upgrade, 1 per outgoing broadcast batch, and **20 per incoming message**). At 1,200 sockets and coalesced
progress, the plausible range is $2–$30/month — but nobody can check the figure because the assumptions are absent.

**Resolution.** Either cost it explicitly (events/job, wakes/hour, messages/socket) or adopt ARC-03 and delete the
line by removing the component.

### COST-04 — MEDIUM — The rate-limiting and WAF tier is unbudgeted
**Documents:** `architecture/CLOUDFLARE_ARCHITECTURE.md` §7, `security/SECURITY_REQUIREMENTS.md` AB-1.

Four rate-limit rules plus WAF managed rules require Pro or above (Free permits one rule; WAF managed rules are a
Pro/Business feature). The budget contains Workers Paid at $5 only. Pro is an order of magnitude more than the
entire projected infrastructure cost at 2–10 workspaces.

**Resolution.** Add the plan tier as a line item, or move per-user rate limiting into the Worker (DO/`usage_events`)
and run on Free/Paid with one well-chosen rule.

### COST-05 — MEDIUM — Workflow steps are closer to the included allowance than shown
30,000 submissions × 8 steps = **240 k steps/month** against 500 k included — fine at 100 workspaces, but retries
and re-marks multiply steps, and a runaway retry loop is a *step* cost as well as an AI cost. At 250 workspaces the
allowance is exhausted (600 k steps → ~$0.80 per additional 100 k).

**Resolution.** Note the step budget in the scale table; alarm on steps/month alongside AI spend.

### COST-06 — MEDIUM — AI cost is correctly left as a variable, but the sensitivity analysis stops short
**Documents:** `operations/COST_AND_SCALABILITY.md` §5.

Leaving `C` unknown is the right call, and the table across $0.002–$0.08 is useful. What is missing is the
**shape** of the decision: at $0.03/call and 100 workspaces, AI spend (~$1,170/mo) is **8.7×** total infrastructure
(~$135/mo). The document implies infrastructure dominates; it does not. That ratio is the single most important
number in the commercial plan and it is left implicit.

**Resolution.** Add one sentence: at any C ≥ $0.01 the AI line dominates infrastructure by an order of magnitude,
so pricing must be set on C, not on hosting. Also state who pays under Q3's "platform keys for trial" default —
every trial submission is the operator's money.

### COST-07 — LOW — Queues operation accounting is right but invisible
A 128 KB message costs 2 operations per write/read/delete; ids-only messages (~200 bytes) cost 1. 300 k
messages/month is well inside 1 M. No action; recorded so the next reader does not re-derive it.

### COST-08 — LOW — Email is the only line with no vendor named
$10–$40/month is plausible for transactional email at this volume, but no provider, no per-1,000 price, and no
statement of whether invitation emails count double (they do — verify + invite).

## 4. Recomputed infrastructure estimate (excluding AI) [E]

| Line | 2 ws | 10 ws | 50 ws | 100 ws |
|---|---|---|---|---|
| Workers Paid base | $5 | $5 | $5 | $5–25 |
| Requests overage | ~$0 | ~$0 | ~$2 | ~$6 |
| D1 storage + rows | ~$0 | ~$1 | ~$5 | ~$11 |
| R2 storage (year-1 avg) + ops | ~$0.25 | ~$1.30 | ~$6.50 | ~$13 |
| Queues | ~$0 | ~$0.05 | ~$0.20 | ~$0.40 |
| Workflows (incl. steps) | ~$0.50 | ~$2 | ~$9 | ~$18 |
| Durable Objects (if kept) | ~$1 | ~$3 | ~$12 | ~$24 |
| Email | $0 | $10 | $25 | $40 |
| **Edge plan (Pro, if rate rules/WAF needed)** | $25 | $25 | $25 | $25 |
| **Subtotal** | **≈$32** | **≈$48** | **≈$90** | **≈$135–165** |
| PDF render host (COST-01) | not costed | not costed | not costed | not costed |
| R2 replication (REL-03) | + storage | + storage | + storage | + storage |

Two conclusions the original table cannot show: at small scale the **edge plan, not compute, is the dominant fixed
cost**; and the model is missing two components (PDF host, file replication) that are required by other documents.

## 5. Scalability verdict by tier

| Tier | Verdict | Constraint that binds first |
|---|---|---|
| 2 ws / 16 users | Trivially fine | None |
| 10 ws / 80 users | Fine | Edge plan tier (if Pro) |
| 50 ws / 400 users | Fine | D1 write bursts during bulk upload |
| 100 ws / 800 users | Fine on paper | Single-threaded D1 at peak; AI spend |
| 250 ws | Needs work | Workflow step budget, D1 rows-written billing, queue consumer concurrency (250 max) |
| 1,000 ws | Re-architecture | D1 single-threaded throughput and the 10 GB wall; consider option C or Postgres |

## 6. What must be measured before any pricing decision

1. **C** — cost per AI call with the real prompt and a real 6-page script (P1).
2. **CPU per sign-in** — scrypt on Workers, to confirm the 30 s default is never approached (P2).
3. **Worker duration for a 40 MB upload** — decides the presigned-URL question (P1/P5, ARC-05).
4. **Render time and host cost per report** (P1, COST-01).
5. **Actual D1 bytes per submission** after a week of pilot traffic (P5) — validates or refutes COST-02.

Until 1–5 exist, every figure in both this document and the source is an estimate, and the pricing decision is
premature.
