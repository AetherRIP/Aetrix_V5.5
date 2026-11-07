# Aetrix V5.5 — agent skill catalog

**Purpose:** the curated record of every agent skill available in this repository, why it is
here, where it came from, and how it was installed.

- Installed set: **48 skills** — 18 pre-existing design/UX skills (2026-11-03, see
  [`.agents/SKILLS_INDEX.md`](../../.agents/SKILLS_INDEX.md)) + **25 external engineering
  skills** + **5 Aetrix-specific skills** (this mission, 2026-11-07).
- Location: `.agents/skills/<name>/SKILL.md` — the highest-priority project skill directory
  for the Freebuff desktop runtime.
- Reproducibility: `skills-lock.json` at the repository root pins source, path and content
  hash for all 25 external skills.
- Format: [Agent Skills](https://agentskills.io/specification) — a directory with
  `SKILL.md` (`name` + `description` frontmatter, instructions, optional
  `references/`, `scripts/`, `assets/`).

## 1. Not all of these are the same thing

| Kind | What it is | In this repository |
|---|---|---|
| **Skill** | A folder of instructions + optional references the agent loads on demand | `.agents/skills/*` |
| **Plugin** | A vendor bundle that may ship skills, hooks, commands and MCP servers together | Trail of Bits and `obra/superpowers` ship plugins; only individual skills were taken |
| **MCP server** | A running process exposing tools over a protocol | Not installed here; the Freebuff app already exposes browser/file/integration tools |
| **CLI tool** | An executable an agent drives (`playwright-cli`, `wrangler`, `ruff`) | Used directly, not a skill; the `playwright-cli` *skill* documents the tool |
| **Documentation** | Prose a human reads | `docs/`, upstream READMEs — not installed as skills |

Installing a skill does not install its CLI. Several skills below reference tools that are
not present (see §6 Dependencies).

## 2. Activation model

Per the Agent Skills specification, skills load by **progressive disclosure**:

1. **Discovery** — the agent sees only `name` + `description` at session start.
2. **Activation** — when a task matches a description, the agent reads the full `SKILL.md`.
3. **Execution** — it follows the instructions, loading `references/` only if needed.

Every skill below is therefore **model-invoked (passive)**: it activates from its
description, not from a typed command. Two deliberate consequences:

- Descriptions are written with trigger words ("Use when…", "Load before…"), because the
  description is the entire activation signal.
- The set is kept tight (25 external skills ≈ one-line descriptions each) so discovery does
  not turn into instruction noise.

`AGENTS.md` at the repository root is the second, stronger channel: the Freebuff runtime
injects it into every session (`KNOWLEDGE_FILE_NAMES = ['AGENTS.md','CLAUDE.md']`, AGENTS.md
wins) and it contains the task → skill routing table.

## 3. External skills installed (25)

Provenance: shallow clone at the commit shown; installed with
`npx skills@latest add <repo> -s <name> -y --agent universal --copy`, which writes
`.agents/skills/<name>/` and records the hash in `skills-lock.json`.

### 3.1 Engineering workflow — `obra/superpowers` @ `22f0b46` (MIT)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `test-driven-development` | testing | essential | The engine is a correctness product with 200+ tests; RED→GREEN→REFACTOR with a failing test first is the cheapest guard against "looks right" marking code. |
| `verification-before-completion` | process | essential | Directly targets this repository's failure mode: claiming success without running the gate. |
| `writing-plans` | process | high | Multi-layer work (migration + service + API + UI) needs an ordered, verifiable plan before edits. |
| `receiving-code-review` | process | high | Demands technical rigour when review feedback arrives instead of reflexive agreement — relevant when an external reviewer is wrong about Aetrix invariants. |
| `dispatching-parallel-agents` | process | optional | Freebuff can spawn subagents; this is the discipline for independent read-only investigations. |

Links: <https://github.com/obra/superpowers> ·
<https://github.com/obra/superpowers/tree/main/skills>

### 3.2 Architecture and domain — `mattpocock/skills` @ `4ae2317` (MIT)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `code-review` | review | essential | Two-axis review (documented standards **and** the spec) against a fixed diff base — fits a repo with ADRs and an explicit status contract. |
| `codebase-design` | architecture | essential | Deep-module vocabulary for the engine's seams (provider boundary, repositories, job service) so new code deepens modules instead of widening interfaces. |
| `domain-modeling` | architecture | high | Aetrix has heavy domain language (tenant, blueprint version, extraction, override). This keeps a glossary and ADRs honest. |
| `diagnosing-bugs` | debugging | high | A structured diagnosis loop for hard bugs and performance regressions in the engine; complements the general debugging skill. |
| `writing-for-agents` | documentation | high | Governs `AGENTS.md`, `SKILL.md` and ADR prose so future sessions get facts, not marketing. |

Links: <https://github.com/mattpocock/skills> ·
<https://github.com/mattpocock/skills/tree/main/skills/engineering>

### 3.3 Frontend — `vercel-labs/agent-skills` @ `1a2c79d` (MIT per file metadata)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `vercel-react-best-practices` | frontend | high | Waterfalls, bundle size, re-render and rendering rules for the React 19 / TanStack Start surface. |
| `vercel-composition-patterns` | frontend | optional | Compound components and context over boolean-prop sprawl — the app shell already has a profile menu, sheet and tabs that will grow. |

Links: <https://github.com/vercel-labs/agent-skills>
(installed directory names match the upstream `name:` field)

### 3.4 Data platform — `supabase/agent-skills` @ `c9be0e9` (MIT)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `supabase` | backend/auth | essential | Supabase is the development PostgreSQL and the frontend's identity provider. Covers Auth, sessions, JWT, RLS surprises, CLI and SSR clients. |
| `supabase-postgres-best-practices` | database | essential | Schema, types, migrations, RLS policy testing, indexes, EXPLAIN, locking — the engine's data layer is PostgreSQL-only. |

Links: <https://github.com/supabase/agent-skills>

### 3.5 Edge deployment — `cloudflare/skills` @ `6eb6c78` (Apache-2.0)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `frameworks-on-cloudflare` | deploy | essential | Names TanStack Start explicitly and describes the Cloudflare Vite plugin path the frontend uses. |
| `workers-best-practices` | deploy | high | Production Worker patterns (bindings, streaming, caching) for the marketing/app Worker. |
| `wrangler` | deploy | high | The actual CLI: local dev, previews, deploy, bindings. Prevents guessed commands. |

Links: <https://github.com/cloudflare/skills>

### 3.6 Quality, review and security — `getsentry/skills` @ `e94f222` (Apache-2.0)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `security-review` | security | essential | OWASP-class review of the API, tenant scoping, uploads and the auth callback. |
| `find-bugs` | review | essential | Defect hunt over branch changes, independent of style. |
| `code-simplifier` | quality | high | Removes incidental complexity without behaviour change — useful after feature work on a codebase this dense. |
| `skill-scanner` | meta/security | high | Scans skill folders for prompt injection, obfuscation, exfiltration and excessive permissions; used to audit this install. |
| `agents-md` | documentation | high | Keeps `AGENTS.md` concise and current — the passive channel that must not rot. |

Links: <https://github.com/getsentry/skills>

### 3.7 Python and test rigour — `trailofbits/skills` @ `e4dd0bb` (CC BY-SA 4.0)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `modern-python` | backend | high | Typing, `pyproject` and ruff discipline for the FastAPI engine. Advises `uv`/`ty`, which Aetrix does not use — follow the principles, keep the existing pip/ruff/pytest toolchain. |
| `property-based-testing` | testing | optional | Hypothesis for the math/document domain: invariants that must hold for all inputs (page ordering, mapping, parsing) are exactly where example tests are weakest. |

Links: <https://github.com/trailofbits/skills>

### 3.8 Browser verification — `microsoft/playwright-cli` @ `4bc00fb` (Apache-2.0)

| Skill | Category | Priority | Why Aetrix needs it |
|---|---|---|---|
| `playwright-cli` | testing | optional | Browser driving plus the reference notes on traces, storage state, request mocking and test generation. Aetrix already runs Playwright; the CLI binary is **not** installed (see §6). |

Links: <https://github.com/microsoft/playwright-cli>

## 4. Aetrix-specific skills (5)

Written for this repository from verified facts; no external source, no credentials.

| Skill | Purpose | Activation |
|---|---|---|
| `aetrix-architecture` | Layer map, documented-vs-implemented split, seven invariants, implemented/unimplemented status, change routing | Any non-trivial change or status claim |
| `aetrix-backend` | FastAPI/SQLAlchemy/Alembic/worker/provider conventions, tenant rule, style, pytest + ruff commands | Work under `backend/` |
| `aetrix-frontend` | TanStack routing, shell/hub components, token and motion rules, `ApiResult` honesty, Supabase auth, build/e2e commands | Work under `frontend/` |
| `aetrix-security` | Trust boundaries, tenancy/IDOR/RLS checklist, secrets, uploads, provider output, review method | Auth, data isolation, uploads, secrets, review |
| `aetrix-verification` | The verification matrix, exact commands, exit-status rules, claim discipline | Before declaring completion |

## 5. Rejected candidates

| Candidate | Source | Reason |
|---|---|---|
| `systematic-debugging` | obra/superpowers | **Duplicate** — the account-level Freebuff skill is this exact skill (identical text and references). Installing both would load the same instructions twice. |
| `brainstorming`, `frontend-design`, `web-design-guidelines` | obra / anthropics / vercel-labs | Already present as account skills and/or project design skills (`frontend-design` exists in `.agents/skills`). |
| `requesting-code-review` | obra/superpowers | The review *request* is already covered by `code-review` + `find-bugs`; `receiving-code-review` covers the harder half. |
| `executing-plans`, `subagent-driven-development` | obra/superpowers | Written for harnesses with a plan-executor convention; overlaps `writing-plans` and `dispatching-parallel-agents`, and prescribes branch-per-task/commit-per-task workflows this repo does not use. |
| `finishing-a-development-branch`, `using-git-worktrees` | obra/superpowers | Git workflow opinions; Aetrix has no branch/PR convention to enforce, and the mission forbids adding process that changes repository state. |
| `tdd` | mattpocock/skills | **Duplicate of purpose** — one TDD skill only; the superpowers version is more prescriptive about proving the test fails first. |
| `improve-codebase-architecture`, `grill-with-docs`, `retro`, `triage`, `wayfinder`, `to-spec`, `implement`, `prototype` | mattpocock/skills | Depend on an issue tracker, an interview loop or an HTML report workflow; `codebase-design` + `domain-modeling` deliver the architecture value without the process. |
| `web-design-guidelines` | vercel-labs | Same skill as the account-level Freebuff skill. |
| `react-view-transitions` | vercel-labs | Its API (`<ViewTransition>`, `addTransitionType`) is React 19.2/Next-oriented; Aetrix's motion layer is CSS keyframes verified under `prefers-reduced-motion`. Adopting View Transitions is a product decision, not a skill install. |
| `deploy-to-vercel`, `vercel-cli-with-tokens`, `vercel-optimize`, `react-native-skills` | vercel-labs | Wrong platform (Vercel/React Native); Aetrix deploys to Cloudflare. |
| `cloudflare` (product catalog), `cf-cli`, `web-perf`, `durable-objects`, `agents-sdk`, `cloudflare-one*`, `basin`, `gateway-workers`, `sandbox*`, `k2`, `turnstile-spin`, `cloudflare-email-service`, `workers-profiling` | cloudflare/skills | Products Aetrix does not use. `web-perf` duplicates the React performance guidance for the current surface. |
| `security-model`, `gha-security-review`, `secret-serialization`, `coding-standards` | getsentry/skills | `security-model` would duplicate `docs/security/`; the GitHub-Actions and Sentry-internal skills do not apply. |
| `commit`, `create-branch`, `pr-writer`, `iterate-pr`, `gh-review-requests`, `pr-screenshots` | getsentry/skills | Sentry's git/PR conventions and `gh` dependency; not this repository's workflow. |
| `supply-chain-risk-auditor` | trailofbits/skills | Genuinely useful but engagement-oriented: it runs collector scripts that query npm/PyPI/registries. Kept as a documented option rather than an installed default (see §6). |
| `static-analysis` (semgrep / codeql / sarif) | trailofbits/skills | Requires semgrep, CodeQL or SARIF tooling that is not installed and would add a dependency chain. |
| `differential-review`, `sharp-edges`, `mutation-testing`, `variant-analysis` | trailofbits/skills | Overlap `find-bugs` + `security-review` at a heavier process cost. |
| `testing-handbook-skills` (24 skills) | trailofbits/skills | C/C++ fuzzing and sanitizers (libFuzzer, AFL++, ASan) — wrong runtime for a Python/TS product. |
| `modern-cpp`, `rust-review`, `c-review`, smart-contract and reverse-engineering plugins | trailofbits/skills | Wrong language/domain. |
| `skill-creator`, `mcp-builder`, `docx`, `pdf`, `pptx`, `xlsx`, `canvas-design`, `theme-factory`, `brand-guidelines`, `webapp-testing`, `web-artifacts-builder` | anthropics/skills | Off-scope or duplicated by better-fitting skills; used as authoring reference only. |
| `ui-styling`, `brand`, `banner-design`, `slides`, `design` (umbrella) | nextlevelbuilder | Already covered by the installed `design-system` / `ui-ux-pro-max`; the umbrella pulls external image APIs. |
| Everything else in `j4flmao/agent-skills` (~600) and `managedcode/dotnet-skills` (200+) | — | Not inspected further: the relevant design/WPF skills are already installed from the 2026-11-03 pass. |

## 6. Dependencies and tool prerequisites

| Skill | Needs | State |
|---|---|---|
| `playwright-cli` | `@playwright/cli` binary (`npm i -g @playwright/cli`) | **Not installed.** Aetrix already has `@playwright/test` and the Freebuff browser tools; the skill's Markdown is still accurate for test/trace guidance. Install the CLI only if a task needs interactive page driving. |
| `modern-python` | `uv`, `ty` (optional), `ruff` | `ruff` present in `backend/.venv`; `uv`/`ty` absent — follow the principles with pip + ruff. |
| `supply-chain-risk-auditor` (not installed) | network access to npm/PyPI registries | n/a |
| `property-based-testing` | `hypothesis` for Python, `fast-check` for TS | Not a dependency of the repo; add it only when writing a property test, and ask first. |
| All others | none | Markdown + references only; no scripts executed during install. |

## 7. Licensing

Upstream licenses are preserved by reference; the CLI copies `SKILL.md` and its references
but not the repository `LICENSE` file. Attribution:

| Source | License | Notes |
|---|---|---|
| obra/superpowers | MIT | © Jesse Vincent |
| mattpocock/skills | MIT | © Matt Pocock |
| supabase/agent-skills | MIT | © Supabase |
| vercel-labs/agent-skills | MIT (declared in each `SKILL.md`) | No root LICENSE file upstream |
| cloudflare/skills | Apache-2.0 | Notice retention required; content unmodified |
| getsentry/skills | Apache-2.0 | Notice retention required; content unmodified |
| trailofbits/skills | **CC BY-SA 4.0** | Share-alike: unmodified use is fine; any *modified* copy must stay CC BY-SA. Do not edit those two skills in place — add an Aetrix note beside them instead. |
| microsoft/playwright-cli | Apache-2.0 | Content unmodified |
| Aetrix-authored (5) | Proprietary | Written for this repository |

No skill was modified after download. No file was renamed except the two Vercel skills,
which the CLI installed under their declared `name:` (`vercel-react-best-practices`,
`vercel-composition-patterns`) — the spec requires `name` to match the directory.

## 8. Maintenance

- List: `npx skills list`
- Update: `npx skills update -p` (project scope); review the diff before accepting — an
  upstream change can alter a trigger description and silently change behaviour.
- Remove: `npx skills remove -s <name>`
- Restore from lock: `npx skills experimental_install` (CI-friendly, `--frozen-lockfile`).
- Audit after every add/update: run `skill-scanner` (§4 in the report) and re-run the
  frontmatter validator (name matches directory, description present).
- Re-check duplicates whenever a new account-level Freebuff skill appears: this repository
  already lost three candidates to duplication.
