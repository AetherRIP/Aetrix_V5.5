# Cost and Scalability

**Status:** ESTIMATE. Every figure is derived from stated assumptions and unit prices read from official
Cloudflare pricing pages on 2026-11-03. **No figure here is a quote**, and no account exists yet.

## 1. Unit prices used (VERIFIED snapshots)

| Item | Price |
|---|---|
| Workers Paid | $5/mo base, includes 30M CPU-ms; +$0.30/M requests (10M included) |
| D1 storage | 5 GB included; +$0.75/GB-mo; rows read 25B/mo included; +$0.001/M rows |
| D1 rows written | 50M/mo included; +$1.00/M |
| R2 storage | $0.015/GB-mo (10 GB free); Class A $4.50/M; Class B $0.36/M; egress free |
| Queues | 1M ops/mo included; +$0.40/M |
| Durable Objects | 1M req/mo + $0.15/M; 400k GB-s + $12.50/M GB-s; SQL storage 5 GB-mo + $0.20/GB-mo |
| Workflows | billed through Workers requests/CPU |
| Turnstile | free |

## 2. Workload assumptions (explicit, so they can be corrected)

| Assumption | Value | Confidence |
|---|---|---|
| Assistants per workspace | 8 | ASSUMPTION (brief says 5–10) |
| Active assignments per workspace per month | 12 | ASSUMPTION |
| Students per assignment | 25 | ASSUMPTION |
| Submissions per workspace per month | 300 | derived (12 × 25) |
| Pages per script | 6 | ASSUMPTION |
| Average scanned page size | 400 KB | ASSUMPTION |
| Bytes per submission | ~2.4 MB | derived |
| Results rows per submission | 12 questions | ASSUMPTION |
| AI calls per submission | 1.3 (retries + re-marks) | ASSUMPTION |
| Read:write ratio on D1 | 20:1 | ASSUMPTION |
| Page views per assistant per day | 120 | ASSUMPTION |
| Real-time connections | assistants × 1.5 tabs | derived |

**The AI cost per submission is the single unknown that dominates the model** and is deliberately left as a
variable `C` in §4 rather than invented.

## 3. Infrastructure by scenario

| Metric | 2 ws | 10 ws | 50 ws | 100 ws |
|---|---|---|---|---|
| Assistants | 16 | 80 | 400 | 800 |
| Submissions/month | 600 | 3,000 | 15,000 | 30,000 |
| R2 storage, year 1 (GB, cumulative) | 17 | 86 | 432 | 864 |
| D1 storage (MB) | ~15 | ~75 | ~375 | ~750 |
| API requests/month (est.) | 0.6M | 2.9M | 14M | 29M |
| Queue messages/month | ~6k | 30k | 150k | 300k |
| AI calls/month | 780 | 3,900 | 19,500 | 39,000 |
| Concurrent job consumers needed | 2 | 5 | 20 | 40 |

D1 storage is a rounding error even at 100 workspaces (≈0.75 GB of a 10 GB database) — which is precisely why
metadata-only storage is the right shape.

## 4. Monthly infrastructure estimate (USD)

| Line | 2 ws | 10 ws | 50 ws | 100 ws |
|---|---|---|---|---|
| Workers Paid base | 5 | 5 | 5 | 25¹ |
| Requests overage | ~0 | ~0 | ~2 | ~6 |
| D1 storage | 0 | 0 | 0 | ~0.50 |
| D1 rows read/written | ~0 | ~1 | ~4 | ~8 |
| R2 storage (year-1 average) | ~0.15 | ~0.80 | ~4 | ~8 |
| R2 operations | ~0.10 | ~0.50 | ~2.50 | ~5 |
| Queues | ~0 | ~0.05 | ~0.20 | ~0.40 |
| Durable Objects | ~1 | ~3 | ~12 | ~24 |
| Workflows | ~0.50 | ~2 | ~9 | ~18 |
| Email (transactional) | 0 | 10 | 25 | 40 |
| **Infrastructure subtotal** | **≈ $7** | **≈ $23** | **≈ $64** | **≈ $135** |

¹ multiple Workers/accounts if we shard by environment or exceed the per-account request bundle.

Rounded, excluding AI spend and excluding staff. Add monitoring/logging platform costs if the free tier is
exceeded (not estimated here).

## 5. AI spend (the real variable)

`AI monthly cost = submissions × calls per submission × C`

| C (cost per call) | 10 ws | 50 ws | 100 ws |
|---|---|---|---|
| $0.002 | $8 | $39 | $78 |
| $0.01 | $39 | $195 | $390 |
| $0.03 | $117 | $585 | $1,170 |
| $0.08 | $312 | $1,560 | $3,120 |

**Action:** measure `C` in phase 1 with the real prompt and a real script set, then replace this table. Until
then, no pricing decision is safe. A vision-capable model reading 6 pages is not cheap; a text-extraction
pre-pass may cut it substantially — that is an engineering experiment, not a guess to be baked into the plan.

## 6. Cost traps, ranked

1. **Re-running failures casually.** Every retry is money. Quotas, per-job budgets and a "duplicate result"
   check exist for this reason.
2. **Storing full-resolution scans forever.** Page images dominate R2 growth; retention defaults and
   thumbnail derivatives matter more than compression tricks.
3. **Durable Object duration.** Without hibernation, idle sockets bill continuously. Hibernation is required.
4. **Log/metric cardinality.** Per-user labels can cost more than the database.
5. **Egress is free on R2 but not on Containers** (if we adopt them for PDF rendering) — that changes the
   PDF decision's economics.
6. **Rebuilding reports on every view.** Generate once, store in R2, serve signed.

## 7. Scaling limits and what breaks first

| Order | Limit | Symptom | Response |
|---|---|---|---|
| 1 | Provider rate limit / quota | Jobs park, throughput plateaus | Per-workspace keys (already designed), queue prioritisation |
| 2 | D1 single-writer throughput | Write p95 rises sharply | Keep writes small; move job state churn to fewer updates; consider sharding by workspace later |
| 3 | Queue consumer concurrency | Backlog grows | Raise concurrency; shard queues per workspace tier |
| 4 | DO per-object throughput | Progress lags | More coalescing; per-workspace sharding by channel |
| 5 | D1 10 GB per database | Hard stop | Already far away (≈0.75 GB at 100 ws); if needed, tier tenants onto separate DBs (option C) |
| 6 | Workers request pricing | Bill grows linearly | Fine at this scale; static asset caching absorbs most traffic |

## 8. Break-even thinking (not a pricing decision)

At 100 workspaces the infrastructure line is roughly $135/mo before AI, i.e. **≈$0.0045 per submission** in
platform cost. AI at $0.03/call is ≈$0.05 per submission — an order of magnitude larger. Therefore:

- pricing must be driven by AI cost, not by hosting;
- the cheapest lever is reducing calls per submission (better first-pass accuracy, fewer re-marks);
- a per-workspace quota is a financial control, not a paywall.
