import { expect, test, type Page } from '@playwright/test'

/**
 * The Validate action on the Gemini fleet screen.
 *
 * The reported defect: every credential showed FAILED with no explanation. The
 * engine now answers with the probe's health, category, HTTP status, model and
 * an operator action, and this suite checks that all of it reaches the screen —
 * and that the key itself never does.
 *
 * The fleet API is intercepted, so these tests state the engine's answer
 * explicitly instead of spending real Gemini quota.
 */

const KEY = {
  id: 'cred-0000',
  contributor_id: null,
  contributor_name: null,
  revoked_at: null,
  project_id: 'user-downloads-pool',
  account_label: 'USER_ADDED · API_KEYS.txt · ****0XFw861c948ba49ed56b',
  key_fingerprint: '****0XFw861c948ba49ed56b',
  auth_type: 'api_key',
  tier: 'UNKNOWN',
  health: 'UNKNOWN',
  model_access: ['gemini-3.6-flash'],
  cooldown_until: null,
  last_success_at: '2026-11-09T17:24:00Z',
  last_failure_at: '2026-11-10T17:28:00Z',
  last_failure_status: null,
  last_validated_at: null,
  last_error: 'ProviderResponseError: The provider returned no content parts.',
  requests: 14,
  input_tokens: 0,
  output_tokens: 0,
  failures: 3,
  quota_failures: 0,
}

const ANSWER = {
  credential_id: KEY.id,
  health: 'HEALTHY',
  valid: true,
  detail: null,
  category: 'ok',
  http_status: 200,
  model: 'gemini-3.6-flash',
  checked_at: '2026-11-10T18:05:00Z',
  provider_message: null,
  recommendation: null,
  latency_ms: 412,
  key_fingerprint: KEY.key_fingerprint,
  project_id: KEY.project_id,
  account_label: KEY.account_label,
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
  keys_by_health: { UNKNOWN: 1 },
  projects: 1,
  requests_today: 14,
  input_tokens_today: 0,
  output_tokens_today: 0,
  failures_today: 3,
  error_rate_today: null,
  observed_at: '2026-11-10T18:00:00Z',
  day_started_at: '2026-11-10T08:00:00Z',
  reset_at: '2026-11-11T08:00:00Z',
  projects_detail: [],
}

/** Serves the fleet endpoints, with ``answer`` returned by the validate route. */
async function open(page: Page, answer: Record<string, unknown>) {
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

    if (request.method() === 'POST' && url.endsWith('/validate')) return json(answer)
    if (url.includes('/overview')) return json(OVERVIEW)
    if (url.includes('/keys')) {
      return json({ items: [KEY], total: 1, limit: 50, offset: 0 })
    }
    return json([])
  })

  const response = await page.goto('/platform/gemini', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await page.getByText('API keys', { exact: true }).first().click()
  const row = page.locator('.gem-table tbody tr').first()
  await expect(row).toContainText(KEY.key_fingerprint)
  return row
}

function stat(page: Page, label: string) {
  return page.locator('.gem-stat').filter({ hasText: label })
}

test.describe('credential validation', () => {
  test('a successful probe shows the model, status and tested credential', async ({ page }) => {
    const row = await open(page, ANSWER)

    await row.getByRole('button', { name: 'Validate' }).click()

    await expect(page.getByText('Validation passed')).toBeVisible()
    await expect(stat(page, 'Health')).toContainText('HEALTHY')
    await expect(stat(page, 'Health')).toContainText('No problem found')
    await expect(stat(page, 'HTTP status')).toContainText('200')
    await expect(stat(page, 'HTTP status')).toContainText('gemini-3.6-flash')
    await expect(stat(page, 'Credential')).toContainText(KEY.key_fingerprint)
    await expect(page.locator('body')).not.toContainText('AIza')
  })

  test('a rejected key names authentication and the corrective action', async ({ page }) => {
    const row = await open(page, {
      ...ANSWER,
      health: 'INVALID',
      valid: false,
      detail: 'ProviderAuthenticationError: Google rejected this API key.',
      category: 'authentication',
      http_status: 401,
      provider_message: 'API key not valid. Please pass a valid API key.',
      recommendation:
        'Google rejected this key. Confirm the Generative Language API is enabled for the project and that the key is not revoked or restricted, then rotate it.',
      latency_ms: null,
    })

    await row.getByRole('button', { name: 'Validate' }).click()

    await expect(page.getByText('Validation failed')).toBeVisible()
    await expect(stat(page, 'Health')).toContainText('INVALID')
    await expect(stat(page, 'Health')).toContainText('Authentication')
    await expect(stat(page, 'HTTP status')).toContainText('401')
    await expect(page.getByText('API key not valid', { exact: false })).toBeVisible()
    await expect(page.getByText('then rotate it', { exact: false })).toBeVisible()
    // A generic FAILED with no reason is exactly what this replaced.
    await expect(page.locator('body')).not.toContainText('AIza')
  })

  test('a throttled project is reported as quota, not an unhealthy key', async ({ page }) => {
    const row = await open(page, {
      ...ANSWER,
      health: 'UNKNOWN',
      operational_status: 'RATE_LIMITED',
      valid: false,
      detail: 'ProviderQuotaError: Quota exceeded.',
      category: 'quota',
      http_status: 429,
      provider_message: 'Quota exceeded for quota metric generate_content_free_tier_requests.',
      recommendation:
        'The project is rate-limited or out of quota. Wait for the window to reset or raise the limit; retrying the same key now cannot succeed.',
      latency_ms: null,
    })

    await row.getByRole('button', { name: 'Validate' }).click()

    await expect(page.getByText('Validation failed')).toBeVisible()
    await expect(stat(page, 'Health')).toContainText('UNKNOWN')
    await expect(stat(page, 'Operational')).toContainText('RATE LIMITED')
    await expect(stat(page, 'Operational')).toContainText('Quota or rate limit')
    await expect(page.getByText('Wait for the window to reset', { exact: false })).toBeVisible()
  })
})
