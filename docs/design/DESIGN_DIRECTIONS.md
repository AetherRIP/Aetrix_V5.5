# Design Directions

**Status:** RECOMMENDED. Six genuinely different directions, then one recommendation. None copies Linear,
Stripe, Notion, Raycast or Vercel; those products are cited only as evidence that a direction is
commercially viable.

Method: each direction is a *system* (identity, type, colour, layout, navigation, components, motion), not a
mood board. The test is whether it survives a 40-screen product and a 3-hour marking session. Direction 1
continues the existing `ui-identity-v6.md` "Instrument" work rather than competing with it.

---

## D1 — Instrument / Ledger *(recommended)*

**Identity.** A measuring instrument for examiners. The interface behaves like a lab readout bound into a
ledger: precise figures, ruled tables, hairline structure, one signal colour that means *measurement*.
Nothing decorative survives unless it encodes information.

- **Type.** Space Grotesk — display, navigation, buttons, figures (tabular). Plus Jakarta Sans — body copy
  read for long stretches. Cascadia Mono — ids, question codes, timestamps.
- **Colour.** Ink graphite base (`#12161A` text, never pure black), cool paper `#F7F8F7`, surfaces
  `#FFFFFF`. One signal accent: cyan-teal `#0E7C86` (light) / `#22C7D4` (dark). Status is a separate
  reserved vocabulary: vermilion `#B3261E` error, amber `#9A6700` review, green `#1E7A4B` confirmed.
- **Layout.** 12-column grid, 8 px rhythm, 1 px hairlines instead of shadows, dense 34 px table rows. Page
  header carries an eyebrow rule and a 3 px marker bar.
- **Navigation.** Left rail 232 px, grouped by task, active item marked with a 3 px bar, workspace switcher
  at top, command palette as the expert path.
- **Components.** Ledger `DataGrid`; stamp-like state chips (5 px radius); instrument stat readouts with
  tabular figures and a measurement rule at the edge; hairline cards.
- **Motion.** 120–180 ms, state-change only (row enters, mark saves, job advances). No entrance animation on
  data.
- **Accessibility.** Strong: hairlines and weight carry hierarchy rather than colour alone; tabular figures
  aid low-vision scanning; every status has a word.
- **Strengths.** Distinctive in a category full of card dashboards; excellent for long sessions, projectors
  and printed reports; tokens map cleanly to a design system; already validated once in V6.
- **Weaknesses.** Unforgiving — one ill-chosen accent or an extra shadow breaks the spell; less friendly for
  first-time onboarding; demands real typographic discipline.

## D2 — Drafting Table

**Identity.** A technical drawing surface. Marking is annotation, so the metaphor fits: faint grid, ink-blue
construction lines, callout labels with leader lines, margins you can write in.

- **Type.** IBM Plex Sans + IBM Plex Mono throughout; labels uppercase micro, tracked 6%.
- **Colour.** Blueprint paper `#F4F6F8` with a 24 px grid at 4% opacity, ink blue `#1B4B8F`, graphite
  `#22272B`, red pencil `#A33A2B` for corrections.
- **Layout.** Wide margins, content in a single measured column, diagrams over cards.
- **Navigation.** Top bar plus a left index, like a drawing set; labels only, no icons.
- **Components.** Annotation callout, revision cloud, legend block, ruled form fields.
- **Motion.** Almost none; 90 ms fade on layer changes.
- **Strengths.** Perfect conceptual match for script annotation; print/report symmetry; highly legible.
- **Weaknesses.** Grids and uppercase labels fatigue over hours; weak at dense tables (grades, workload);
  hard to make onboarding feel approachable.

## D3 — Quiet Studio

**Identity.** An editorial workspace. Near-monochrome, generous space, one serif display face, chrome that
recedes so the script is the only object on screen.

- **Type.** Instrument Serif or Fraunces (display), Inter/Geist (body), no mono.
- **Colour.** Warm paper `#FAF8F4`, charcoal `#1A1A18`, one muted accent per workspace (default `#3F5D53`).
  **Risk:** warm cream plus serif is the most common AI-generated default; using it needs a deliberate
  reason and at least one structural deviation.
- **Layout.** Asymmetric two-column, wide gutters (48 px), prose max 720 px.
- **Navigation.** Sidebar collapses to icons by default; breadcrumb-first.
- **Motion.** Slow, 240–320 ms ease-out; cross-fades.
- **Strengths.** Calm and premium; excellent for reading AI explanations and reports.
- **Weaknesses.** Poor density for 200-row queues; the aesthetic is currently over-used; contrast risk from
  pale secondary text.

## D4 — Signal Room

**Identity.** A dark operations console. Treats marking as a monitored pipeline: throughput, failures, queue
depth, live job activity.

- **Type.** Geist Mono for data, Inter for UI, 12 px base.
- **Colour.** `#0B0E10` base, `#151A1E` panel, phosphor `#4ADE80`, amber `#F59E0B`, alert `#EF4444`, text
  `#E6EDF3`.
- **Layout.** Dense grid, 28 px rows, status strip across the top, panels with 1 px borders.
- **Navigation.** Icon rail 56 px plus a collapsible panel.
- **Components.** Sparkline, job strip, log tail, status pill.
- **Motion.** Instant; only status transitions animate (80 ms).
- **Strengths.** Superb for supervisors and long-running jobs; makes failure states legible; low eye strain
  in dim rooms.
- **Weaknesses.** Bad for reading handwriting under glare; alarming for non-technical teachers; dark-first
  doubles the contrast-tuning cost; printing and reports need a light theme anyway.

## D5 — Markbook

**Identity.** Deliberately descended from the spreadsheet teachers already trust. Cells, not cards.

- **Type.** Inter with tabular figures; 13 px base; no display face.
- **Colour.** White `#FFFFFF`, gridline `#D7DBDE`, header `#F1F3F4`, selection blue `#1A73E8` (worksheet
  convention), one status accent.
- **Layout.** Full-bleed grid, frozen headers, 26 px rows, keyboard-first cell editing.
- **Navigation.** Tabs per assignment; minimal chrome; no rail.
- **Components.** Cell, range selection, formula-bar-like detail strip, column filter.
- **Motion.** None. Instant selection.
- **Strengths.** Zero learning curve for the core table; fastest bulk entry; familiar to admin staff.
- **Weaknesses.** Unusable for the review canvas (PDF plus per-question marks); weak identity; poor at
  narrative surfaces (reports, onboarding, settings).

## D6 — Atrium

**Identity.** Friendly modern SaaS. Soft cards, rounded geometry, gentle colour, optimistic illustrations.

- **Type.** Plus Jakarta Sans everywhere; 15 px base.
- **Colour.** `#FFFFFF` surfaces on `#F5F7FB`, indigo `#4F46E5`, slate text `#0F172A`, radii 12–16 px.
- **Layout.** Card grid, 24 px gaps, generous padding, hero panels.
- **Navigation.** Sidebar plus top bar, icon+label, breadcrumbs.
- **Components.** Card, pill, avatar stack, empty-state illustration, progress ring.
- **Motion.** 200 ms, hover lift, entrance fades.
- **Strengths.** Approachable; fast to build; familiar to school buyers.
- **Weaknesses.** **This is what V5 already looks like**, and the V6 audit named it: "reads as a well-made
  dashboard template rather than a tool for examiners." Highest risk of looking generic.

---

## Recommendation

**Adopt D1 (Instrument / Ledger), with two specific grafts.**

1. **From D2, the annotation callout and revision mark** — the review canvas adopts leader-line callouts and
   a margin strip, because marking *is* annotation.
2. **From D5, cell-level density and keyboard editing** in the grade matrix and submission queue, where
   spreadsheet familiarity is a feature rather than a compromise.

| Criterion | D1 | D6 | D4 | D5 | D2 | D3 |
|---|---|---|---|---|---|---|
| Distinctive vs category default | ●●● | ● | ●●● | ●● | ●●● | ●● |
| Long-session readability | ●●● | ●● | ●● | ●●● | ●● | ●● |
| Dense data (queues, grades) | ●●● | ● | ●●● | ●●● | ● | ● |
| Marks-integrity legibility (states, exceptions) | ●●● | ● | ●●● | ●● | ●● | ●● |
| Projector/print legibility | ●●● | ●● | ● | ●● | ●●● | ●● |
| Onboarding friendliness | ●● | ●●● | ● | ●● | ●● | ●●● |
| Continuity with existing V6 direction | ●●● | ● | – | – | ● | ● |

D1 is the only direction scoring ●●● on both distinctiveness and dense-data legibility, and the only one
continuing work already started (V6 tokens, `ui-identity-v6.md`). It also degrades gracefully: the same
tokens produce a printable report and a projector-legible dashboard.

**Refused regardless of direction:** gradient-mesh heroes, purple-to-blue accents, cards nested in cards, a
rounded-square icon tile above every heading, pill-shaped status everywhere, all-caps eyebrows on every
section, and drop shadows used to separate surfaces a hairline separates better.

**Reversal trigger:** if usability testing with 5+ assistants shows density is too high on 1366×768 laptops,
raise row height and body size before changing direction — density is tunable, identity is not.
