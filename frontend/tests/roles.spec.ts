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
    await expect(nav.getByRole('link', { name: 'Workspaces' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Accounts' })).toBeVisible()
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
    // token, the screen names the gap and renders no quota figure.
    await expect(
      page
        .getByText(/no public HTTPS deployment yet|The engine rejected the request \(401\)/)
        .first(),
    ).toBeVisible()
    for (const label of ['API keys', 'Contributors', 'Projects', 'Usage', 'Alerts']) {
      await page.getByRole('tab', { name: label }).click()
      await expect(page.getByRole('tab', { name: label })).toHaveAttribute('aria-selected', 'true')
      await expect(page.locator('.gem-panel')).toBeVisible()
    }
  })
})

test.describe('platform owner', () => {
  test('renders the owner identity across the platform rail', async ({ context }) => {
    const page = await open(context, '/platform', { role: 'owner' })

    await expect(page.locator('.app')).toHaveAttribute('data-role', 'owner')
    await expect(page.locator('.app-topbar__role')).toHaveText('Platform owner')

    const nav = page.locator('.app-nav')
    await expect(nav.getByRole('link', { name: 'Workspaces' })).toBeVisible()
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

  test('gives an ordinary administrator no way to assign or remove it', async ({ context }) => {
    const page = await open(context, '/platform/users', { role: 'platform_operator' })

    await expect(
      page.getByRole('heading', { name: 'Account management needs an admin surface' }),
    ).toBeVisible()
    // No control writes a role: assignment is an identity-provider action.
    await expect(page.locator('select')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: /assign|grant|change role|remove role|promote/i }),
    ).toHaveCount(0)
    await expect(page.getByText(/identity provider/i).first()).toBeVisible()
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
    await expect(page.locator('.app-nav').getByRole('link', { name: 'Accounts' })).toHaveCount(0)
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

    // Workspace and platform administration are absent, not merely disabled.
    await expect(nav.getByRole('link', { name: 'Assistants' })).toHaveCount(0)
    await expect(nav.getByRole('link', { name: 'Workspace', exact: true })).toHaveCount(0)
    await expect(nav.getByRole('link', { name: 'Accounts', exact: true })).toHaveCount(0)
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
