# Design System

**Status:** RECOMMENDED — specification only, no components implemented. Built on direction **D1**
(Instrument / Ledger) from [`DESIGN_DIRECTIONS.md`](DESIGN_DIRECTIONS.md), continuing the V6 token work.

## 1. Three-layer token architecture

```
Primitive   raw values, no meaning        ink.900 #12161A · cyan.600 #0E7C86 · space.4 16px
   ↓
Semantic    purpose in the product        text.primary · surface.raised · accent.measurement · status.review
   ↓
Component   one component's decisions     table.row.height · button.primary.bg · chip.radius
```

Rules: components may consume **semantic** and **component** tokens only, never primitives. A component
that needs a new value must add a semantic token with a reason, so the system cannot drift.

## 2. Primitive palette

| Token | Hex | Use |
|---|---|---|
| `ink.950` | `#0C0F12` | Darkest, dark-theme base |
| `ink.900` | `#12161A` | Primary text (light theme) |
| `ink.700` | `#2A3239` | Secondary text |
| `ink.500` | `#5A656D` | Tertiary text, meta |
| `ink.300` | `#98A2A9` | Disabled text |
| `paper.50` | `#FBFCFB` | Highest surface |
| `paper.100` | `#F7F8F7` | App background (cool paper) |
| `paper.200` | `#F0F2F1` | Sunken / table header |
| `line.200` | `#DDE2E3` | Hairline |
| `line.300` | `#C8CFD0` | Strong hairline |
| `cyan.600` | `#0E7C86` | Measurement accent (light) |
| `cyan.400` | `#22C7D4` | Measurement accent (dark) |
| `cyan.50` | `#E6F4F5` | Accent wash |
| `vermilion.600` | `#B3261E` | Error / destructive |
| `amber.700` | `#9A6700` | Review / attention |
| `green.700` | `#1E7A4B` | Confirmed / published |
| `violet.600` | `#5B4BA8` | AI-generated content marker (explanations) |

Contrast pairs are fixed: `ink.900` on `paper.100` = 15.9:1; `ink.700` on `paper.100` = 9.8:1; `cyan.600` on
`paper.50` = 5.1:1; `vermilion.600` on `paper.50` = 6.2:1; `amber.700` on `paper.50` = 4.8:1.

## 3. Semantic tokens

| Group | Tokens |
|---|---|
| Text | `text.primary` `text.secondary` `text.tertiary` `text.disabled` `text.inverse` `text.link` |
| Surface | `surface.app` `surface.raised` `surface.sunken` `surface.overlay` `surface.selected` `surface.hover` |
| Border | `border.hairline` `border.strong` `border.focus` `border.danger` |
| Accent | `accent.measurement` `accent.measurement.wash` `accent.measurement.text` |
| Status | `status.draft` `status.queued` `status.running` `status.parked` `status.review` `status.failed` `status.needs_verification` `status.approved` `status.published` |
| Data | `data.positive` `data.negative` `data.neutral` `data.series.1…8` |
| Elevation | `elevation.0` (hairline) `elevation.1` `elevation.2` `elevation.overlay` |

**Status vocabulary is closed.** Every job/submission state maps to exactly one status token, and each
carries a word, a hue and an icon shape. Colour never travels alone (see `ACCESSIBILITY.md` §4).

## 4. Typography

| Role | Face | Size / line | Weight | Uses |
|---|---|---|---|---|
| Display | Space Grotesk | 32 / 36 | 600 | Page hero, report cover |
| H1 | Space Grotesk | 24 / 30 | 600 | Screen title |
| H2 | Space Grotesk | 18 / 24 | 600 | Section |
| H3 | Plus Jakarta Sans | 15 / 22 | 600 | Card/subsection |
| Body | Plus Jakarta Sans | 14 / 21 | 400 | Default |
| Body strong | Plus Jakarta Sans | 14 / 21 | 600 | Emphasis |
| Small | Plus Jakarta Sans | 13 / 18 | 400 | Meta, helper |
| Micro | Plus Jakarta Sans | 11 / 16 | 600 | Table headers, tracked 4% |
| Figure | Space Grotesk tabular | 14 / 20 | 600 | Marks, totals, counts |
| Figure lg | Space Grotesk tabular | 28 / 32 | 600 | Stat readouts |
| Mono | Cascadia Mono | 13 / 18 | 400 | Ids, question codes, timestamps |

Rules: body line length ≤ 78 characters; `font-variant-numeric: tabular-nums` on every figure column;
no letter-spacing on lowercase text; micro headers are the **only** uppercase role.

## 5. Space, radii, border, elevation, motion

- **Space** (4 px base): `2 4 6 8 12 16 20 24 32 40 48 64`. Component padding uses 8/12/16; section gaps 24/32.
- **Radii**: `chip 5` · `control 8` · `card 12` · `dialog 14` · `avatar 999`. Nothing else.
- **Borders**: 1 px `border.hairline` defaults; 1 px `border.strong` for selected; 2 px focus ring, offset 2.
- **Elevation**: level 0 = hairline only (default for all panels); 1 = `0 1px 2px rgba(12,15,18,.06)`;
  2 = `0 8px 24px rgba(12,15,18,.10)` for popovers; overlay = `0 24px 48px rgba(12,15,18,.18)`.
  **Shadows are never used to separate two adjacent surfaces.**
- **Motion**: `fast 120ms` (state), `base 180ms` (panel), `slow 240ms` (dialog). Easing
  `cubic-bezier(.2,.8,.2,1)`. `prefers-reduced-motion` collapses all to 0 ms opacity swaps.

## 6. Component specifications

**Button** — variants `primary` (accent bg, inverse text), `secondary` (hairline, ink text), `ghost`,
`danger` (vermilion). Sizes `sm 28px · md 34px · lg 40px`. States: rest / hover (wash) / active (pressed
1px) / focus (2px ring) / disabled (40% + no pointer) / loading (spinner replaces label, width frozen).
Icon+label gap 6; never icon-only without `aria-label`.

**Input / Textarea / Select** — 34 px, 8 radius, hairline; label above (never placeholder-only); helper
below; error replaces helper in vermilion with an icon and states the fix; `aria-describedby` wired.

**Table (ledger)** — header 32 px, micro caps, sticky; rows 34 px dense / 44 px comfortable; hover
`surface.hover`; selected `surface.selected` + 3 px marker bar; numeric cells right-aligned, tabular; no
zebra striping; sort indicator on the header cell; column resize with keyboard support.

**State chip** — 20 px, 5 radius, 11 px micro label, icon + word, tinted wash + hairline. Never a pill.

**Card** — 12 radius, hairline, 16 padding, no shadow at rest. A card that contains a table becomes a panel
with a header row, not a padded box.

**Dialog** — 14 radius, max 560 px (forms) or 880 px (review), overlay 40% ink, focus trapped, `Esc`
closes unless destructive, title + description + actions right-aligned, destructive action never default.

**Tabs** — underline 2 px `accent.measurement`, counts as micro figures; keyboard arrow navigation.

**Nav item** — 36 px, icon 18, label 14; active = 3 px marker bar + `surface.selected`; sections labelled
with micro caps; collapse to 56 px rail with tooltips.

**Toolbar** — 40 px, hairline bottom, groups separated by 1 px divider, destructive actions right and
separated by 16 px.

**Toast** — bottom-right, 320 px, hairline, one action max, auto-dismiss 6 s (never for errors).

**Empty state** — icon 24, one sentence of what this is, one primary action, optional "why" link. No
illustrations.

**Chart** — categorical palette `data.series.1…8` (colour-blind-safe ordering), 1.5 px lines, 4 px dot
markers, gridlines at 50% hairline, direct labels over legends, tooltip on focus as well as hover.

## 7. Dark theme

Same semantic names, remapped: `surface.app #0C0F12`, `surface.raised #151A1E`, `text.primary #E6EDF3`,
`border.hairline #222A30`, `accent.measurement #22C7D4`. Status hues shift +1 step lighter to hold 4.5:1 on
dark. Charts re-check contrast rather than reusing light values.

## 8. Governance

- Tokens live in one source of truth and generate both the app theme and the documentation table above.
- A new semantic token requires: purpose, contrast pair, dark mapping, and one component that uses it.
- Components are added only when two screens need them; a one-off stays local.
- Any visual change that alters density or status colour requires a review against `ACCESSIBILITY.md`.
