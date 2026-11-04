# Accessibility

**Status:** RECOMMENDED. Target: **WCAG 2.2 Level AA** across the authenticated app and marketing site.
This is a design input, budgeted in phases 3–5, not a remediation phase.

## 1. Non-negotiables

1. Every function reachable by keyboard alone, in a logical order.
2. Visible focus at all times; focus is never removed, only restyled.
3. Contrast ≥ 4.5:1 for text, ≥ 3:1 for UI boundaries and graphical objects.
4. Status is never conveyed by colour alone — always colour + word + shape.
5. Text scales to 200% without loss of function or content.
6. Reduced motion honoured; nothing flashes more than 3×/second.
7. Form errors identify the field, state the problem, and say how to fix it.
8. Every page has one `h1`, a document title that matches the route, and landmark structure.

## 2. Keyboard model

| Context | Keys |
|---|---|
| Global | `⌘K`/`Ctrl+K` palette · `?` shortcuts · `G` then `H/A/Q/R` go-to · `Esc` close layer |
| Lists/tables | `↑ ↓` move rows · `Enter` open · `Space` select · `Shift+↑/↓` range · `Home/End` · `⌘A` select page |
| Review canvas | `J/K` next/prev question · `0–9` set mark · `Enter` confirm · `Tab` cycles panes · `⌘S` save · `⌘Enter` approve |
| Dialog | focus trapped; `Esc` closes (unless destructive); `Enter` submits when safe |
| Menus | arrow keys, `Home/End`, type-ahead, `Esc` returns focus to the trigger |

Focus order follows visual order; the DOM order must match. Skip link ("Skip to main content") is the first
focusable element on every page.

## 3. Semantics

- One `h1` per page; headings never skip levels for styling.
- Landmarks: `banner` (top bar), `navigation`, `main`, `complementary` (mark pane), `contentinfo`.
- Tables are real `<table>` with `<th scope>`, `<caption>` (visually hidden if needed) and `aria-sort` on
  sortable headers. No div-based grids for data.
- The PDF viewer is an `<iframe>`/canvas pair with: a text alternative describing page count and current
  page, keyboard page navigation, zoom controls, and a "download original" escape hatch. A scanned
  handwriting image cannot be described — the accessible equivalent is the *mark table*, which carries the
  same information and is always present beside it.
- Job progress uses `role="status"` with `aria-live="polite"` for stage changes and `aria-live="assertive"`
  only for failures. Announcements are throttled to at most one every 2 s.
- Icons are `aria-hidden` unless they are the only label; icon buttons always carry `aria-label`.

## 4. Colour and state encoding

| Status | Word | Shape | Hue |
|---|---|---|---|
| Queued | "Queued" | hollow circle | neutral |
| Running | "Marking" | half-filled circle | accent |
| Parked | "Waiting" | pause bars | neutral-strong |
| Review | "Needs review" | triangle | amber |
| Failed | "Failed" | filled octagon | vermilion |
| Needs verification | "Unverified" | question mark | amber-strong |
| Approved | "Approved" | check | green |
| Published | "Published" | double check | green-strong |

Chart series use a colour-blind-safe categorical order and are additionally distinguished by line style or
direct labels. No chart encodes a grade band by hue alone; bands carry a label and a boundary rule.

## 5. Forms

- Label above input, always visible; placeholders are examples, never labels.
- Required fields marked in the label text ("Mark scheme (required)"), not by an asterisk alone.
- Validation on blur and on submit, never on first keystroke.
- Errors: `aria-invalid`, `aria-describedby` pointing at the message, message text that names the fix
  ("Mark cannot exceed 4 for question 3").
- Error summary at the top of long forms, linking to each field.
- Autocomplete attributes on identity fields; one-time-code on MFA.

## 6. Motion and timing

- `prefers-reduced-motion: reduce` collapses transitions to ≤ 1 frame; no parallax, no auto-playing motion.
- No time limit on any task. Session expiry gives a 5-minute warning with a one-click extend.
- Toasts that carry information also persist in the notification centre (no information only in a toast).
- Auto-dismiss is disabled for errors; 6 s for success messages, with pause on hover/focus.

## 7. Testing gates (each phase)

| Gate | Method | Blocking? |
|---|---|---|
| Automated axe scan on every route | CI, Playwright + axe-core | Yes (zero serious/critical) |
| Keyboard-only walkthrough of new flows | Manual, scripted per phase | Yes |
| Screen-reader pass (NVDA on Windows) | Manual, per release | Yes for new flows |
| 200% zoom + 125% OS scaling | Manual, per phase | Yes |
| Contrast audit of tokens | Automated token check | Yes |
| Colour-blind simulation of charts | Manual, per release | No (advisory) |

## 8. Known hard problems (documented, not hidden)

- **Handwritten script content is inherently inaccessible.** Mitigation: the mark table is the accessible
  representation; the AI explanation is available as text; page images are supplementary.
- **Dense tables at 200% zoom** will scroll horizontally inside their container. Accepted, because the
  alternative (removing columns) loses information.
- **Third-party OAuth screens** (Google) are outside our conformance scope.
