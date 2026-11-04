# Responsive Design

**Status:** RECOMMENDED. This is a **desktop-first professional tool**; "responsive" here means *graceful
capability reduction*, not shrinking a 1400 px canvas into a phone.

## 1. Breakpoints

| Name | Width | Target | Product stance |
|---|---|---|---|
| `xs` | < 640 | Phone | Read, approve, notify. No marking. |
| `sm` | 640–1023 | Tablet portrait / small laptop | Queue + review of individual items; no bulk tools |
| `md` | 1024–1439 | Standard laptop | Full app; review canvas in stacked mode |
| `lg` | 1440–1919 | Desktop | Full app; side-by-side review canvas |
| `xl` | ≥ 1920 | Large monitor / projector | Full app; three-pane review, wider tables |

Also respected: **125–200% browser zoom** at every breakpoint, and Windows display scaling at 125%/150%
(the most common real-world condition in schools).

## 2. Which workflows require a large screen

| Workflow | Minimum | Rationale |
|---|---|---|
| Review canvas (script + marks) | `lg` (1440) | A4 page render plus a mark column needs ~1100 px together |
| Grade matrix with > 8 columns | `md` (1024) | Below that, column freezing is worse than horizontal scroll |
| Bulk upload / import | `md` | Multi-file progress and per-file errors need room |
| Scheme review (question table) | `md` | 6-column question table |
| Dashboard, lists, settings, members | `sm` | Genuinely usable |
| Signup, invites, notifications | `xs` | Fully supported |

Below the minimum, the screen does not distort — it explains the requirement and offers the nearest useful
action ("Open on a larger screen", "Download the report instead", "Mark this one script in single-column
mode").

## 3. Layout adaptations by screen class

**List/table screens (`md` and below).** Tables convert to a *row card* at `sm`: title line, then a 2-column
definition list of the three most important fields, then status chip and one action. Sorting and filtering
move into a full-width sheet. Never render a 9-column table as horizontal scroll on a phone.

**Review canvas.** `xl`: three panes (thumbnails · page · marks). `lg`: two panes (page · marks). `md`:
stacked with a sticky mark bar at the bottom and a "jump to question" control. `< md`: read-only with
approve action; overriding is disabled with an explanation.

**Navigation.** `lg+` permanent 232 px rail. `md` collapsible 56 px icon rail with tooltips. `sm` and `xs`
bottom bar (Now, Marking, Records, More) with the workspace switcher in the header.

**Dialogs.** `sm+` centred modal (max 560/880 px). `xs` full-screen sheet with a sticky action bar.

**Dashboard.** 4-up stat row → 2-up → 1-up. Exception list always first; chart widgets collapse to their
key figure plus a "view report" link rather than shrinking axes into illegibility.

**Reports.** Always rendered server-side at a fixed A4 page size. On screen, fit-to-width with pinch/zoom;
never reflowed into a responsive web layout, because the artefact must match the printed page.

## 4. Rules

1. **No horizontal page scroll at any breakpoint.** Horizontal scrolling is allowed *inside* a table
   container with a frozen first column, and nowhere else.
2. **No information removed silently.** Anything hidden on small screens is reachable by explicit action,
   not deleted.
3. **Touch targets ≥ 44 × 44 px** at `xs`/`sm`; mouse targets ≥ 28 px at `md+`.
4. **Density is a setting, not a breakpoint.** `comfortable` / `dense` row heights are user preference and
   persist per user.
5. **Sticky context.** In long lists the header, filter bar and column header stay pinned; the primary
   action stays reachable without scrolling back.
6. **Offline is not supported for writes**, but the app must not lose a typed override: drafts persist
   locally until saved or explicitly discarded.

## 5. Performance budgets tied to layout

- First contentful paint ≤ 1.5 s on a 10 Mbps school connection.
- Route change ≤ 300 ms perceived (skeletons that match final layout, never spinners on a blank page).
- The review canvas must open with page 1 rendered before marks finish loading; marks stream in.
- Images of script pages are sized to the pane (no 4000 px scans downloaded for a 700 px pane).
