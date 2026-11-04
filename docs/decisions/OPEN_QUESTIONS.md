# Open Questions

**Status:** these need the product owner. Each lists why it matters, the options, and the default we will
assume if it stays unanswered. Defaults are **not** decisions; they are what the build will do in the absence
of one, and they are the cheapest thing to reverse early and the most expensive late.

**Labels.** Every row here is **UNKNOWN** — that is the reason it is listed. Where another document in this
package takes a position while its question is still open, that position is tagged **ASSUMPTION**, and the
"Default if unanswered" column is where you can find it. No row in this file is **VERIFIED**: a question that
had an authoritative answer would not be a question.

| # | Question | Why it matters | Options | Default if unanswered |
|---|---|---|---|---|
| **Q1** | Which jurisdiction(s) and lawful basis govern student data? | Determines DPA, retention limits, transfer mechanism, DPIA need | UK/EU (GDPR), other, mixed | Assume UK/EU-shaped requirements; ship no compliance claim |
| **Q2** | Is the school the controller or are we? | Decides who answers subject requests and who signs the DPA | School = controller (processor model) vs we are controller | School = controller |
| **Q3** | Do we host AI credentials, or must each workspace bring its own? | Cost, liability, privacy, onboarding friction | Platform keys (we pay) · workspace keys (they pay) · both | **Both**: platform keys for trial, workspace keys for production |
| **Q4** | What is the AI cost per script, measured? | The entire pricing model and margin | – | Measure in phase 1; no pricing decision before then |
| **Q5** | Do we migrate existing V5 data into V5.5? | An importer is real work; V5 users may expect continuity | No migration · one-off CSV/SQLite importer · per-workspace import tool | **No automatic migration**; document a manual path |
| **Q6** | Is the WPF desktop client part of V5.5? | It shells out to a local backend that will not exist | Retire · thin shell over the hosted API · keep local mode | **Retire** for MVP; revisit only if offline marking is required |
| **Q7** | Do customers need their own domain (white-label)? | Multi-tenant custom domains add routing, cert, and tenant-resolution complexity | No (our subdomain) · optional per workspace | No for MVP |
| **Q8** | What is the commercial model? | Shapes quotas, metering, seat limits, invoicing | Per seat · per script · per workspace tier · free for now | **Free during pilot**, metering built so billing is additive |
| **Q9** | Is Google Classroom mandatory, optional, or one of several LMS integrations? | Phase ordering and OAuth verification lead time | Optional (recommended) · mandatory · multi-LMS later | **Optional**; manual upload is a first-class path |
| **Q10** | Which subjects/boards beyond Edexcel IGCSE 4MA1? | The mark-scheme model assumes a structured scheme with M/A/B points | Single qualification · several maths boards · general | Single qualification; do not generalise the model yet |
| **Q11** | Who is on call, and what is the response promise? | Support promises appear in contracts | Founder-only · small rota · business hours only | Business-hours support during pilot; 24 h response |
| **Q12** | Is offline marking required (schools with poor connectivity)? | Would force a local-first client and conflict sync | No · read-only offline · full offline | **No**; the review canvas is online-only |
| **Q13** | What is the retention expectation from schools? | Drives defaults and storage cost | 1 term · 1 year · configurable | 180 days after publication, configurable |
| **Q14** | Do reviewers need a second-model cross-check ("double marking")? | V5 has `double_check.py`; it doubles cost | Off · on demand per assignment · always for sampled scripts | Off by default; available per assignment |
| **Q15** | Is there an existing brand identity to honour? | The design direction assumes we define one | None · existing school-facing brand · partially | Adopt the "Instrument/Ledger" direction as the product brand |
| **Q16** | Who owns the marking prompt and its IP? | It is the core asset, possibly authored under contract | Ours · shared · licensed | Treat as proprietary; confirm authorship before launch |

## How to answer efficiently

Answer **Q1, Q2, Q3, Q8** first — they change contracts, cost and onboarding. **Q4** is measured, not answered.
**Q5, Q6, Q12** can be deferred past the MVP but should not be assumed silently.

## Questions we deliberately did not ask

Feature wishlists (more dashboards, more charts, mobile apps) are downstream of the above. Adding them before
Q1–Q4 are settled is how a product acquires surface it cannot afford to run.
