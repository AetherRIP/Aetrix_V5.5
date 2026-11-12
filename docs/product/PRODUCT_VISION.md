# Product Vision

**Status:** RECOMMENDED · **Owner decisions required:** see [`../decisions/OPEN_QUESTIONS.md`](../decisions/OPEN_QUESTIONS.md)

## One line

Aetrix V5.5 marks IGCSE mathematics homework the way an experienced examiner would — deterministically,
against the official mark scheme, with a human deciding every mark that matters — and lets a department
do it together, in one shared workspace, without sending a single script to a browser tab.

## Who it is for

| Role | Job to be done | Today (V5) |
|---|---|---|
| **Assistant / marker** | Get through a stack of scripts without losing the thread | Works on one machine, one operator |
| **Supervisor / head of maths** | Know that marking is consistent and on time | No cross-person view |
| **Workspace admin** | Manage classes, staff access, API keys, storage | Local settings file |
| **Workspace owner** | Own the account, the data and the bill | Not a concept in V5 |
| **Platform operator** | Run many customer workspaces safely | Not a concept in V5 |
| **Student (indirect)** | Receive a correct, explained mark | Receives a PDF via Classroom |

The buyer is a school or a maths department; the daily user is an assistant or a teacher marking at
speed. Both must be served, and they want different things from the same screen — the assistant wants
the next script, the supervisor wants the exception.

## The problem V5 solves, and where it stops

V5 is a genuinely strong single-operator product: a preserved marking engine at `temperature: 0` with a
fixed seed, a mark-scheme **blueprint** that fixes the official question list and max marks once per
scheme, `verify.py` reconciliation after marking, a `result_guard` that refuses to let a valid mark be
silently replaced, a multi-key Gemini manager with cooldowns and key-scoped file re-upload, a persistent
job manager with duplicate prevention and crash recovery, a classified retry policy with a provider
circuit breaker, and Google Classroom integration that attaches reports and publishes draft grades with a
`NEEDS_VERIFICATION` state instead of pretending an interrupted write succeeded.

What it cannot do is be operated by more than one person, from more than one place, for more than one
organisation. There is no tenancy, no shared identity, no authorisation boundary, no hosted durability,
and no way for a supervisor to see whether the marking is any good.

**V5.5 is therefore not a redesign. It is a re-hosting of a proven marking system behind a real
multi-tenant product surface — without weakening a single mark-integrity guarantee.**

## Product promise (what we will not trade away)

1. **A mark is never silently wrong.** Missing question → `REVIEW`, never `0`. Max marks forced back to
   the official blueprint value. Verification reports, it does not rewrite. Human override is recorded
   with who, when, and why.
2. **The browser never marks.** Correction is a server-side job. No API key, no prompt, no mark scheme
   ever reaches client JavaScript.
3. **One workspace cannot see another.** Enforced in the data layer and proven by a standing test suite,
   not by a `WHERE` clause someone remembered to write.
4. **Classroom is a boundary, not the product.** Google Classroom is an integration that can fail
   independently; nothing about marking depends on it being reachable.
5. **The supervisor can always answer "what is the state of this?"** Every job has a state, every state
5. **The supervisor can always answer "what is the state of this?"** Every job has a state, every state
   has an owner, and an interrupted remote write is `NEEDS_VERIFICATION`, never a guess.

## Design principles

1. **Instrument, not dashboard.** The interface reports measurements — marks, deltas, counts, timings —
   with ledger discipline; it does not decorate them.
2. **Density with air.** Markers read tables for hours. Rows are tight, figures are tabular, and
   whitespace is spent on grouping rather than on padding.
3. **The exception leads.** A screen's most prominent element is the thing that needs a human: the
   `REVIEW` item, the failed grade write, the missing script.
4. **Keyboard first, mouse welcome.** A marker grading 200 scripts should not need the mouse twice.
5. **States are named, not implied.** Pending, running, parked, failed, needs-verification, approved —
   each has a word, a colour and a next action.
6. **Nothing destructive without a stated consequence.** Deleting a workspace names what is deleted.
7. **Accessibility is a design input**, not a QA phase: contrast, focus order, keyboard paths and reduced
   motion are decided in the mockup.

## What changes from V5 to V5.5

| Dimension | V5 | V5.5 |
|---|---|---|
| Operator | One person, one machine | Many people, many workspaces, one platform |
| Storage | Local SQLite in `DATA_DIR` | D1 (metadata) + R2 (files) |
| Identity | Local device token, keys in settings | Platform account, membership, roles |
| Correction | In-process worker on the operator's machine | Durable server-side job (Queues + Workflows) |
| Files | Local disk / Drive download | R2 with signed, expiring access |
| Collaboration | None | Assignment ownership, review requests, comments, live progress |
| Oversight | Local health checks | Workspace and platform admin surfaces, audit log |
| Delivery | Localhost web + WPF | Hosted web application on Cloudflare |

## Non-goals for V5.5

- **Not an LMS.** No timetable, attendance, parent portal or gradebook of record. Classroom remains the
  system of record for marks where it is used.
- **Not a general marking tool.** Edexcel IGCSE 4MA1 mathematics with a structured mark scheme is the
  supported domain. Other boards or subjects are a future product decision, not a V5.5 assumption.
- **Not an AI research project.** Model choice is configuration with a benchmark, not a differentiator.
- **Not a billing platform.** Plans are designed for but not built (roadmap phase 10).
- **Not mobile-first.** Mobile is read-and-approve only; marking needs a large screen.

## Success metrics (proposed)

| Metric | Target | Why |
|---|---|---|
| Jobs reaching a terminal mark | ≥ 99% within 24 h | Core promise |
| Mark-integrity escapes found later | **0** | Non-negotiable |
| Median end-to-end time per script incl. review | ≤ 90 s | Must beat manual marking |
| Supervisor sampled review coverage | ≥ 10% per assignment | Consistency, not only throughput |
| Signup to first marked script | < 15 min | Adoption gate |
| Cross-tenant access incidents | **0** | Trust |
| AI cost per script | Tracked from day one | Margin is decided here |

## Risks to the thesis

- **The domain is narrow** — one board, one subject, one qualification. Tenancy must therefore be cheap
  to operate (it is: shared D1, R2, Queues) and pricing must not assume scale that does not exist.
- **AI cost per script can exceed willingness to pay** if reviewers casually re-run failures. Metering and
  per-workspace quotas are in MVP even though billing is not.
- **Review quality is the product.** A fast system producing marks nobody trusts has no value, so the
  review surface is a P0 screen rather than later polish.
