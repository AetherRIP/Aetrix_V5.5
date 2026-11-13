# Aetrix V5.5 — legal documentation and website compliance review

**Date:** 13 November 2026
**Scope:** public website and authenticated legal surfaces (`frontend/`), plus the policy content they publish.
**Excluded by instruction:** the correction engine (`backend/`), the benchmark, prompts, provider
configuration and every engine test. No engine file was modified, committed or deployed by this work.
**Status:** pre-release drafts, published for inspection. This document is an engineering and
product record. It is not legal advice, and it does not certify compliance with any law.

---

## 1. Initial audit findings

### 1.1 What existed before this change

| Area | State found |
|---|---|
| Legal pages | `/terms` and `/privacy` only, both under the public `_marketing` layout with a shared `LegalPage` shell. |
| Legal centre | None. The two documents linked to each other, the homepage and the top of the page. |
| Footer | A "Legal" column with two links (Privacy, Terms). |
| Metadata | Unique title, description and `og:title`/`og:type` per legal page. |
| Prerender | `/privacy` and `/terms` listed in `vite.config.ts`; `scripts/legal-clean-urls.mjs` emitted slashless copies. |
| Cookies | No cookie is written anywhere in the frontend (`document.cookie` is never used). |
| Browser storage | `aetrix:auth` (Supabase session), `aetrix:auth-accounts` (identity only), `aetrix:theme`, `aetrix:rail`, `aetrix:platform-overview-changed-at` in local storage; `aetrix:auth-next`, `aetrix:auth-add`, `aetrix:platform-overview-stale` in session storage. |
| Analytics / advertising | None. No third-party tag, pixel, tag-manager or session-recording script. |
| Registration | None by design: accounts are provisioned by an invitation or an operator. `/sign-in` offers Google OAuth via Supabase PKCE and an optional email/password form. |
| Sign-in legal notice | None. The page had no legal link and no acknowledgement step. |
| Settings | Profile, appearance and session only. No legal or privacy entry point. |
| Account deletion / export | Not implemented. No API, no UI, no self-service path. |
| Existing notes | `LEGAL_REVIEW_NOTES.md` (9 November) recorded verified platform facts, placeholders and open legal decisions. |

### 1.2 Verified platform facts used in the policy text

- **Authentication:** Supabase Auth, Google OAuth with PKCE, session persisted in local storage under
  `aetrix:auth`; browser holds only the Supabase publishable key.
- **Google Classroom:** optional workspace connection, `classroom.courses.readonly` only, tokens
  encrypted by the engine (`backend/app/services/classroom_google.py`).
- **AI provider:** Google Gemini at `generativelanguage.googleapis.com`; configured primary
  `gemini-3.6-flash`, review `gemini-3.1-pro-preview` (`backend/app/core/config.py`).
- **Storage:** uploaded files on the operator host (`data/documents`); PostgreSQL on Supabase
  (eu-west-2 for this pilot). No Supabase Storage, R2, D1 or queue in the data path.
- **Tenancy:** resolved from the verified JWT claim in `backend/app/api/deps.py`, never from a body.
- **Uploads:** PDF/PNG/JPEG, 25 MiB, 80 pages, MIME/size checks, checksums, path-traversal guard;
  no malware scanning, no application-level rate limiting.
- **Deletion:** no self-service deletion, export or retention job; audit and usage records are
  append-only by design.
- **Hosting:** Cloudflare Pages project `aetrix`, Git-connected; a push to `main` builds and deploys
  from the repository, so an uncommitted working tree can never reach production.

### 1.3 Documents that were missing

Cookie Policy, Acceptable Use Policy, AI Use Disclosure, Intellectual Property and Copyright Policy,
Security and Vulnerability Disclosure Policy, and an account deletion / data request process page.
There was also no index from which a reader (or an OAuth reviewer) could see the full set.

---

## 2. Documents created

| Route | Document | Purpose |
|---|---|---|
| `/legal` | Legal centre | Index of every document with version, date, scope and the open items the documents cannot settle. |
| `/cookies` | Cookie Policy | States that no cookies are set, tables every storage key with purpose and lifetime, explains the consent position and how to clear data. |
| `/acceptable-use` | Acceptable Use Policy | Prohibited conduct (unauthorised access, auth abuse, access-control bypass, automated abuse, malicious uploads, IP infringement, content misuse, AI manipulation, harassment), enforcement and reporting. |
| `/ai-disclosure` | AI Use Disclosure | Where AI is used, what is sent, failure modes, human review/approval, automated-decision position, accuracy claims not made, provider terms, reporting a wrong mark. |
| `/copyright` | Intellectual Property and Copyright Policy | Platform ownership, user ownership, operational licence, examination-board material, takedown notice contents, counter-notice, repeat infringement, misuse. |
| `/security` | Security and Vulnerability Disclosure Policy | Controls implemented, limitations disclosed, vulnerability reporting, research rules, response expectations, incident/breach position. |
| `/account-deletion` | Account Deletion and Data Requests | Manual request process, what can be deleted, what remains (audit, backups, provider logs, AI provider content), timing, school-controlled data, correction, export, clearing the device. |

## 3. Documents updated

| Document | Change |
|---|---|
| `/terms` | Added the incorporated-policy set, account security, a "no fees / no payment" section, an explicit indemnity position (none imposed on individuals; institutional agreement to settle it), and cross-links throughout. Now 23 numbered sections. |
| `/privacy` | Added a legal-basis table (contract / legitimate interests / legal obligation / consent-not-used), a cookie-and-storage section linking the Cookie Policy, an automated-decisions section, and links to deletion, security and AI documents. Now 20 numbered sections. |
| `components/legal/LegalPage.tsx` | Reads version and date from the registry; sidebar lists every legal document plus the legal centre. |
| `components/site/SiteFooter.tsx` | Legal column now exposes Terms, Privacy, Cookies, AI Use, Acceptable Use and the legal centre. |
| `routes/_marketing.sign-in.tsx` | Sign-in actions are gated on an explicit acknowledgement. |
| `routes/_app.settings.tsx` | Adds a "Privacy and legal" card linking every document and stating that no self-service deletion or export exists. |
| `vite.config.ts`, `scripts/legal-clean-urls.mjs` | All nine legal routes are prerendered and emitted with slashless copies. |

## 4. Registration and consent

There is no registration form to attach consent to: accounts are created by an administrator or an
invitation. Acceptance is therefore attached to the authenticated account, and the workspace is
gated on it:

- signing in completes normally; the application then reads this account's acceptance records from
  `public.legal_acceptances` with the user's own Supabase token;
- if a required document has no record at its current version, a blocking screen asks the person to
  accept **each missing document** (Terms of Service and Privacy Policy today), with unchecked
  boxes and a link to the document at that version, and states that AI marking is provisional;
- accepting writes one row per document — `user_id`, `document_type`, `document_version` — and the
  timestamp is generated by the database, not the browser; the gate then re-reads the rows and opens
  the workspace only when every required version is present;
- a failed write, an unreadable table or an unreachable database keeps the workspace closed, shows
  the reason and offers an explicit retry; a local flag is never treated as acceptance;
- signing out, signing in again, refreshing, clearing browser storage or using another device re-runs
  the same read, so an accepted version is not asked for twice;
- each document carries its own version (`terms_of_service` 1.0, `privacy_policy` 1.0, kept in
  `frontend/src/lib/legal.ts`); publishing a document at a new version asks for that document only;
- there is no preselected optional consent, and no marketing consent, because no marketing email is
  sent.

**Versioned acceptance is recorded server-side.** `supabase/migrations/20261113120000_legal_acceptances.sql`
creates the table with a unique `(user_id, document_type, document_version)` constraint, a trigger that
stamps `accepted_at`, a trigger that refuses UPDATE, and RLS policies that restrict reads and inserts to
`user_id = auth.uid()` with column-level insert grants (the client cannot supply a timestamp). The rules
are exercised against the live database by `supabase/tests/legal_acceptances_rls.py`.

## 5. Cookie consent position

No cookie banner was added, and that is a deliberate, evidenced decision rather than an omission:

- the application writes **no cookies** at all;
- every local/session-storage key is first-party and serves the requested service (session,
  sign-in round trip, display preference);
- there is no analytics, advertising or cross-site tracking;
- a banner asking consent for strictly necessary storage would misstate the position, and a banner
  with no optional category would be a non-functional control.

The Cookie Policy states this, lists every key, and commits to collecting separate, explicit consent
if non-essential storage is ever introduced. If the operator adds analytics, a consent mechanism and
a policy update are required before it is written.

## 6. Regulations evaluated

Applicability depends on facts the repository does not establish (operator entity and establishment,
user and data-subject locations, school contracts). Each row therefore states a conditional position
and the obligations that would follow — not a finding of compliance.

| Regime | Applies? | Obligations if it applies | Affected features / gaps |
|---|---|---|---|
| **EU GDPR** | Possibly — if the operator targets or monitors people in the EU, or a school in the EU uses it. Not established. | Art 5 principles; Art 6/9 lawful basis; Art 12–14 notice; Art 15–22 rights; Art 28 processor terms; Art 30 records; Art 32 security; Art 33/34 breach notification; Art 35 DPIA (likely for large-scale marking of children's work); Art 44+ transfer mechanism; Art 27 EU representative. | Legal-basis table added. **Gaps:** Art 28 DPA absent, Art 30 record not maintained, Art 27 representative undecided, DPIA not done, transfer mechanism absent, breach procedure unwritten. |
| **UK GDPR + Data Protection Act 2018** | Possibly — same conditional test for the UK. | Same core obligations; UK IDTA/Addendum for transfers; ICO registration/fee where applicable; Children's Code (age-appropriate design) if child users were direct users. | Same gaps. Students are not direct users, which weakens but does not remove the Children's Code question. |
| **ePrivacy Directive / UK PECR** | Applies to storage on a user's device wherever the user is in the EU/UK. | Prior consent for non-essential storage; information about storage; consent must be freely given, specific, informed, unambiguous, and as easy to refuse. | No cookies and no non-essential storage, so the strictly-necessary exemption covers the current build. Documented in the Cookie Policy. Revisit before adding analytics. |
| **Egypt PDPL No. 151 of 2020** | Possibly — if the operator is established in Egypt or processes data of people in Egypt. The operator's jurisdiction is unresolved. | Lawful purpose/consent; transparency; data-subject rights; security obligations; restrictions on transferring personal data outside Egypt without a licence/permit or an enumerated exception; notification to the regulator; penalties for unlawful processing. | Not directly addressed by the pages (they avoid asserting a jurisdiction). **Gap:** operator must establish whether PDPL applies, whether a licence or transfer permit is required, and whether children's data triggers extra conditions. Needs local counsel. |
| **COPPA (US)** | Unlikely as a direct obligation — Aetrix is not directed to children, has no child accounts and no child-directed content. | Verifiable parental consent, notice, deletion rights, data-minimisation, no conditioning access on unnecessary data. | If an operator or school were treated as directing the service to under-13s, obligations would attach. **Gap:** no age-assurance position; recorded as an open decision. |
| **FERPA (US)** | Only for US schools receiving federal funds; Aetrix would act as a "school official" under a written agreement. | Written agreement, direct control, limited use, re-disclosure limits. | No school-official agreement exists. **Gap.** |
| **US state privacy laws (CCPA/CPRA et al.)** | Unlikely at current scale; thresholds (revenue, volume, sale of data) are not met by a pilot, and the laws exempt some education records. | Notice at collection, rights to know/delete/correct/opt out, service-provider contracts, sensitive-data limits. | The Privacy Policy already provides a rights and deletion route. **Gap:** no formal service-provider addendum. |
| **EU AI Act** | Possibly — Annex III treats AI used to evaluate learning outcomes as high-risk when placed on the EU market or used in the EU. Marking assistance can fall inside that description. | Risk-management system, data governance, technical documentation, logging, transparency and instructions for use, human oversight, accuracy/robustness, conformity assessment and registration before placing on the market. GPAI transparency duties sit with the model provider. | Human review and approval are implemented and disclosed, and output is explicitly provisional. **Gap:** no AI Act classification, conformity assessment or technical file. Needs counsel; timeline and territorial scope are unresolved. |
| **Google API Services User Data Policy (Classroom)** | Yes, contractually, when the Classroom scope is used. | Limited Use: accurate privacy disclosure, no sale, no advertising use, no human review except enumerated cases, no training of non-compliant models; OAuth verification. | Privacy Policy describes Classroom scope and data. **Gap:** the operator entity and monitored contact must be real before OAuth verification. |

**Not evaluated as applicable, and not claimed:** ISO 27001, SOC 2, FERPA certification, "GDPR
compliant" status. None is established by publishing these pages.

## 7. Compliance gaps

| # | Gap | Consequence | Owner action |
|---|---|---|---|
| 1 | Operator legal entity, registered address and monitored contact are placeholders | Cannot form a contract, answer a request, or pass OAuth verification | Decide and publish |
| 2 | Governing law, forum, liability cap unresolved | Terms are not fully enforceable | Counsel |
| 3 | Controller/processor role per deployment undecided | Determines who answers data-subject requests | Counsel + school contract |
| 4 | No school/institution DPA, security schedule or subprocessor list | Schools cannot lawfully onboard at scale | Counsel |
| 5 | No international-transfer assessment or mechanism | EU/UK/Egypt transfers may be unlawful | Counsel |
| 6 | No retention schedule, deletion deadline or export | Policy cannot promise either; requests are manual | Owner + engineering |
| 7 | No server-side record of accepted document version | Acceptance is enforced but not evidenced | Engine endpoint (out of scope here) |
| 8 | No DPIA for children's scripts at scale | Required before high-risk processing | Owner + counsel |
| 9 | No malware scanning, rate limiting, RLS defence-in-depth, penetration test | Disclosed as limitations; affects school procurement | Engineering |
| 10 | No written incident-response / breach-notification procedure | Statutory deadlines may be missed | Owner |
| 11 | No EU/UK representative or DPO decision | Possible Art 27 breach if in scope | Counsel |
| 12 | Minimum-age and age-assurance position undecided | Unclear child-safeguarding stance | Owner + counsel |
| 13 | Google/Gemini terms, retention and training behaviour unrecorded | Privacy Policy cannot promise non-retention | Owner |
| 14 | AI Act classification not assessed | Possible high-risk obligations | Counsel |
| 15 | No accessibility statement or formal WCAG audit | Procurement and public-sector duties | Engineering |

## 8. Website functionality implemented

- Nine public legal routes, all prerendered, all readable without a session, each with a single `h1`,
  a version, a last-updated date and a draft-status notice.
- A legal centre that indexes every document with a one-line summary and version.
- Consistent footer links on every marketing page, plus a sidebar of all documents on every policy.
- Cross-links between related policies in the prose, not only in navigation.
- Unique page metadata (title, description, Open Graph title/type) per route.
- Sign-in acknowledgement that blocks both sign-in paths until accepted, with focus management and
  an `role="alert"` message.
- A "Privacy and legal" card in account settings that links every document and states plainly that
  no self-service deletion or export exists.
- A Cookie Policy that reflects the actual zero-cookie build, with no decorative preference toggles.
- Slashless clean-URL artifacts for all nine routes so `/cookies` serves 200 rather than redirecting.

## 9. Files changed

Frontend:
`src/lib/legal.ts`, `src/components/legal/LegalPage.tsx`,
`src/components/legal/LegalAcknowledgement.tsx`, `src/components/site/SiteFooter.tsx`,
`src/routes/_marketing.legal.tsx`, `_marketing.terms.tsx`, `_marketing.privacy.tsx`,
`_marketing.cookies.tsx`, `_marketing.acceptable-use.tsx`, `_marketing.ai-disclosure.tsx`,
`_marketing.copyright.tsx`, `_marketing.security.tsx`, `_marketing.account-deletion.tsx`,
`_marketing.sign-in.tsx`, `_app.settings.tsx`, `src/styles/legal.css`, `src/routeTree.gen.ts`,
`vite.config.ts`, `scripts/legal-clean-urls.mjs`, `tests/legal.spec.ts`, `tests/auth.spec.ts`.

Documentation:
`docs/legal/LEGAL_COMPLIANCE_REPORT.md` (this file), `LEGAL_REVIEW_NOTES.md` (amendment).

## 10. Files explicitly excluded

Every path in `backend/` (engine, prompts, migrations, tests), `benchmark/`, `experiment/`, `tools/`,
`scripts/aetrix-stack.ps1`, `.tmp*` artifacts, and the uncommitted frontend work in
`AccountSwitcher.tsx`, `lib/api/types.ts`, `useSystemStatus.ts`, `AuthProvider.tsx`,
`lib/auth/accounts.ts`, `lib/services.ts` and `_app.assignments_.$assignmentId.tsx`.

## 11. Verification log

| Check | Result |
|---|---|
| `tsc --noEmit` (worktree at the committed tree) | Passed |
| `vite build` incl. prerender and clean-URL artifacts | Passed; nine legal URLs emitted |
| `tests/legal.spec.ts` | 16 passed (routes, cross-links, footer, consent gate, 390px overflow, axe) |
| `tests/auth.spec.ts` + `tests/marketing.spec.ts` | 52 passed, 1 failed — the failure is a stale assertion at `auth.spec.ts:87` on unmodified HEAD (the `#access` text concatenates `<dt>`/`<dd>` without whitespace); the uncommitted working tree already contains the fix, which was not included here |
| `tests/responsive.spec.ts` + `tests/roles.spec.ts` | 116 passed |

**Deployment**

| Item | Value |
|---|---|
| Branch | `feat/legal-compliance` |
| Commit | `d0177f2` — `feat(legal): add website legal documentation and compliance pages` |
| Production branch | `main`, fast-forwarded from `72c6801` to `d0177f2` (no merge commit, no unrelated commit) |
| Cloudflare Pages project | `aetrix` |
| Production deployment | `3516f3d8-b26b-47f6-99d0-e43cc7ba7368`, source `d0177f2`, status Active |
| Canonical host | `https://aetrix.pages.dev` |
| Immutable host | `https://3516f3d8.aetrix.pages.dev` |

Every legal route returned HTTP 200 on the canonical host with its own `<title>`:
`/legal`, `/terms`, `/privacy`, `/cookies`, `/acceptable-use`, `/ai-disclosure`, `/copyright`,
`/security`, `/account-deletion`. The immutable deployment host also returned 200 for `/legal`. The
footer on `/` links `/cookies` and `/legal`, and `/sign-in` serves the acknowledgement markup.

**Live browser check.** On `https://aetrix.pages.dev/sign-in`, clicking “Continue with Google” with the
box unchecked produced the inline alert, moved focus to the checkbox and did not start an OAuth
request. The console showed one pre-existing `400` from a Supabase `refresh_token` call (that browser
held no valid session) and a font-preload warning; neither is caused by this change.

**Not performed on production:** a real Google sign-in round trip (no test account available), the
authenticated settings page, and a mobile visual review. Those paths are covered by the local suites
and by unchanged code, not by a production observation.

## 12. Honest limits of this work

- These are drafted policies, not legal advice, and publishing them is not compliance with GDPR,
  UK GDPR, PDPL, COPPA, FERPA, the AI Act or any other regime.
- No certification, audit, DPIA or transfer assessment was performed.
- The drafts deliberately contain visible placeholders rather than invented operator facts,
  retention periods or jurisdictions.
- Acceptance is recorded by the service as an account id, document type, document version and a
  database-generated timestamp. That record is evidence of the acceptance event; it is not an
  independent audit trail, an e-signature, or proof of who was at the keyboard, and the pilot does not
  capture IP address or device evidence.
- The pages describe the code as it is at this commit, including the limitations that a school would
  want to know about.
