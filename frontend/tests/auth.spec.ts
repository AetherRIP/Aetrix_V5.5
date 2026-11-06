import { expect, test, type BrowserContext, type Page } from '@playwright/test'

/**
 * These tests exercise the authentication surface that can be verified without a
 * Google account: the sign-in page, the authorize request the Supabase client
 * builds, the protected-route guard, the callback's failure handling and the
 * static HTML emitted for nested routes. A real consent round-trip requires an
 * interactive Google session and is reported separately.
 */

const PROTECTED_ROUTES = [
  '/dashboard',
  '/workspace',
  '/inbox',
  '/queue',
  '/assignments',
  '/assignments/example',
  '/submissions/example',
  '/reports',
  '/settings',
]

type OpenOptions = { width?: number; height?: number; reducedMotion?: 'reduce' | 'no-preference' }

/** Same retry-on-renderer-crash helper as the marketing suite. */
async function open(
  context: BrowserContext,
  path = '/',
  options: OpenOptions = {},
): Promise<Page> {
  const { width = 1440, height = 1000, reducedMotion = 'no-preference' } = options
  let lastError: unknown

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const page = await context.newPage()
    try {
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ reducedMotion })
      const response = await page.goto(path, { waitUntil: 'load' })
      expect(response?.status()).toBe(200)
      return page
    } catch (error) {
      lastError = error
      await page.close().catch(() => {})
    }
  }

  throw lastError
}

async function storedSession(page: Page) {
  return page.evaluate(() => {
    const raw = localStorage.getItem('aetrix:auth')
    if (!raw) return null
    return raw.length
  })
}

test.describe('sign-in page', () => {
  test('offers Google sign-in and states the access policy honestly', async ({ context }) => {
    const page = await open(context, '/sign-in')

    await expect(page.getByRole('heading', { name: 'Sign in to Aetrix' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeEnabled()

    // No self-serve signup is offered, and the page says so.
    await expect(page.getByText(/no self-serve sign-up/i)).toBeVisible()

    // The status panel lists only methods that are actually enabled.
    await expect(page.locator('#access')).toContainText('Google OAuth · enabled')
    await expect(page.locator('#access')).toContainText('Workspace provisioning')
    await expect(page.locator('#access')).toContainText('Work in progress')

    // Nothing is signed in at this point.
    expect(await storedSession(page)).toBeNull()
  })

  test('Google button starts a real Supabase PKCE authorize request', async ({ context }) => {
    const page = await open(context, '/sign-in')
    const origin = new URL(page.url()).origin

    let authorizeUrl = ''
    await page.route('**/auth/v1/authorize**', async (route) => {
      authorizeUrl = route.request().url()
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<!doctype html><title>provider stub</title><p>provider stub</p>',
      })
    })

    await page.getByRole('button', { name: 'Continue with Google' }).click()
    await expect.poll(() => authorizeUrl, { timeout: 15_000 }).toContain('/auth/v1/authorize')

    const url = new URL(authorizeUrl)
    expect(url.host).toBe('wswsibspyjrhlahxcefs.supabase.co')
    expect(url.searchParams.get('provider')).toBe('google')

    // The allow-list friendly callback: origin + path, no query parameters.
    expect(url.searchParams.get('redirect_to')).toBe(`${origin}/auth/callback`)

    // Proof it is a real PKCE handshake rather than a hand-built URL.
    expect(url.searchParams.get('code_challenge_method')).toBe('s256')
    expect(url.searchParams.get('code_challenge')?.length ?? 0).toBeGreaterThan(20)
  })

  test('theme choice persists on the sign-in page', async ({ context }) => {
    const first = await open(context, '/sign-in')
    await first.getByRole('button', { name: 'Light', exact: true }).click()
    await expect(first.locator('html')).toHaveAttribute('data-theme', 'light')
    expect(await first.evaluate(() => localStorage.getItem('aetrix:theme'))).toBe('light')

    const second = await open(context, '/sign-in')
    await expect(second.locator('html')).toHaveAttribute('data-theme', 'light')

    // Restore the default for later specs sharing the storage state.
    await second.getByRole('button', { name: 'Dark', exact: true }).click()
  })
})

test.describe('protected routes', () => {
  for (const route of PROTECTED_ROUTES) {
    test(`anonymous visitor at ${route} is sent to sign-in`, async ({ context }) => {
      const page = await open(context, route)

      await expect(page).toHaveURL(/\/sign-in\/?$/, { timeout: 20_000 })
      // The application chrome is never rendered for a visitor without a session.
      await expect(page.locator('.app-sidebar')).toHaveCount(0)
      await expect(page.locator('.app-topbar')).toHaveCount(0)
      await expect(page.getByRole('heading', { name: 'Sign in to Aetrix' })).toBeVisible()
    })
  }

  test('the requested destination survives the redirect without a fake session', async ({
    context,
  }) => {
    const page = await open(context, '/queue')
    await expect(page).toHaveURL(/\/sign-in\/?$/, { timeout: 20_000 })

    expect(
      await page.evaluate(() => sessionStorage.getItem('aetrix:auth-next')),
    ).toBe('/queue')
    expect(await storedSession(page)).toBeNull()
  })
})

test.describe('OAuth callback', () => {
  test('a cancelled authorization is reported, not treated as success', async ({ context }) => {
    const page = await open(
      context,
      '/auth/callback#error=access_denied&error_description=User+denied+access',
    )

    await expect(page.getByRole('heading', { name: /Sign-in did not complete/i })).toBeVisible({
      timeout: 20_000,
    })
    await expect(page.getByRole('link', { name: 'Return to sign-in' })).toBeVisible()
    expect(await storedSession(page)).toBeNull()
  })

  test('a callback without a code does not claim a session', async ({ context }) => {
    const page = await open(context, '/auth/callback')

    await expect(page.getByRole('heading', { name: /Sign-in did not complete/i })).toBeVisible({
      timeout: 20_000,
    })
    expect(await storedSession(page)).toBeNull()
  })
})

test.describe('nested routes on static hosting', () => {
  test('record routes load directly, and an unknown id still resolves', async ({ context }) => {
    // Pre-rendered record documents answer a direct request with their own HTML.
    const record = await open(context, '/assignments/example')
    expect(await record.content()).toContain('Checking your session')
    await expect(record).toHaveURL(/\/sign-in\/?$/, { timeout: 20_000 })

    // An id that has no pre-rendered document falls back to the site document;
    // the client router then resolves the real URL instead of showing a 404.
    const unknown = await open(context, '/submissions/revision-0042')
    await expect(unknown).toHaveURL(/\/sign-in\/?$/, { timeout: 20_000 })
  })

  test('app routes are pre-rendered as HTML rather than served as a 404', async ({
    context,
  }) => {
    const page = await open(context, '/dashboard/')
    // A pre-rendered document exists for the route, so the server answers 200 and
    // the client guard then forwards the visitor to sign-in.
    await expect(page).toHaveURL(/\/sign-in\/?$/, { timeout: 20_000 })
    const html = await page.request.get('/dashboard')
    expect(html.status()).toBe(200)
    expect(await html.text()).toContain('Checking your session')
  })
})
