import { expect, test, type BrowserContext, type Page } from '@playwright/test'

/**
 * The three account types.
 *
 * A real Google round-trip needs an interactive Google session, so these tests
 * seed the session object that Supabase would have stored after one. That is the
 * same object `supabase.auth.getSession()` reads, and the role travels in its
 * `app_metadata` — the field only the identity provider's admin API can write.
 * The point of the suite is that nothing *else* opens a dashboard: the shell,
 * the navigation and the route guards all read that one claim.
 */

type Role = 'owner' | 'platform_operator' | 'supervisor' | 'assistant'

const EMAIL: Record<Role, string> = {
  owner: 'owner@aetrix.test',
  platform_operator: 'operator@aetrix.test',
  supervisor: 'teacher@aetrix.test',
  assistant: 'ana@aetrix.test',
}

function session(
  appMetadata: Record<string, unknown>,
  email: string,
  userMetadata: Record<string, unknown> = {},
) {
  const now = Math.floor(Date.now() / 1000)
  return {
    access_token: 'test-access-token',
    token_type: 'bearer',
    expires_in: 3600,
    // Far in the future: the client must not try to refresh a token it cannot.
    expires_at: 4102444800,
    refresh_token: 'test-refresh-token',
    user: {
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      role: 'authenticated',
      email,
      email_confirmed_at: new Date(now * 1000).toISOString(),
      phone: '',
      confirmed_at: new Date(now * 1000).toISOString(),
      last_sign_in_at: new Date(now * 1000).toISOString(),
      app_metadata: appMetadata,
      user_metadata: { full_name: 'Ana Ruiz', name: 'Ana Ruiz', ...userMetadata },
      identities: [],
      created_at: new Date(now * 1000).toISOString(),
      updated_at: new Date(now * 1000).toISOString(),
    },
  }
}

/** Seeds the stored Supabase session before the application boots. */
async function withRole(page: Page, role: Role | null) {
  const payload = role
    ? session({ provider: 'google', aetrix_role: role }, EMAIL[role])
    : session({ provider: 'google' }, 'newcomer@aetrix.test')

  await page.addInitScript((value) => {
    window.localStorage.setItem('aetrix:auth', JSON.stringify(value))
  }, payload)
}

/**
 * A session whose *user-writable* metadata claims ownership. `user_metadata` is
 * written by the account itself, so it must never be consulted for a role; only
 * the identity provider can write `app_metadata`.
 */
async function withSpoofedOwner(page: Page) {
  const payload = session({ provider: 'google' }, 'newcomer@aetrix.test', {
    aetrix_role: 'owner',
  })

  await page.addInitScript((value) => {
    window.localStorage.setItem('aetrix:auth', JSON.stringify(value))
  }, payload)
}

async function open(
  context: BrowserContext,
  path: string,
  options: { role?: Role | null; width?: number; reducedMotion?: 'reduce' | 'no-preference' } = {},
) {
  const { role = null, width = 1440, reducedMotion = 'no-preference' } = options
  const page = await context.newPage()
  await page.setViewportSize({ width, height: 1000 })
  await page.emulateMedia({ reducedMotion })
  await withRole(page, role)
  const response = await page.goto(path, { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  return page
}

test.describe('platform administrator', () => {
  test('lands on the platform dashboard with platform navigation only', async ({ context }) => {
    const page = await open(context, '/platform', { role: 'platform_operator' })

    await expect(page.locator('.app')).toHaveAttribute('data-role', 'platform_operator')
    await expect(page.locator('.app-topbar__role')).toHaveText('Platform administrator')

    const nav = page.locator('.app-nav')
    await expect(nav.getByRole('link', { name: 'Allocation' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Account management' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'System health' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Audit log' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Gemini fleet' })).toBeVisible()

    // Academic destinations are not in an operator's rail at all.
    await expect(nav.getByRole('link', { name: 'Marking queue' })).toHaveCount(0)
    await expect(nav.getByRole('link', { name: 'Gradebook' })).toHaveCount(0)
  })

  test('is moved out of the teacher area to the platform home', async ({ context }) => {
    const page = await open(context, '/dashboard', { role: 'platform_operator' })
    await expect(page).toHaveURL(/\/platform\/?$/, { timeout: 20_000 })
  })

  test('routes the Gemini quota slot to the fleet screen', async ({ context }) => {
    const page = await open(context, '/platform/integrations', { role: 'platform_operator' })

    await expect(page.getByRole('heading', { level: 1, name: 'AI providers' })).toBeVisible()
    await expect(page.getByRole('main')).toContainText('Gemini')

    await page.getByRole('link', { name: 'Open the Gemini fleet' }).click()
    await expect(page).toHaveURL(/\/platform\/gemini\/?$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Gemini fleet' })).toBeVisible()
  })

  test('states the fleet data gap rather than showing figures', async ({ context }) => {
    const page = await open(context, '/platform/gemini', { role: 'platform_operator' })

    // Whether the build has no engine origin or the engine rejects the seeded
    // token, the screen names the gap and renders no quota figure. The engine's
    // own message varies by build (configured origin, 401, network), so any of
    // those variants satisfies the check; a page showing figures without a gap
    // statement still fails it.
    await expect(
      page
        .getByText(
          /no public HTTPS deployment yet|The engine rejected the request \(401\)|The engine could not be reached|The bearer token is invalid or has expired|The figures below are not being guessed/,
        )
        .first(),
    ).toBeVisible()
    for (const label of ['API keys', 'Contributors', 'Projects', 'Usage', 'Alerts']) {
      await page.getByRole('tab', { name: label }).click()
      await expect(page.getByRole('tab', { name: label })).toHaveAttribute('aria-selected', 'true')
      await expect(page.locator('.gem-panel')).toBeVisible()
    }
  })

  test('reports a 204 key removal as success and keeps model pools separate', async ({ context }) => {
    const page = await context.newPage()
    await page.setViewportSize({ width: 1440, height: 1000 })
    await withRole(page, 'platform_operator')

    const estimate = {
      project_id: 'operator-declared-project',
      model: 'gemini-3.6-flash',
      confidence: 'ESTIMATED',
      requests_per_minute: { limit: 10, used: 1, remaining: 9, used_share: 0.1, confidence: 'ESTIMATED' },
      tokens_per_minute: { limit: null, used: 0, remaining: null, used_share: null, confidence: 'UNKNOWN' },
      requests_per_day: { limit: 200, used: 13, remaining: 187, used_share: 0.065, confidence: 'ESTIMATED' },
      reset_at: '2026-11-10T08:00:00Z',
      observed_at: '2026-11-09T12:00:00Z',
      cooldown_until: null,
      exhausted: false,
      notes: [],
    }
    const key = {
      id: '00000000-0000-4000-8000-000000000010',
      contributor_id: null,
      contributor_name: null,
      revoked_at: null,
      project_id: 'operator-declared-project',
      account_label: 'Disposable test key',
      key_fingerprint: 'test-fingerprint',
      auth_type: 'api_key',
      tier: 'UNKNOWN',
      health: 'HEALTHY',
      model_access: ['gemini-3.6-flash'],
      cooldown_until: null,
      last_success_at: null,
      last_failure_at: null,
      last_failure_status: null,
      last_validated_at: null,
      last_error: null,
      requests: 0,
      input_tokens: 0,
      output_tokens: 0,
      failures: 0,
      quota_failures: 0,
    }

    await page.route('**/api/v1/admin/providers/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() === 'DELETE') {
        await route.fulfill({ status: 204, body: '' })
        return
      }
      if (path.endsWith('/overview')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            keys_total: 1,
            keys_by_health: { HEALTHY: 1 },
            projects: 1,
            requests_today: 0,
            input_tokens_today: 0,
            output_tokens_today: 0,
            failures_today: 0,
            error_rate_today: null,
            observed_at: '2026-11-09T12:00:00Z',
            day_started_at: '2026-11-09T08:00:00Z',
            reset_at: '2026-11-10T08:00:00Z',
            projects_detail: [
              {
                project_id: 'operator-declared-project',
                keys: 1,
                healthy: 1,
                disabled: 0,
                invalid: 0,
                cooldown_until: null,
                estimates: [estimate, { ...estimate, model: 'gemini-3.1-pro-preview' }],
              },
            ],
          }),
        })
        return
      }
      if (path.endsWith('/keys')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: [key], total: 1, limit: 50, offset: 0 }),
        })
        return
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })

    await page.goto('/platform/gemini', { waitUntil: 'load' })
    await expect(page.getByText(/not additive/)).toBeVisible()

    await page.getByRole('tab', { name: 'API keys' }).click()
    await expect(page.getByText('Disposable test key')).toBeVisible()
    page.on('dialog', (dialog) => void dialog.accept())
    await page.getByRole('button', { name: 'Remove' }).click()
    await expect(page.getByRole('status')).toContainText('Removal succeeded.')
  })
})

test.describe('platform owner', () => {
  test('renders the owner identity across the platform rail', async ({ context }) => {
    const page = await open(context, '/platform', { role: 'owner' })

    await expect(page.locator('.app')).toHaveAttribute('data-role', 'owner')
    await expect(page.locator('.app-topbar__role')).toHaveText('Platform owner')

    const nav = page.locator('.app-nav')
    await expect(nav.getByRole('link', { name: 'Allocation' })).toBeVisible()
    // The owner is not locked out of the other two dashboards.
    await expect(nav.getByRole('link', { name: 'Teacher dashboard' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Assistant overview' })).toBeVisible()
  })

  test('opens teacher and assistant areas without being confined', async ({ context }) => {
    for (const path of ['/dashboard', '/students', '/queue', '/assistant', '/assistant/tasks']) {
      const page = await open(context, path, { role: 'owner' })

      await expect(page.locator('.app')).toHaveAttribute('data-role', 'owner')
      await expect(
        page.getByRole('heading', { name: 'This screen belongs to another account type' }),
      ).toHaveCount(0)
      await page.close()
    }
  })

  test('opens the fleet screen with its contributor tab', async ({ context }) => {
    const page = await open(context, '/platform/gemini', { role: 'owner' })

    await expect(page.getByRole('heading', { level: 1, name: 'Gemini fleet' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Contributors' })).toBeVisible()
  })

  test('cannot be granted by editing user metadata', async ({ context }) => {
    const page = await context.newPage()
    await withSpoofedOwner(page)
    await page.goto('/platform')

    await expect(page.getByRole('heading', { name: 'No account role assigned' })).toBeVisible()
    await expect(page.locator('.app')).toHaveCount(0)
  })

  test('is told when platform-wide access needs a service-role key', async ({ context }) => {
    const page = await context.newPage()
    await page.setViewportSize({ width: 1440, height: 1000 })
    await withRole(page, 'platform_operator')

    await page.route('**/api/v1/admin/accounts**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: false,
          reason:
            'AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY is not set on the engine, so platform-wide accounts cannot be read.',
          operations: [],
        }),
      }),
    )

    await page.goto('/platform/users', { waitUntil: 'load' })

    await expect(
      page.getByRole('heading', { name: 'Platform-wide accounts need a Supabase service-role key' }),
    ).toBeVisible()
    // With no credential there is no account list and no control that writes a role.
    await expect(page.locator('select')).toHaveCount(0)
    await expect(page.locator('.data-table')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: /assign|grant|change role|remove role|promote/i }),
    ).toHaveCount(0)
    await expect(page.getByText(/AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY/).first()).toBeVisible()
  })
})

test.describe('teacher', () => {
  test('opens the workspace hub with the teaching navigation', async ({ context }) => {
    const page = await open(context, '/dashboard', { role: 'supervisor' })

    await expect(page.locator('.app')).toHaveAttribute('data-role', 'supervisor')
    await expect(page.locator('.app-topbar__role')).toHaveText('Teacher')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Ana')

    const nav = page.locator('.app-nav')
    await expect(nav.getByRole('link', { name: 'Classes & students' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Gradebook' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Assistants' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Platform overview' })).toHaveCount(0)
  })

  test('cannot enter the platform area', async ({ context }) => {
    const page = await open(context, '/platform/users', { role: 'supervisor' })
    await expect(page).toHaveURL(/\/dashboard\/?$/, { timeout: 20_000 })
    await expect(
      page.locator('.app-nav').getByRole('link', { name: 'Account management' }),
    ).toHaveCount(0)
  })

  test('shows the workspace scope it is confined to', async ({ context }) => {
    const page = await open(context, '/workspace', { role: 'supervisor' })
    await expect(page.locator('.hub-workspace__note')).toHaveText('Own workspace only')
  })
})

test.describe('assistant', () => {
  test('opens a personal overview with no administration', async ({ context }) => {
    const page = await open(context, '/assistant', { role: 'assistant' })

    await expect(page.locator('.app')).toHaveAttribute('data-role', 'assistant')
    await expect(page.locator('.app-topbar__role')).toHaveText('Assistant')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Ana')

    const nav = page.locator('.app-nav')
    await expect(nav.getByRole('link', { name: 'My overview' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Submission queue' })).toBeVisible()

    // The manual upload path is reachable from the assistant's own rail.
    const uploads = nav.getByRole('link', { name: 'Uploads' })
    await expect(uploads).toBeVisible()
    await expect(uploads).toHaveAttribute('href', '/assignments')

    // Workspace and platform administration are absent, not merely disabled.
    await expect(nav.getByRole('link', { name: 'Assistants' })).toHaveCount(0)
    await expect(nav.getByRole('link', { name: 'Workspace', exact: true })).toHaveCount(0)
    await expect(
      nav.getByRole('link', { name: 'Account management', exact: true }),
    ).toHaveCount(0)
  })

  test('is refused a teacher-only screen, with the reason stated', async ({ context }) => {
    const page = await open(context, '/students', { role: 'assistant' })

    await expect(
      page.getByRole('heading', { name: 'This screen belongs to another account type' }),
    ).toBeVisible()
    await expect(page.locator('.state-panel')).toContainText('Assistant')
    // The restricted screen offers a way back rather than a blank page.
    await expect(page.getByRole('link', { name: 'Go to my dashboard' })).toBeVisible()
  })

  test('is moved out of the platform area', async ({ context }) => {
    const page = await open(context, '/platform', { role: 'assistant' })
    await expect(page).toHaveURL(/\/assistant\/?$/, { timeout: 20_000 })
  })
})

test.describe('no role', () => {
  test('a verified account without a role is offered no dashboard', async ({ context }) => {
    const page = await open(context, '/dashboard')

    await expect(page.getByRole('heading', { name: 'No account role assigned' })).toBeVisible()
    await expect(page.locator('.app-sidebar')).toHaveCount(0)
    await expect(page.locator('.app-nav')).toHaveCount(0)
    await expect(page.getByText(/platform_operator/)).toBeVisible()
  })
})

/**
 * Every dashboard route must paint its own content. A nested route that silently
 * renders its parent's page would still show the right page title, so each entry
 * below names a card that exists only on that screen.
 */
const ROUTE_CONTENT: { role: Role; path: string; card: string }[] = [
  { role: 'owner', path: '/platform', card: 'Workspace allocation' },
  { role: 'owner', path: '/platform/users', card: 'Role assignment' },
  { role: 'owner', path: '/platform/gemini', card: 'Gemini fleet' },
  { role: 'owner', path: '/students', card: 'Classes' },
  { role: 'owner', path: '/assistant', card: 'Review rules' },
  { role: 'platform_operator', path: '/platform', card: 'Workspace allocation' },
  { role: 'platform_operator', path: '/platform/workspaces', card: 'Allocation rules' },
  { role: 'platform_operator', path: '/platform/users', card: 'Role assignment' },
  { role: 'platform_operator', path: '/platform/health', card: 'Service state' },
  { role: 'platform_operator', path: '/platform/audit', card: 'What is recorded' },
  { role: 'platform_operator', path: '/platform/integrations', card: 'Gemini usage' },
  { role: 'platform_operator', path: '/platform/gemini', card: 'Gemini fleet' },
  { role: 'platform_operator', path: '/platform/settings', card: 'Platform defaults' },
  { role: 'supervisor', path: '/students', card: 'Classes' },
  { role: 'supervisor', path: '/gradebook', card: 'Marks' },
  { role: 'supervisor', path: '/analytics', card: 'Question-level performance' },
  { role: 'supervisor', path: '/assistants', card: 'What an assistant may do' },
  { role: 'supervisor', path: '/classroom', card: 'How a class reaches this workspace' },
  { role: 'assistant', path: '/assistant', card: 'Review rules' },
  { role: 'assistant', path: '/assistant/classes', card: 'What is in scope' },
  { role: 'assistant', path: '/assistant/work', card: 'A review, once marking exists' },
  { role: 'assistant', path: '/assistant/tasks', card: 'Task list' },
  { role: 'assistant', path: '/assistant/progress', card: 'What these figures would count' },
]

test.describe('dashboard routes', () => {
  test('each screen renders its own content', async ({ context }) => {
    for (const entry of ROUTE_CONTENT) {
      const page = await open(context, entry.path, { role: entry.role })
      await expect(
        page.locator('.app-card__title', { hasText: entry.card }),
        `${entry.path} should show “${entry.card}”`,
      ).toBeVisible()
      await expect(page.locator('.app')).toHaveAttribute('data-role', entry.role)
      await page.close()
    }
  })
})

test.describe('shell behaviour', () => {
  test('the rail collapses, remembers the choice and stays keyboard operable', async ({
    context,
  }) => {
    const page = await open(context, '/dashboard', { role: 'supervisor' })

    const toggle = page.getByRole('button', { name: 'Collapse navigation' })
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await toggle.click()

    await expect(page.locator('.app')).toHaveClass(/app--rail-collapsed/)
    // Icons remain reachable, so the collapsed rail is still a navigation.
    await expect(page.locator('.app-nav__link')).toHaveCount(12)
    expect(await page.evaluate(() => localStorage.getItem('aetrix:rail'))).toBe('collapsed')

    await page.reload({ waitUntil: 'load' })
    await expect(page.locator('.app')).toHaveClass(/app--rail-collapsed/)
    await expect(page.getByRole('button', { name: 'Expand navigation' })).toBeVisible()
  })

  test('the phone layout keeps the tab bar and never scrolls sideways', async ({ context }) => {
    const page = await open(context, '/assistant', { role: 'assistant', width: 390 })

    await expect(page.locator('.app-sidebar')).toBeHidden()
    await expect(page.locator('.hub-tabs')).toBeVisible()
    await expect(page.locator('.hub-tab').first()).toBeVisible()

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })

  test('every role home fits a phone without sideways scrolling', async ({ context }) => {
    for (const [role, path] of [
      ['platform_operator', '/platform'],
      ['supervisor', '/students'],
      ['assistant', '/assistant/progress'],
    ] as const) {
      const page = await open(context, path, { role, width: 360 })
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      )
      expect(overflow, `${path} overflows at 360px`).toBeLessThanOrEqual(0)
      await page.close()
    }
  })

  test('the session survives a reload and sign-out closes the shell', async ({ context }) => {
    const seeded = await open(context, '/settings', { role: 'supervisor' })
    await expect(seeded.locator('.app')).toHaveAttribute('data-role', 'supervisor')

    // A different page has no seed script: its identity can only come from the
    // session the first page stored, which is what a reload reads.
    const restored = await context.newPage()
    await restored.goto('/settings', { waitUntil: 'load' })
    await expect(restored.locator('.app')).toHaveAttribute('data-role', 'supervisor')

    await restored.getByRole('button', { name: 'Sign out' }).click()
    await expect(restored).toHaveURL(/\/sign-in\/?$/, { timeout: 20_000 })
    expect(await restored.evaluate(() => localStorage.getItem('aetrix:auth'))).toBeNull()

    // A third page has neither the seed script nor a session, so the protected
    // route must stay closed rather than fall back to a cached principal.
    const after = await context.newPage()
    await after.goto('/dashboard', { waitUntil: 'load' })
    await expect(after).toHaveURL(/\/sign-in\/?$/, { timeout: 20_000 })
  })

  test('entrances are disabled when the reader asks for reduced motion', async ({ context }) => {
    const page = await open(context, '/platform', {
      role: 'platform_operator',
      reducedMotion: 'reduce',
    })

    // The page is the operator dashboard, so the hero and its first section are
    // the entrances a reader with `prefers-reduced-motion` should never see.
    await expect(page.locator('.hub-hero')).toBeVisible()

    const names = await page.evaluate(() => {
      const read = (selector: string, pseudo?: string) => {
        const element = document.querySelector(selector)
        return element ? getComputedStyle(element, pseudo ?? null).animationName : 'missing'
      }
      return { hero: read('.hub-hero'), section: read('.hub-section') }
    })
    expect(names).toEqual({ hero: 'none', section: 'none' })
  })
})

test.describe('engine provisioning and role fallback', () => {
  test('opens the shell from the engine role when the browser claim is absent', async ({
    context,
  }) => {
    const page = await context.newPage()
    await page.setViewportSize({ width: 1440, height: 1000 })
    await withRole(page, null)

    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/v1/me') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            user_id: '00000000-0000-4000-8000-000000000001',
            subject: 'invited-user-1',
            email: 'newcomer@aetrix.test',
            display_name: 'Invited Teacher',
            tenant_id: '00000000-0000-4000-8000-000000000010',
            workspace_name: 'Invited workspace',
            workspace_slug: 'invited',
            role: 'TEACHER',
            ui_role: 'supervisor',
            capabilities: ['read', 'manage_exams', 'review', 'approve'],
            is_demo: false,
          }),
        })
        return
      }
      if (path.endsWith('/dashboard')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            assignments: 0,
            submissions: 0,
            jobs_active: 0,
            awaiting_review: 0,
            failed_jobs: 0,
            approved_results: 0,
            recent_jobs: [],
          }),
        })
        return
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })

    const response = await page.goto('/dashboard', { waitUntil: 'load' })
    expect(response?.status()).toBe(200)
    await expect(page.locator('.app')).toHaveAttribute('data-role', 'supervisor')
    await expect(page.locator('.app-sidebar')).toBeVisible()
  })

  test('shows the invitation gate, not a blank dashboard, when the engine refuses provisioning', async ({
    context,
  }) => {
    const page = await context.newPage()
    await page.setViewportSize({ width: 1440, height: 1000 })
    await withRole(page, null)

    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/v1/me') {
        await route.fulfill({
          status: 403,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'PROVISIONING_REQUIRED',
              message: 'This account has not been invited to a workspace.',
            },
          }),
        })
        return
      }
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    })

    const response = await page.goto('/dashboard', { waitUntil: 'load' })
    expect(response?.status()).toBe(200)
    await expect(
      page.getByRole('heading', { name: 'A workspace invitation is required' }),
    ).toBeVisible()
    await expect(page.getByLabel('One-time acceptance code')).toBeVisible()
  })
})
