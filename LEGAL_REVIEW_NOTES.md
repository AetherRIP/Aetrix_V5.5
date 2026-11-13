# Aetrix legal pages — review notes

> **Amended 13 November 2026.** The legal surface was expanded from `/privacy` and `/terms` to eight
documents plus a `/legal` centre: Cookie Policy, Acceptable Use, AI Use Disclosure, Copyright and IP,
Security and Vulnerability Disclosure, and Account Deletion and Data Requests. Sign-in is now gated on
an explicit, unchecked acknowledgement. The 9 November sections below remain the record of the first
two pages; the current audit, regulatory assessment, gaps and verification are in
`docs/legal/LEGAL_COMPLIANCE_REPORT.md`. The placeholders and open decisions in sections 3–6 are
still unresolved.

Status: **pre-release draft, published for review on 9 November 2026.**
Pages: `/privacy` and `/terms` on `https://aetrix.pages.dev`.
These notes record what the source code actually supports, what remains unverified, and what must be decided before the pages are treated as final. They are not legal advice.

---

## 1. Why these pages are drafts

The repository does not establish an operator legal identity, registered address, contact email, data-protection contact, governing law, jurisdiction, liability cap, minimum age, retention periods, or international-transfer mechanism. Inventing any of those would create commitments the operator cannot stand behind.

The published pages therefore:

- use visible placeholders for those facts;
- avoid claiming GDPR, UK GDPR, COPPA, FERPA, ISO 27001, SOC 2, or any other compliance or certification;
- avoid promising a deletion deadline, provider non-retention, “never shared”, or “encrypted at rest” as an Aetrix guarantee;
- describe the pilot’s actual limitations, including local file storage, no malware scanning, no rate limiting, and no self-service export or deletion;
- carry a visible “pre-release pilot · pending legal review” notice.

**Do not remove the draft notice or placeholders until the items in sections 3 and 4 are resolved and counsel has reviewed the pages.**

---

## 2. Verified platform facts used in the pages

| Area | Verified fact | Source |
|---|---|---|
| Frontend hosting | Static TanStack Start build on Cloudflare Pages, project `aetrix`; public pages are prerendered and do not require a session | `frontend/vite.config.ts`, `frontend/wrangler.jsonc`, `.github/workflows/deploy-frontend.yml` |
| Authentication | Supabase Auth with Google OAuth (PKCE) and optional email/password; session persisted in browser local storage under `aetrix:auth`; browser uses only the Supabase publishable key | `frontend/src/lib/auth/AuthProvider.tsx`, `frontend/src/lib/supabase.ts`, `frontend/src/lib/env.ts` |
| Google data | Account subject identifier, email, name, and profile-image URL; the engine stores subject, email, and display name; no avatar field exists in the application models | `frontend/src/lib/auth/AuthProvider.tsx`, `backend/app/db/models.py` |
| Tenant identity | Tenant is resolved from the verified JWT claim in the API dependency layer, not from a request body | `backend/app/api/deps.py` |
| Database | PostgreSQL on Supabase; current pooler host is in AWS `eu-west-2`; direct SQLAlchemy access, no SQLite path | `backend/app/core/config.py`, `backend/.env` (host only inspected) |
| Uploads | PDF, PNG, JPEG; 25 MiB maximum; maximum 80 pages; MIME/size checks, checksums, page rendering, path-traversal guard | `backend/app/core/config.py`, `backend/app/storage/local.py` |
| File storage | Local filesystem only (`storage.backend = local`, root `data/documents`); `build_storage` rejects every non-local backend; no Supabase Storage or R2 adapter | `backend/app/storage/local.py`, runtime settings |
| AI provider | Google Gemini API at `generativelanguage.googleapis.com`; primary `gemini-3.6-flash`, review `gemini-3.1-pro-preview`; live provider currently enabled | `backend/app/core/config.py`, runtime settings |
| AI inputs/outputs | Page images plus prompt, mark scheme, and blueprint content are sent to Gemini; question results, confidence, evidence, verification, reviews, and approvals are stored | `backend/app/services/results.py`, marking/provider modules |
| Human approval | A job cannot be approved while any question is flagged `review_required`; approval records approver, time, marks, total, and record version; gradebook records approval state | `backend/app/services/results.py`, `backend/app/services/workspace.py` |
| Provider credentials | Stored encrypted with Fernet and never returned to the browser | `backend/app/core/config.py`, `backend/app/db/models.py`, admin provider routes |
| Logging | Structured JSON with request/tenant/job identifiers; redacts bearer tokens, `AIza` keys, JWTs, long hex, and sensitive field names; does not log bodies or prompts | `backend/app/core/logging.py` |
| Audit and usage | `audit_events`, `job_events`, and `provider_usage` are append-only by design; no retention job enforces expiry | `backend/app/db/models.py`, `docs/engine/architecture/SECURITY.md` |
| Frontend tracking | No third-party advertising or behavioural-analytics script was found; the application’s analytics page is a product view computed from marking records | `frontend/package.json`, frontend source search |
| Public API | Engine exposed through Tailscale Funnel at `https://arthur-rip-zn02.tail06bb75.ts.net` | `frontend/.env` (host only inspected) |

### Data categories actually stored

- Account and workspace: Supabase subject, email, display name, role, workspace name/slug, invitations.
- Educational records: exams, blueprints, mark schemes, classes, student references and optional display names, submissions, page images and text excerpts, question results, working summaries, confidence, evidence, review decisions, approvals, audit events.
- Operational: request/tenant/job IDs, timestamps, status and error codes, provider token counts and estimated cost.
- Provider credentials: encrypted ciphertext and fingerprint (not user data, but sensitive operator data).

### What is not implemented

- No self-service account deletion, workspace deletion, or data export.
- No automated retention or legal-hold job.
- No malware scanning on uploads.
- No application-level rate limiting.
- No database row-level security relied on for tenant isolation.
- No independent penetration test, certification, or formal disaster-recovery test.
- No tested backup restore or expiry process for local files.
- No consented, time-limited platform support-access feature.
- No DPO, EU/UK representative, or confirmed supervisory authority.
- No verified provider data-processing agreement or retention commitment for Gemini.
- No international-transfer assessment or standard contractual clauses recorded in the project.

---

## 3. Missing operator information and placeholders

Every item below appears in the pages as a visible placeholder.

| Placeholder | Needed from owner | Why it matters |
|---|---|---|
| `OPERATOR LEGAL ENTITY — TO BE CONFIRMED` | Exact legal name of the entity operating Aetrix (individual, company, or institution) | Identity of the party contracting, controller/processor analysis, enforceability |
| `REGISTERED ADDRESS — TO BE CONFIRMED` | Registered or principal business address | Legal notices, consumer law, service of process |
| `CONTACT EMAIL — TO BE CONFIRMED` | Monitored privacy and legal contact address | Data-subject requests, complaints, OAuth review, breach contact |
| Data-protection contact | Name/role and contact route, if one is required | Accountability and request handling |
| EU/UK representative | Whether one is required and, if so, who | GDPR/UK GDPR territorial scope, if applicable |
| `GOVERNING LAW — TO BE CONFIRMED` | Chosen governing law | Contract interpretation and enforceability |
| `JURISDICTION — TO BE CONFIRMED` | Chosen courts or dispute forum | Dispute resolution; must fit the operator’s legal circumstances |
| `LIABILITY CAP — TO BE CONFIRMED BY COUNSEL` | A defensible cap, or a decision to rely only on exclusions permitted by law | The current placeholder is not an enforceable term |
| Minimum age / eligibility | Whether a minimum age is required; current pages say no separate minimum age and no age verification | Child-safety and consumer-law obligations |
| Retention periods | Approved periods per category, including audit, usage, backups, and local files | The pages currently say no automated schedule is enforced |
| Deletion deadline | What the operator can actually meet, including backups and append-only records | The pages currently promise no fixed deadline |
| International-transfer mechanism | SCCs, UK IDTA/Addendum, adequacy, or another lawful route; transfer assessment | Cross-border processing by Supabase, Google, Cloudflare, Tailscale |
| Supervisory authority | Competent authority and complaint route | Rights section currently says it is undetermined |
| Subprocessor notice mechanism | How schools are told about provider changes | Transparency and contract compliance |

---

## 4. Unresolved legal decisions

1. **Controller/processor role.** The pages say the role “depends on the contract with the school and has not been finally determined.” Decide whether Aetrix is a processor, controller, or joint controller for each deployment, and paper it in a school/institution agreement.
2. **School contracts and DPAs.** A data-processing agreement, security schedule, subprocessor list, breach-notification clause, and audit/assistance terms are needed before real student scripts are processed at scale.
3. **Children’s data.** The pilot has educator accounts only, but student scripts are uploaded by teachers. Decide whether parental consent, school consent, or another lawful basis applies; whether a DPIA is required; and what age-assurance position is defensible. The pages do not claim COPPA, FERPA, or UK Children’s Code compliance.
4. **Google Gemini terms and retention.** Obtain and record the applicable Google Cloud/Gemini API terms, data-processing terms, retention behaviour, and whether paid-tier protections apply. The pages currently state that Aetrix has not independently verified these points.
5. **International transfers.** Complete a transfer assessment and put a lawful mechanism in place. The database is in `eu-west-2`, but Supabase, Google, Cloudflare, and Tailscale operate globally.
6. **Retention and legal hold.** Approve a schedule for account, workspace, script, page-image, result, audit, usage, invitation, and backup data. Decide how legal holds, exam-board retention rules, and school instructions interact.
7. **Deletion and export.** Decide what “deletion” means for live data, backups, append-only audit, and provider logs; what export format will be offered; and how student/guardian requests are routed through schools.
8. **Liability and consumer terms.** Settle the liability cap, exclusions, indemnities (none are currently included), and whether any consumer cancellation/refund terms are needed. The pilot is free, but that may change.
9. **Governing law and forum.** Choose after the operator entity is known. Do not leave the placeholder in a live final policy.
10. **IP ownership of outputs.** The pages say the operator owns the software, prompts, and documentation and that users retain uploaded content. Decide who owns generated marking records and whether school contracts need a broader licence.
11. **Cookies/local storage.** The frontend uses local storage for the Supabase session, not advertising cookies. Decide whether an ePrivacy/cookie notice or consent mechanism is required in the target jurisdictions; the current Privacy Policy describes the storage but there is no banner.
12. **Breach notification.** Implement an incident-response and breach-notification procedure, including who decides, who notifies schools/authorities, and within what period.
13. **Accessibility and language.** No accessibility statement or alternative-language policy exists. The pages target WCAG 2.2 AA patterns, but no formal audit has been done.
14. **Age and capacity.** The pages say users must have legal capacity and that minors may use Aetrix only through an institution or authorised adult. Confirm this is the intended model and whether a hard minimum age is required.
15. **OAuth consent-screen review.** Google may reject placeholder operator details or a page that reads as a non-final draft. Resolve the operator identity and contact before submitting for verification.

---

## 5. Technical changes needed to make the policy fully accurate and defensible

Priority: **P0** before real student data at scale; **P1** before public launch; **P2** as the pilot matures.

| Priority | Change | Current state / why |
|---|---|---|
| P0 | Replace local filesystem storage with encrypted object storage and tested backups | Files sit on the operator host at `data/documents`; disk-level controls are not managed by Aetrix |
| P0 | Obtain and document Gemini data-processing and retention terms | The pages cannot promise provider non-retention; this is currently unverified |
| P0 | Put a school/institution DPA and subprocessor schedule in place | No contract or DPA is present in the repository |
| P0 | Implement account/workspace deletion and data export | No API or UI exists; deletion is manual |
| P0 | Implement malware scanning and upload quarantine | Only type/size/page checks exist |
| P0 | Implement application-level rate limiting | No rate limiting exists |
| P0 | Complete an international-transfer assessment and mechanism | No SCCs/IDTA/adequacy record exists |
| P1 | Define and enforce retention and legal-hold rules | Audit and usage are append-only; no expiry job |
| P1 | Add row-level security or equivalent database defence in depth | Tenant isolation is application-enforced only |
| P1 | Add independent security testing and document results | No penetration test or certification |
| P1 | Implement incident response and breach notification | No formal procedure found |
| P1 | Add a consented, time-limited support-access flow | Platform operators can access data without a scoped grant |
| P1 | Document log retention at Cloudflare, Supabase, Tailscale, and Google | The application does not control vendor logs; IP/user-agent handling is provider-dependent |
| P1 | Add key rotation and documented key-management procedure | Provider credentials are Fernet-encrypted, but rotation is not implemented |
| P1 | Add a tested backup restore and deletion-propagation process | Supabase backups exist under vendor terms; local files have no tested restore |
| P2 | Add accessibility audit and statement | No formal WCAG audit |
| P2 | Add subprocessor-change notice and versioned policy archive | No notice mechanism or archive |
| P2 | Add a data-request workflow with identity/authority checks and response tracking | Requests are currently handled manually by email |

---

## 6. Claims deliberately not made

The pages do **not** say, and should not say until independently established:

- that Aetrix is GDPR, UK GDPR, COPPA, FERPA, ISO 27001, SOC 2, or otherwise compliant/certified;
- that data is encrypted at rest by Aetrix (the database relies on Supabase’s controls; local files rely on the host);
- that Google/Gemini never retains, reviews, or trains on uploaded content;
- that data is “never shared” (processors and legal disclosures exist);
- that deletion happens within a specific number of days;
- that uploads are malware-scanned or rate-limited;
- that the service has 99.9% uptime, a disaster-recovery guarantee, or a tested export;
- that AI marks are official, infallible, examiner-equivalent, or a substitute for human grading;
- that Aetrix is affiliated with or endorsed by Pearson Edexcel or Google;
- that student consent has been obtained by Aetrix (teachers/schools are responsible).

---

## 7. Page implementation and verification

- Routes: `frontend/src/routes/_marketing.privacy.tsx`, `frontend/src/routes/_marketing.terms.tsx`.
- Shared shell: `frontend/src/components/legal/LegalPage.tsx`.
- Styles: `frontend/src/styles/legal.css`, imported from `frontend/src/styles/app.css`.
- Footer links: `frontend/src/components/site/SiteFooter.tsx` (Legal column, every marketing page).
- Prerender list: `/privacy` and `/terms` added to `frontend/vite.config.ts`.
- Both routes sit under `_marketing`, so they use the public header/footer and have no session gate.
- Metadata: unique title, description, and Open Graph title/type per page.
- Accessibility: single `h1`, numbered `h2` sections, skip link inherited from the marketing layout, visible focus styles, semantic table captions, and a labelled table of contents.
- Responsive: single-column content and TOC below 980px; sticky TOC above 980px; tables scroll horizontally on narrow screens.
- Cross-links: each page links to the other, to the homepage, and back to the top.

Verification results are recorded in section 9 and the final delivery message.

---

## 8. Recommended next actions

1. Decide the operator entity, address, contact email, governing law, jurisdiction, liability cap, and minimum-age position.
2. Obtain counsel review of both pages and the school/institution agreement.
3. Obtain Google’s applicable data-processing/retention terms and record them.
4. Implement P0 technical controls before onboarding real student scripts beyond the pilot.
5. Replace the placeholders and remove the draft notice only after steps 1–4 are complete.

---

## 9. Deployment verification — 9 November 2026

**Build and local verification**

- `vite build` succeeded; both `/privacy` and `/terms` were prerendered and emitted as `privacy/index.html`, `terms/index.html`, `privacy.html`, and `terms.html`.
- `tsc --noEmit` passed.
- 111 Playwright public/responsive tests passed against the local preview, including no horizontal overflow at 360, 375, 390, 412, 768, 1024, 1440, and 1920px.
- Both pages were loaded without a session; no auth redirect occurred. Cross-links, footer links, TOC anchors, and tables were checked. The provider-table overflow at 390px was found and fixed before deployment.

**Cloudflare Pages deployment**

- Production deployment: `21b2c072-d42a-4ce1-8f07-f9e3f412aa78` (branch `main`, deploy success).
- Immutable deployment URLs, verified HTTP 200 with the correct titles and content:
  - `https://21b2c072.aetrix.pages.dev/privacy`
  - `https://21b2c072.aetrix.pages.dev/terms`
- Canonical URLs, **verified but not correct at the time of writing**:
  - `https://aetrix.pages.dev/privacy` returns HTTP 200 but serves the old homepage fallback.
  - `https://aetrix.pages.dev/terms` returns HTTP 200 but serves the old homepage fallback.

**Why the canonical URLs are not correct**

The Cloudflare Pages control plane names `21b2c072` as the latest and canonical production deployment, and its deployment log says “Success: Your site was deployed!”. The `aetrix.pages.dev` host nevertheless continues to serve deployment `cc4a9bfc` (old CSS hash `app-Bk2H1rye.css`) rather than the new build (`app-B2TwD8HF.css`).

This was reproduced with:

- two separate direct-upload deployments (`8b509d09`, `9ec4881e`) and a third with a unique working-tree commit hash (`21b2c072`);
- a successful rollback to prior deployment `8b509d09`;
- cache-busting query strings and `Cache-Control: no-cache`;
- an external fetch from a different network, which also saw the old content;
- checks confirming there is no Worker script, Worker custom domain, or route intercepting the host.

Cloudflare’s rollback API refused to promote `9ec4881e` because it already considered it production, then returned HTTP 500 when promoting `8b509d09`; the retry succeeded but did not change what `aetrix.pages.dev` served. Public Cloudflare community reports describe the same Pages behaviour (deployment succeeds, production/pages.dev continues serving an older deployment, including after purge and on fresh projects).

**Consequence:** the canonical URLs must not be used for Google OAuth verification until Cloudflare’s production alias is refreshed. The immutable deployment URLs are live and correct for review. Escalate to Cloudflare support with deployment IDs `21b2c072`, `9ec4881e`, `8b509d09`, and the stale deployment `cc4a9bfc`; alternatively trigger a Git-based production deployment after committing the changes. Re-check both canonical URLs after the alias updates.
