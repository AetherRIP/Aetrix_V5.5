---
name: aetrix-frontend
description: Conventions and design system for the Aetrix frontend (TanStack Start, React 19, Vite, Cloudflare Workers, Supabase JS, Playwright). Use when changing anything under frontend/src or frontend/tests — routes, the app shell, dashboard or hub components, styles, tokens, theme, animation, auth UI, API contracts, or end-to-end tests.
license: Proprietary (Aetrix project skill)
metadata:
  author: Aetrix
  version: '1.0.0'
---

# Aetrix frontend conventions

TanStack Start 1.169 + TanStack Router 1.170 (file-based routes), React 19, TypeScript 6,
Vite 8 with the Cloudflare Vite plugin, wrangler 4, `@supabase/supabase-js`, Playwright 1.64
with `@axe-core/playwright`. No UI framework, no Tailwind, no animation library.

## Layout

```
frontend/src/routes/      file-based routes: _marketing.*, _app.*, auth.callback
frontend/src/components/  app/ (shell), hub/ (dashboard), product/ (marketing), site/, ui/
frontend/src/lib/         env.ts, supabase.ts, auth/, api/ (client + types), theme.ts, format.ts
frontend/src/styles/      tokens.css → app.css (marketing) → hub.css (app shell + motion)
frontend/tests/           auth.spec.ts, marketing.spec.ts, responsive.spec.ts
```

- `_app.*` routes render inside `AppShell`; `_app.tsx` owns the page metadata table
  (`title`, `eyebrow`) — add the path there when adding a route, and normalise trailing
  slashes (`/dashboard/` previously fell through to the wrong title).
- The marketing surface is independent: do not make it depend on app state or Supabase.
- Build output is prerendered by the Cloudflare plugin; keep routes SSR-safe (no
  `window`/`localStorage` at module scope).

## Styling rules

- `tokens.css` holds the single source of truth: colour ramp, type scale, spacing, radii
  (`--r-sm/md/lg/xl/2xl`), motion. Extend tokens; never hardcode a hex or a magic radius.
- `app.css` is the marketing stylesheet. `hub.css` owns the app shell and dashboard.
  Shared primitives (`app-card`, `state-panel`, `data-table`) live in `hub.css`.
- Only `transform` and `opacity` animate. No layout transitions, no `filter: blur` loops,
  no new dependency for motion.
- Every entrance, drift, shimmer and pulse must be inside the `prefers-reduced-motion`
  block that disables it. Verify with `emulateMedia({ reducedMotion: 'reduce' })`.
- No horizontal overflow at any breakpoint; the phone layout uses the tab bar plus the
  "More" sheet rather than a drawer.
- One `h1` per route; visible focus; `aria-current` on navigation.

## Data honesty

`src/lib/api/client.ts` returns `ApiResult<T>` with `ok | unavailable | error`. The engine
has no public deployment, so screens render an explicit unavailable state. Never render
zeros, sample rows, or invented metrics — use `API_UNAVAILABLE_REASON` and
`StatePanel`/`HubStats` empty conventions already in the codebase.

## Auth

`getSupabase()` returns `null` when the build has no configuration; treat that as
"authentication unavailable", never as a signed-out user. PKCE flow, callback at
`/auth/callback`, storage key `aetrix:auth`. Browser config is `VITE_SUPABASE_URL` and
`VITE_SUPABASE_ANON_KEY` (public by design); the service-role key must never appear in
this bundle. `VITE_AETRIX_API_URL` is optional and gates the engine client.

## Verify

```bash
cd frontend
../.tools/node/node.exe node_modules/typescript/bin/tsc --noEmit
../.tools/node/node.exe node_modules/vite/bin/vite.js build      # 17 pages prerendered
../.tools/node/node.exe node_modules/vite/bin/vite.js preview --port 3000
../.tools/node/node.exe node_modules/@playwright/test/cli.js test # needs the preview above
```

- `node`/`npx` are not on PATH in this workspace; invoke `.tools/node/node.exe` explicitly.
- The e2e suite runs against an already-running preview (`BASE_URL` overrides the default
  `http://127.0.0.1:3000`) and seeds auth through the `aetrix:auth` localStorage key.
- Visual work is unverified until it has been looked at. Capture fixed viewports; the
  desktop panel's screenshot resizes the page and misleads.
- Do not weaken assertions or delete a route to make a test pass.
