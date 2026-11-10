import { expect, test, type Page } from '@playwright/test'

/**
 * The model catalogue screen.
 *
 * The defect this replaces: two hardcoded model names and no way to see what a
 * credential can actually reach. The catalogue is intercepted here, so each test
 * states Google's answer explicitly and spends no quota.
 */

const CATALOGUE = {
  discovered_at: '2026-11-10T16:20:00Z',
  cached: false,
  ttl_seconds: 3600,
  projects: [
    { project_id: 'user-downloads-pool', ok: true, models: 62, error: null },
  ],
  models: [
    {
      id: 'gemini-3.8-flash',
      display_name: 'Gemini 3.8 Flash',
      description: 'Most intelligent Flash model.',
      status: 'stable',
      status_detail: null,
      supports_generate: true,
      input_token_limit: 1048576,
      output_token_limit: 65536,
      capabilities: {
        structured_outputs: null,
        thinking: null,
        documented_inputs: ['text', 'image', 'video', 'audio', 'pdf'],
        source: 'ai.google.dev Gemini model pages, read 2026-11-10',
      },
      input_usd_per_million: 0.75,
      output_usd_per_million: 3.75,
      projects: [{ project_id: 'user-downloads-pool', available: true }],
    },
    {
      id: 'gemini-3.1-pro-preview',
      display_name: 'Gemini 3.1 Pro Preview',
      description: null,
      status: 'preview',
      status_detail: null,
      supports_generate: true,
      input_token_limit: 1048576,
      output_token_limit: 65536,
      capabilities: {
        structured_outputs: null,
        thinking: null,
        documented_inputs: null,
        source: null,
      },
      input_usd_per_million: 2,
      output_usd_per_million: 12,
      projects: [{ project_id: 'user-downloads-pool', available: true }],
    },
    {
      id: 'gemini-2.5-flash-image',
      display_name: 'Nano Banana',
      description: null,
      status: 'unsupported',
      status_detail: "Specialised 'image' endpoint; not a general correction model.",
      supports_generate: true,
      input_token_limit: 32768,
      output_token_limit: 32768,
      capabilities: {
        structured_outputs: null,
        thinking: null,
        documented_inputs: null,
        source: null,
      },
      input_usd_per_million: null,
      output_usd_per_million: null,
      projects: [{ project_id: 'user-downloads-pool', available: true }],
    },
  ],
  selections: {
    primary: 'gemini-3.6-flash',
    review: 'gemini-3.1-pro-preview',
    lightweight: 'gemini-3.1-flash-lite',
  },
  selection_sources: {
    primary: 'settings',
    review: 'settings',
    lightweight: 'settings',
  },
  note: 'Availability is read from models.list with one key per Google Cloud project.',
}

const ANSWER = {
  credential_id: 'cred-0000',
  health: 'HEALTHY',
  valid: true,
  detail: null,
  category: 'ok',
  http_status: 200,
  model: 'gemini-3.8-flash',
  checked_at: '2026-11-10T16:25:00Z',
  provider_message: null,
  recommendation: null,
  latency_ms: 980,
  key_fingerprint: '****0XFw861c948ba49ed56b',
  project_id: 'user-downloads-pool',
  account_label: 'USER_ADDED · API_KEYS.txt · ****0XFw861c948ba49ed56b',
}

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

const OVERVIEW = {
  keys_total: 1,
  keys_by_health: { HEALTHY: 1 },
  projects: 1,
  requests_today: 0,
  input_tokens_today: 0,
  output_tokens_today: 0,
  failures_today: 0,
  error_rate_today: null,
  observed_at: '2026-11-10T16:20:00Z',
  day_started_at: '2026-11-10T08:00:00Z',
  reset_at: '2026-11-11T08:00:00Z',
  projects_detail: [],
}

async function open(page: Page, catalogue: unknown = CATALOGUE) {
  const seen: { selection: unknown; tested: string | null } = {
    selection: null,
    tested: null,
  }
  await signIn(page)
  await page.route('**/api/v1/admin/providers/**', (route) => {
    const request = route.request()
    const url = request.url()
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      })

    if (request.method() === 'PUT' && url.includes('/models/selection/')) {
      seen.selection = request.postDataJSON()
      return json({
        role: 'primary',
        model: (seen.selection as { model: string }).model,
        updated_at: '2026-11-10T16:22:00Z',
        updated_by: 'user-1',
      })
    }
    if (request.method() === 'POST' && url.includes('/test')) {
      seen.tested = decodeURIComponent(url.split('/models/')[1].split('/test')[0])
      return json(ANSWER)
    }
    if (url.includes('/models')) return json(catalogue)
    if (url.includes('/overview')) return json(OVERVIEW)
    return json([])
  })

  const response = await page.goto('/platform/gemini', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await page.getByRole('tab', { name: 'Models' }).click()
  return seen
}

test.describe('model catalogue', () => {
  test('lists exact ids, preview status and excludes specialised endpoints', async ({ page }) => {
    await open(page)

    const table = page.locator('.gem-table tbody')
    await expect(table.getByText('gemini-3.8-flash', { exact: true })).toBeVisible()
    await expect(table.getByText('gemini-3.1-pro-preview', { exact: true })).toBeVisible()
    await expect(table.getByText('preview', { exact: true })).toBeVisible()
    await expect(page.getByText('excluded from correction')).toBeVisible()
    await expect(page.getByText('discovery ok')).toBeVisible()
    await expect(page.getByText('$0.75 in / $3.75 out per 1M')).toBeVisible()
    await expect(page.locator('body')).not.toContainText('AIza')
  })

  test('saving a role persists the exact model and testing shows the probe result', async ({ page }) => {
    const seen = await open(page)

    await page.locator('.gem-roles select').first().selectOption('gemini-3.8-flash')
    await expect
      .poll(() => seen.selection)
      .toEqual({ model: 'gemini-3.8-flash' })
    await expect(page.getByText('Primary correction now uses gemini-3.8-flash')).toBeVisible()

    const row = page.locator('.gem-table tbody tr').filter({ hasText: 'gemini-3.8-flash' })
    await row.getByRole('button', { name: 'Test' }).click()

    await expect.poll(() => seen.tested).toBe('gemini-3.8-flash')
    await expect(page.getByText('Validation passed')).toBeVisible()
    await expect(page.locator('.gem-stat').filter({ hasText: 'HTTP status' })).toContainText('200')
  })

  test('a failed discovery is named instead of showing an empty catalogue', async ({ page }) => {
    await open(page, {
      ...CATALOGUE,
      models: [],
      projects: [
        {
          project_id: 'user-downloads-pool',
          ok: false,
          models: 0,
          error: 'ProviderAuthenticationError: The provider rejected the credential.',
        },
      ],
    })

    await expect(page.getByText('discovery failed')).toBeVisible()
    await expect(page.getByText('The provider rejected the credential', { exact: false })).toBeVisible()
    await expect(page.getByText('0 listed')).toBeVisible()
  })
})
