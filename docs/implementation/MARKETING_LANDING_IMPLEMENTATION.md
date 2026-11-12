# Marketing landing — implementation record (Aetrix V5.5)

Status: imported from `feat/marketing-landing-foundation` into `frontend/`. Public marketing surface only.
The authenticated workspace, its data model and the six pending owner decisions are unchanged.

## 1. What was built

A TanStack Start 1.0 marketing site for Aetrix V5.5, running on the Cloudflare Workers
runtime through the official Cloudflare Vite integration. It is the public surface described in
`docs/product/INFORMATION_ARCHITECTURE.md`, not the marking workspace.

| Surface | Route | Purpose |
| --- | --- | --- |
| Landing page | `/` | Nav, hero, product preview, workflow, features, trust, closing CTA, footer |
| Access status | `/sign-in` | Honest status page for the unbuilt sign-in flow |

`/sign-in` exists because the navigation brief requires a sign-in entry point while no identity
provider, session policy or workspace provisioning has been approved. The page states that
authentication is not enabled in this build, lists the open decisions, and offers no form. It
creates no account, sends nothing and stores nothing.

## 2. Design direction

**Concept: the mark sheet.** The memorable element is the hero headline sitting above a
question-level mark ledger — the artefact an examiner actually works in. Every other section
stays quiet so that one idea carries the page.

- **Palette:** zero hue. Graphite (`#08090A`, `#0D1011`, `#131618`) and silver hairlines in dark;
  off-white (`#F1F1EF`, `#FFFFFF`) with charcoal text in light. Status is communicated by word,
  shape and weight, never by colour, which keeps the page honest under
  `docs/design/ACCESSIBILITY.md §4` (no colour-only meaning).
- **Type:** one family, Schibsted Grotesk (self-hosted, variable 400–900), used at two roles:
  display/UI, and a data voice that uses tabular figures plus open tracking for ledger codes,
  marks and progress. A second monospace family was dropped — see §8.
- **Structure over decoration:** hairline rules, a faint ledger grid in the hero, and numbered
  workflow steps — numbering appears only where the content genuinely is a sequence.
- **Depth:** layered surfaces, a single restrained tilt on the product panel driven by pointer
  position, and two floating cards. No blurred glow layers and no `backdrop-filter`; both were
  removed during the work for rendering cost and stability, with gradient stops standing in.

## 3. Composition

1. **Navigation** — brand mark, version badge, Features / Workflow / Security, theme switch,
   Sign in. Collapses to a disclosure panel under 720px with Escape-to-close and focus return.
2. **Hero** — kicker, two-line headline ("Mark smarter. / Trust every mark."), the supplied
   supporting text, both CTAs, three platform facts, and the ledger panel with two floating cards.
3. **Product preview** — tabbed demo (`Overview` / `Questions` / `Review`) with assignment
   overview, submission progress, marking activity, question-level results, review indicators,
   a distribution chart and a sparkline. Every panel is labelled as synthetic demonstration data.
4. **Workflow** — the six intended steps, with the server-side pipeline stage marked as such.
5. **Features** — eight capabilities, each written as an intended capability rather than a
   shipped claim.
6. **Trust** — five design principles (workspace isolation, server-side correction, no provider
   credentials in browser code, auditable overrides, explicit review). No certifications,
   compliance badges or audit claims.
7. **Closing CTA + footer** — pilot framing, no invented pricing, email address or signup backend.

## 4. Animation system

All seven requested behaviours are implemented in CSS (no animation library):

| Requirement | Implementation |
| --- | --- |
| Animated charts and statistics | SVG distribution bars and sparkline draw on reveal; counters animate in the demo stats |
| Floating 3D-style elements | Two floating cards with a slow drift, plus pointer-driven `rotateX/rotateY` on the panel |
| Ambient background | CSS-gradient ledger grid and a slow drifting wash |
| Hover/click micro-interactions | Buttons, nav links, tabs, theme switch, ledger rows |
| Page/component transitions | Hero entrance sequence and tab cross-fade |
| Scroll reveal | `IntersectionObserver` hook adds `data-visible`; content is in the DOM before it runs |
| Skeleton loading | Ledger skeleton rows and shimmer for the queued result |

Motion is transform/opacity only. `prefers-reduced-motion: reduce` disables drift, tilt, reveal
translation and the entrance sequence, and leaves every value at its final state — no content
depends on an animation having run. Verified by the reduced-motion tests and by capturing every
screenshot with reduced motion enabled.

## 5. Theme system

Semantic tokens in `frontend/src/styles/tokens.css`, three layers (primitive → semantic → component).
Dark is the default, applied by an inline script before first paint to avoid a flash, persisted
under the app theme storage key, and reflected as `data-theme` on `<html>`. The switcher is a real
radio group with `aria-pressed`-style state, keyboard support and a visible focus ring. There are
no hardcoded colours in components — only semantic tokens.

## 6. Architecture preserved

- TanStack Start 1.0 (`@tanstack/react-start` 1.169.4), React 19, SSR, TypeScript strict.
- Cloudflare Workers runtime via `@cloudflare/vite-plugin` with the SSR environment, `wrangler.jsonc`
  (`compatibility_date` 2026-11-04, `nodejs_compat`), `main: @tanstack/react-start/server-entry`.
- No new hosting, no D1/R2/Queues/Workflows bindings, no secrets, no deployment.
- The authenticated app's D1 Instrument / Ledger direction is untouched; this surface does not
  borrow into it, and its animation-heavy language is deliberately confined to marketing.
- The six owner decisions in `docs/product/OWNER_APPROVAL_DECISIONS.md` remain pending. Nothing
  here should be read as approving them.

## 7. Files

New application code (all previously absent — the repository contained documentation only):

- Config: `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/wrangler.jsonc`, `frontend/tsconfig.json`,
  `frontend/tsr.config.json`, `frontend/worker-configuration.d.ts`, `frontend/playwright.config.ts`.
- Styles: `frontend/src/styles/tokens.css`, `frontend/src/styles/app.css`.
- Routes: `frontend/src/routes/__root.tsx`, `frontend/src/routes/index.tsx`, `frontend/src/routes/sign-in.tsx`.
- Site components: `frontend/src/components/site/` (header, theme switch, hero, workflow, features,
  security, closing CTA, footer, section heading).
- Product components: `frontend/src/components/product/` (hero ledger, preview, distribution chart,
  sparkline, status chip, skeleton) and `frontend/src/components/ui/` (icons, brand).
- Logic and data: `frontend/src/lib/theme.ts`, `frontend/src/lib/hooks.ts`, `frontend/src/lib/demo-data.ts`.
- Assets: `frontend/public/fonts/schibsted-grotesk.woff2`.
- Tests: `frontend/tests/marketing.spec.ts`, `frontend/tests/screenshots.mjs`.
- Docs: this file, plus `docs/implementation/screenshots/`.

No planning, design or remediation document was edited. `README.md` changed only where it
stated that no application code exists.

## 8. Known limitations

1. **Data voice uses the display family.** The intended second typeface was a monospace for
   ledger codes and marks. In this verification container Chromium has no system fonts
   (`fc-list` returns nothing) and rejected every monospace webfont tried — JetBrains Mono
   (static and variable), Fira Mono, IBM Plex Mono, Space Mono, Roboto Mono and Source Code Pro —
   reporting them as `error` after a `200 font/woff2` response, while the Schibsted Grotesk
   webfont decoded normally. Rather than ship a face that could not be verified, the data voice
   uses tabular figures and tracking from the single family. `--font-mono` remains the token for
   that role, so restoring a monospace later is a one-line change plus a `@font-face`; that
   substitution has not been verified in a browser with working system fonts.
2. **No authentication, no signup, no email.** By design — see §1.
3. **Synthetic data only.** No backend call exists on this surface.
4. **Verification environment.** The browser tests need system libraries that are not installed in
   this image; Playwright's Chromium was run with libraries fetched unprivileged into
   `/tmp/pwlibs/root`. Chromium also crashes intermittently on `page.goto` in this container
   (renderer crash, not a page error); the suite retries and the screenshot script retries each
   capture. See §9 for the exact numbers.
5. **Contrast is asserted at rest.** The axe checks run with reduced motion so that entering rows
   are measured at their final opacity. Mid-transition opacity is not a steady-state contrast
   failure, and measuring it produced false positives on the first attempt.

## 9. Verification actually run

| Check | Command | Result |
| --- | --- | --- |
| Dependency install | `npm ci` | pass |
| TypeScript (strict) | `npm run typecheck` | exit 0 |
| Production build | `npm run build` | exit 0 |
| Routes served | `curl /` and `/sign-in` against `vite preview` | 200, 200 |
| End-to-end suite | `npx playwright test` | 18 tests, 17 passed, 1 flaky (passed on retry), 0 failed, exit 0 |
| Screenshots | `cd frontend && node tests/screenshots.mjs` | 7/7 captured |
| Accessibility | axe `wcag2a/aa`, `wcag21a/aa`, `wcag22aa` on `/` (dark and light) and `/sign-in` | 0 violations |
| Responsive | overflow assertions at 360, 390, 768, 834, 1024, 1440 and beyond | no horizontal overflow |
| Themes | switch, `localStorage` persistence, reload restore, both palettes | pass |
| Reduced motion | content visible and stable when reduced; animations present when allowed | pass |
| Interactions | mobile menu Escape + focus return, tab keyboard navigation, skip link focus | pass |

The suite covers the seven animation requirements indirectly: it asserts that reduced motion
leaves content visible and stable, and that the animation system is present when motion is
allowed.

Screenshots (captured with reduced motion, generated by `frontend/tests/screenshots.mjs`):

- `screenshots/landing-hero-dark.png`, `landing-hero-light.png` — hero in both themes
- `screenshots/landing-dark.png`, `landing-light.png` — full page in both themes
- `screenshots/landing-mobile.png` (390px), `landing-tablet.png` (834px)
- `screenshots/sign-in.png`

To reproduce locally:

```bash
npm ci
npm run build
PREVIEW_HOST=<preview-host> npx vite preview --port 3000 --host 0.0.0.0   # or: npm run dev
npx playwright test
node tests/screenshots.mjs
```

## 10. Visual review notes

Three issues were found by inspecting the rendered page and fixed before completion:

- The hero headline wrapped to four lines, breaking the two-line lockup. The headline now spans
  the full container with the supporting copy and panel beneath it.
- The floating cards covered the panel's status chip and footer note. The stage now reserves
  padding for them, so they sit outside the panel at every width where they are shown.
- Monospace strings collapsed to zero size, which traced to the font issue in §8.1.
