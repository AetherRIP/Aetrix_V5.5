# Screen Inventory

**Status:** RECOMMENDED. 48 screens. "States" lists what must be designed for each screen, not just the
happy path. Permission keys reference `../product/USER_ROLES_AND_PERMISSIONS.md`.

## Public

| # | Screen | Purpose | Key elements | States |
|---|---|---|---|---|
| 1 | Landing | Explain the product in one screen | Headline, one product image (real UI, not abstract), proof, single CTA | default |
| 2 | Features | Capability detail | Section per capability, no icon grids | default |
| 3 | Pricing | Plan comparison | 3 plans, usage limits, FAQ | no-plans-yet variant |
| 4 | Use cases | School/department framing | 2 narratives | default |
| 5 | Security & privacy | Trust page | Data location, retention, sub-processors, DPA link | default |
| 6 | FAQ | Objection handling | Accordion, 20 questions | default |
| 7 | Contact | Sales + support | Form, response-time promise | sent / error |
| 8 | Docs index | Help centre | Search, categories, popular articles | empty search |
| 9 | Doc article | Answer one question | Article, TOC, feedback | default |
| 10 | Legal pages | Terms, privacy, DPA, cookies | Versioned documents | default |
| 11 | Status | Availability | Component status, incident history | degraded / outage |
| 12 | Changelog | Release notes | Reverse-chronological entries | default |
| 13 | 404 / 500 | Recover gracefully | Explanation + route back | default |

## Auth and onboarding

| # | Screen | Purpose | Key elements | States |
|---|---|---|---|---|
| 14 | Signup | Create account | Email, password strength, Google, Turnstile | taken / weak / rate-limited |
| 15 | Login | Return | Email, password, passkey, "remember me" | wrong / locked / unverified |
| 16 | Verify email | Confirm identity | Resend, change email | expired / already-verified |
| 17 | Forgot / reset | Recover access | Email → token → new password | expired / reused |
| 18 | MFA challenge | Step up | TOTP, recovery code | wrong / locked |
| 19 | Invite acceptance | Join a workspace | Workspace name, inviter, role | expired / wrong-email / suspended |
| 20 | Workspace picker | Choose context | Membership cards with roles | single / empty |
| 21 | Create workspace | First workspace | Name, slug, region notice | slug taken |
| 22 | Onboarding checklist | Guide to first script | 6 steps, resumable, skip Classroom | partial / abandoned |
| 23 | Device & session manager | Control sessions | Session list, revoke, sign out everywhere | none |

## Core app

| # | Screen | Purpose | Key elements | States |
|---|---|---|---|---|
| 24 | Home dashboard | State of the workspace | Exception list, throughput readouts, workload, recent activity | new / quiet / busy |
| 25 | Inbox | What needs me | Item list, type filters, age | empty (celebrated, not sad) |
| 26 | Assignments list | Find work | Table: title, class, status, progress, owner | empty / filtered-empty |
| 27 | Assignment overview | One assignment's state | Status strip, progress, blockers, next action | draft / marking / review / published / archived |
| 28 | Assignment editor | Create/edit | Metadata, class, deadlines, defaults | validation |
| 29 | Scheme upload + extraction | Turn a PDF into a blueprint | Upload, page preview, extraction progress | scanning / mismatch |
| 30 | Scheme review | Human confirms the blueprint | Question table, max marks, M/A/B, exclude/include | conflicts / locked |
| 31 | Submissions table | All scripts | Rows per student, status, marks, assignee | empty / partial / bulk-selected |
| 32 | Upload submissions | Add scripts | Drag-drop, multipart progress, per-file validation | resumable / rejected / duplicate |
| 33 | Marking queue | Next script | One-at-a-time card, keyboard advance, filters | empty / paused / circuit-open |
| 34 | Review canvas | Mark and correct | PDF pane, per-question marks, explanation, comment, override | loading / review-needed / locked / conflict |
| 35 | Submission detail | One script's record | All marks, history, audit, files | approved / overridden |
| 36 | Results / grade matrix | Marks across the class | Pivot table, totals, distribution, outliers | empty / provisional |
| 37 | Class report | Printable summary | PDF preview, download, attach-to-Classroom | generating / failed |
| 38 | Classes list / detail | Structure | Class table, roster, performance | empty |
| 39 | Students list | Roster | Table with identifiers, counts | imported / empty |
| 40 | Student profile | One student | History, trend, notes | no-results |
| 41 | Bulk import | CSV onboarding | Template, mapping, dry-run preview, errors | invalid rows / partial commit |
| 42 | Reports hub | Cross-assignment analysis | Filters, charts, export | insufficient-data |
| 43 | Activity & audit | Who did what | Filterable log, export | empty / permission-denied |
| 44 | Members | People | Table, roles, status, invite | invited / suspended |

## Settings, admin and help

| # | Screen | Purpose | Key elements | States |
|---|---|---|---|---|
| 45 | Settings (7 tabs) | Configure workspace | General, branding, academic, corrections, notifications, retention | saved / unsaved-changes |
| 46 | Credentials | Manage AI providers | Provider list, key state, test, rotate, quota | untested / invalid / cooling-down |
| 47 | Usage & quotas | Consumption | Storage, jobs, tokens, per-assignment breakdown | near-limit / exceeded |
| 48 | Classroom integration | Connect Google | OAuth, course selection, allow-list, health | disconnected / token-expired / forbidden |
| 49 | Danger zone | Delete/export | Counts, typed confirmation, grace period | pending-deletion |
| 50 | Help & shortcuts | Self-service | Search, shortcuts (`?`), contact | default |
| 51 | Platform: workspaces | Operator directory | Table, status, usage, suspend | default |
| 52 | Platform: health & queues | Operate the service | Queue depth, DLQ, provider health, error rate | degraded / incident |
| 53 | Platform: support grants | Consent-based access | Grant list, scope, expiry, revoke | none / active / expired |
| 54 | Platform: audit | Platform events | Search, export | default |

## Screens the brief did not list but the product needs

- **Job detail drawer** (not a page): every job's attempts, classified errors, prepared-input reuse, and the
  single next action. Reachable from anywhere via the top-bar indicator.
- **Conflict resolution** (route, not modal): shown when a mark save loses a version race.
- **Provider outage banner state**: a global, dismissible-but-persistent strip when a circuit is open.
- **Permission-denied page**: distinct from 404, only for "you are a member but lack this permission".
- **Session-expired interstitial**: preserves the intended URL and unsaved draft.
- **Deletion grace-period banner**: workspace-wide, with the purge date and a cancel action.
- **Print stylesheet for Results and Report** — a real deliverable, since teachers print.
