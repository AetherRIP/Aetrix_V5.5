# Data Privacy

**Status:** RECOMMENDED engineering requirements. **Not legal advice, and not a compliance claim.**
Jurisdiction and lawful basis must be confirmed by the operator's counsel (Q1 in `../decisions/OPEN_QUESTIONS.md`).

## 1. Data classification

| Class | Examples | Handling |
|---|---|---|
| **C4 — Student personal data** | Full name, student id, marks, script images | Encrypted at rest, PII-gated permission, never in logs, retention-limited |
| **C3 — Staff personal data** | Email, name, IP, session metadata | Standard protection, access on need |
| **C2 — Commercial** | Usage counts, provider fingerprints, plan | Internal only |
| **C1 — Public** | Marketing copy, docs | Unrestricted |

Students are frequently **minors**. That makes C4 the highest-risk class in the product and drives every
default below.

## 2. Data minimisation (what we deliberately do not collect)

- No student email addresses, dates of birth, addresses, photos or free-text SEN notes.
- No postal addresses or phone numbers for staff.
- `display_name` (marker-facing label, may be a nickname) is separate from `full_name`; lists default to the
  former.
- No analytics on individual student behaviour; product analytics are aggregate and staff-level only.
- No third-party advertising or session-replay SDKs anywhere.

## 3. Lawful basis and roles (to be confirmed)

| Question | Our assumption | Why it matters |
|---|---|---|
| Who is the controller? | The **school/workspace** is controller; we are a **processor** | Determines whether we need a DPA, and who answers subject requests |
| Lawful basis | Public task / legitimate interest of the school, not consent | Consent from minors is fragile and revocable |
| DPA required? | Yes — a processor agreement per workspace, referenced in Terms | Standard for school data |
| Sub-processors | Cloudflare (hosting), the AI provider, the email provider | Must be listed publicly with purpose and region |
| International transfers | Cloudflare global network; AI provider region TBD | Needs a transfer mechanism if outside UK/EU |

**We will not state "GDPR compliant" in marketing** until counsel confirms the above and the DPA is published.

## 4. Retention (defaults, workspace-configurable within limits)

| Data | Default | Max | Notes |
|---|---|---|---|
| Script files (R2) | 180 days after assignment publication | 24 months | Deletable earlier by the workspace |
| Marks and results | Life of workspace | – | Needed for reporting history |
| Job + attempt records | 90 days after terminal | 12 months | Debugging value decays fast |
| Audit log | 12 months | 24 months | Accountability |
| Sessions | 30 days absolute | – | |
| Invitations | 7 days | – | |
| Usage events | 24 months | – | Billing/quotas |
| Deleted workspace | 14-day grace, then purge | – | Tombstone hash retained |
| Backups (exports) | 35 days rolling | 90 days | Restore drills documented |

A retention sweep is a Cron-triggered Workflow that deletes by `created_at` **within a workspace**, never
across tenants in one statement.

## 5. Data-subject rights — how each is actually served

| Right | Mechanism | SLA |
|---|---|---|
| Access / portability | Workspace export (owner) → JSON + CSV + file manifest, signed 24 h; staff `/me/export` | 30 days (aim 72 h) |
| Rectification | Edit student/staff record; corrections to marks are append-only revisions | immediate |
| Erasure | Student delete (batched, cascading); workspace delete with grace | 30 days |
| Restriction | Workspace can disable marking for a class; support can freeze a workspace | immediate |
| Objection | Contact route → human review | 30 days |
| Breach notification | See §8 | 72 h where required |

Because the **school is the controller**, most subject requests arrive at the school. Our obligation is to
provide the tooling and to respond to the controller's instruction — this must be stated in the DPA.

## 6. AI provider handling — the questions that must be answered before launch

1. Is customer content used for **model training**? (Must be contractually no.)
2. What is the **retention** of uploaded files and prompts on the provider side?
3. Which **region** processes the data, and is there a transfer mechanism?
4. Are **sub-processors** disclosed?
5. Is there a **zero-retention / enterprise** tier available, and at what cost?

Until 1–5 are answered in writing, the privacy page must describe the provider generically and the product
must let a workspace use **its own** provider key, so the contractual relationship can be the customer's.

Design consequence already baked in: per-workspace credentials mean a school may contract directly with the
AI provider. This is a privacy feature, not only a billing convenience.

## 7. Support access and privacy

Operators see aggregates only. Any access to C4 data requires a workspace-owner-issued grant (scope, reason,
≤ 72 h), is visible to the workspace via banner, and each read is audited with the operator identity. There is
no break-glass path that bypasses consent (`SECURITY_REQUIREMENTS.md` SA-1…SA-6).

## 8. Incident response (privacy)

1. **Detect** — alert on anomalous cross-tenant access patterns, mass exports, credential failures.
2. **Contain** — revoke sessions, rotate provider keys, disable the affected route, suspend the workspace.
3. **Assess** — what data, whose, how many, for how long; preserve logs (they are the evidence).
4. **Notify** — controller (workspace owner) first; regulator within 72 h where required; affected
   individuals per the controller's instruction.
5. **Remediate** — root cause, test, post-mortem published to affected customers.

A named incident owner and an out-of-band contact list are required before launch (currently **UNKNOWN**).

## 9. Marketing-site specifics

- Cookie banner only if non-essential cookies exist; the app itself uses only necessary session cookies.
- No third-party trackers on authenticated pages. Ever.
- Privacy policy, DPA and sub-processor list are versioned documents with a changelog.

## 10. Open legal questions (blocking for public launch, not for build)

- Jurisdiction and governing law.
- Whether a DPIA is required (likely, given minors at scale).
- Age threshold assumptions per market.
- Whether exam-paper copyright requires a separate agreement with the board.
