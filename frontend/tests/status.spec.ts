import { expect, test, type BrowserContext, type Page } from '@playwright/test'

/**
 * Engine status.
 *
 * The reported defect: screens said "Awaits the engine" while the backend was
 * connected. Two causes are pinned here — a static note shown for every non-ok
 * read, and status cards that were never wired to the engine at all.
 *
 * `/status` is intercepted, so each test states the engine's answer explicitly
 * rather than depending on a live deployment.
 */

async function signIn(page: Page) {
  const now = Math.floor(Date.now() / 1000)
  const payload = {
    access_token: 'test-access-token',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: 4102444800,
    refresh_token: 'test-refresh-token',
    user: {
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      role: 'authenticated',
      email: 'owner@aetrix.test',
      email_confirmed_at: new Date(now * 1000).toISOString(),
      phone: '',
      confirmed_at: new Date(now * 1000).toISOString(),
      last_sign_in_at: new Date(now * 1000).toISOString(),
      app_metadata: { provider: 'google', aetrix_role: 'owner' },
      user_metadata: { full_name: 'Rudro Pratihar', name: 'Rudro Pratihar' },
      identities: [],
      created_at: new Date(now * 1000).toISOString(),
      updated_at: new Date(now * 1000).toISOString(),
    },
  }

  await page.addInitScript((value) => {
    window.localStorage.setItem('aetrix:auth', JSON.stringify(value))
  }, payload)
}

const SYSTEM_STATUS = {
  checked_at: '2026-11-10T10:00:00Z',
  service: 'aetrix-engine',
  version: '5.5.0',
  environment: 'development',
  api: { state: 'ok', summary: 'The API answered this request', detail: 'aetrix-engine 5.5.0' },
  engine: { state: 'ok', summary: 'The correction engine responded', detail: null },
  readiness: {
    state: 'ok',
    summary: 'Initialised and accepting correction jobs',
    detail: 'Marking is not implemented: an accepted job parks at PIPELINE_UNAVAILABLE.',
  },
  database: { state: 'ok', summary: 'PostgreSQL answered a readiness query', detail: null },
  worker: {
    state: 'ok',
    summary: 'The worker process is renewing its heartbeat',
    detail: 'Last heartbeat 3s ago; the grace window is 60s.',
  },
  provider: {
    state: 'unknown',
    summary: 'Live provider calls are enabled but unverified',
    detail: null,
  },
  components: [
    {
      name: 'HTTP API',
      deployment: 'deployed',
      operational: 'available',
      readiness: 'ready',
      checked_at: '2026-11-10T10:00:00Z',
      last_success_at: '2026-11-10T10:00:00Z',
      last_failure_at: null,
      last_failure: null,
      diagnostic: 'aetrix-engine 5.5.0 answered this status request.',
    },
    {
      name: 'PostgreSQL',
      deployment: 'deployed',
      operational: 'available',
      readiness: 'ready',
      checked_at: '2026-11-10T10:00:00Z',
      last_success_at: '2026-11-10T10:00:00Z',
      last_failure_at: null,
      last_failure: null,
      diagnostic: 'The readiness query SELECT 1 succeeded.',
    },
    {
      name: 'Background worker',
      deployment: 'deployed',
      operational: 'available',
      readiness: 'not_ready',
      checked_at: '2026-11-10T10:00:00Z',
      last_success_at: '2026-11-10T10:00:00Z',
      last_failure_at: null,
      last_failure: null,
      diagnostic:
        'Last heartbeat 3s ago (grace 60s). No runnable job is queued. The marking pipeline is a stub, so a claimed job parks at PIPELINE_UNAVAILABLE.',
    },
    {
      name: 'AI provider',
      deployment: 'deployed',
      operational: 'unverified',
      readiness: 'not_ready',
      checked_at: '2026-11-10T10:00:00Z',
      last_success_at: null,
      last_failure_at: null,
      last_failure: null,
      diagnostic:
        'Credentials are configured, but no live call has been recorded yet; availability is not claimed.',
    },
  ],
  features: [
    { name: 'Marking', state: 'not_implemented', reason: 'A job validates and then parks.' },
    { name: 'Cohort intelligence', state: 'not_implemented', reason: 'Analytics needs marks.' },
  ],
}

async function open(context: BrowserContext, path: string) {
  const page = await context.newPage()
  await signIn(page)
  await page.route('**/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SYSTEM_STATUS),
    }),
  )
  const response = await page.goto(path, { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  return page
}

function row(page: Page, label: string) {
  return page.locator('.hub-stat').filter({ hasText: label })
}

test.describe('engine status', () => {
  test('reports a connected backend without the awaited-engine wording', async ({ context }) => {
    const page = await open(context, '/platform/health')

    await expect(row(page, 'API')).toContainText('Connected')
    await expect(row(page, 'Correction engine')).toContainText('Online')
    await expect(row(page, 'Worker')).toContainText('Online')
    await expect(row(page, 'Database')).toContainText('Connected')
    // A configured provider is never upgraded to "available": it was not called.
    await expect(row(page, 'Provider')).toContainText('Unknown')

    // The component table reports deployment separately from operation, so a
    // running worker is never shown as "Not deployed".
    const workerRow = page.locator('tbody tr').filter({ hasText: 'Background worker' })
    await expect(workerRow).toContainText('Deployed')
    await expect(workerRow).toContainText('Available')
    await expect(workerRow).toContainText('Not ready')
    await expect(workerRow).not.toContainText('Not deployed')

    const providerRow = page.locator('tbody tr').filter({ hasText: 'AI provider' })
    await expect(providerRow).toContainText('Unverified')
    await expect(providerRow).not.toContainText('Available')

    await expect(page.getByText('Marking', { exact: true })).toBeVisible()
    await expect(page.getByText('Not implemented').first()).toBeVisible()
    await expect(page.locator('body')).not.toContainText('Awaits the engine')
  })

  test('a failed status read fabricates nothing', async ({ context }) => {
    const page = await context.newPage()
    await signIn(page)
    await page.route('**/status', (route) =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'SERVICE_NOT_READY', message: 'The database is not reachable.' },
        }),
      }),
    )
    const response = await page.goto('/platform/health', { waitUntil: 'load' })
    expect(response?.status()).toBe(200)

    await expect(row(page, 'API')).toContainText('Unknown')
    await expect(row(page, 'Worker')).toContainText('Unknown')
    await expect(page.locator('body')).not.toContainText('Connected')
    await expect(page.locator('body')).not.toContainText('Awaits the engine')
  })

  test('the platform dashboard reads the engine instead of a static list', async ({ context }) => {
    const page = await open(context, '/platform')

    await expect(row(page, 'API')).toContainText('Connected')
    await expect(row(page, 'Worker')).toContainText('Online')
    await expect(page.locator('body')).not.toContainText('Awaits the engine')
    // The platform figures now come from a real aggregate endpoint; the old
    // "no platform endpoint" copy must not survive the change.
    await expect(page.locator('body')).not.toContainText('no platform endpoint')
    await expect(page.getByRole('heading', { name: 'Platform overview' })).toBeVisible()
  })

  test('a section names the real failure rather than awaiting an engine', async ({ context }) => {
    const page = await context.newPage()
    await signIn(page)
    await page.route('**/api/v1/admin/providers/**', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'UNAUTHENTICATED', message: 'The bearer token is invalid or has expired.' },
        }),
      }),
    )
    await page.goto('/platform/gemini', { waitUntil: 'load' })

    await expect(page.locator('.app-card__note').filter({ hasText: 'Unavailable (401)' }).first()).toBeVisible()
    await expect(page.locator('body')).not.toContainText('Awaits the engine')
  })

  test('an unimplemented feature is labelled, not blamed on the engine', async ({ context }) => {
    const page = await open(context, '/analytics')

    await expect(page.getByText('Not implemented', { exact: true }).first()).toBeVisible()
    await expect(page.locator('body')).not.toContainText('Awaits the engine')
  })
})
