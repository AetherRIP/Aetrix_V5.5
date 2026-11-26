import { expect, test } from './support/fixtures'
import type { Page } from '@playwright/test'

/**
 * The Gemini fleet screen renders one Aetrix pool per API key, keeps Google
 * quota at project level, and separates the three primary correction models from
 * the independent verification model.
 *
 * Every response here is intercepted, so the spec states the engine's answer
 * explicitly, spends no provider quota and never needs a real credential.
 */

const KEY_A = {
  id: 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa',
  pool_id: 'gemini-key-aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa',
  contributor_id: null,
  contributor_name: null,
  revoked_at: null,
  project_id: 'shared-project',
  account_label: 'USER_ADDED · API_KEYS.txt · ****AAAA',
  key_fingerprint: 'fingerprint-aaaa1111',
  auth_type: 'api_key',
  tier: 'UNKNOWN',
  health: 'HEALTHY',
  operational_status: 'OPERATIONAL',
  project_verification: 'PROJECT_IDENTITY_UNVERIFIED',
  enabled: true,
  routable: true,
  google_quota_status: 'UNKNOWN',
  quarantined: false,
  quarantine_kind: 'NONE',
  quarantine_until: null,
  quarantine_reason: null,
  remaining_today: 40,
  remaining_minute: 9,
  reservations_today: 1,
  reservations_minute: 0,
  validations_today: 0,
  consecutive_failures: 0,
  model_access: ['gemini-3.6-flash', 'gemini-3.8-flash'],
  cooldown_until: null,
  last_success_at: '2026-11-25T10:00:00Z',
  last_failure_at: null,
  last_failure_status: null,
  last_validated_at: '2026-11-25T09:00:00Z',
  last_error: null,
  requests: 20,
  input_tokens: 1000,
  output_tokens: 200,
  failures: 2,
  quota_failures: 0,
}

const KEY_B = {
  ...KEY_A,
  id: 'bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb',
  pool_id: 'gemini-key-bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb',
  account_label: 'USER_ADDED · API_KEYS.txt · ****BBBB',
  key_fingerprint: 'fingerprint-bbbb2222',
  remaining_today: 12,
  consecutive_failures: 3,
  health: 'INVALID',
  quarantined: true,
  quarantine_kind: 'AUTH',
  quarantine_until: '2026-11-26T10:00:00Z',
  model_access: ['gemini-3.1-flash-lite'],
  requests: 5,
  failures: 5,
}

const KEY_C = {
  ...KEY_A,
  id: 'cccccccc-3333-4333-8333-cccccccccccc',
  pool_id: 'gemini-key-cccccccc-3333-4333-8333-cccccccccccc',
  project_id: 'other-project',
  account_label: 'USER_ADDED · API_KEYS.txt · ****CCCC',
  key_fingerprint: 'fingerprint-cccc3333',
  model_access: ['gemini-3.5-flash-lite'],
}

const PRIMARY = [
  { model_id: 'gemini-4-hydrogen', display_name: 'Gemini 4 Hydrogen', role: 'primary', priority: 1 },
  { model_id: 'gemini-3.8-flash', display_name: 'Gemini 3.8 Flash', role: 'primary', priority: 2 },
  { model_id: 'gemini-3.6-flash', display_name: 'Gemini 3.6 Flash', role: 'primary', priority: 3 },
].map((model) => ({
  ...model,
  stability: 'stable',
  context_limit: 1048576,
  max_output: 65536,
  pdf_input: true,
  image_input: true,
  structured_outputs: true,
  thinking: true,
  free_tier: true,
  free_tier_used_for_product_improvement: true,
  retirement_date: null,
  source_url: 'https://ai.google.dev/gemini-api/docs/models',
  verified_on: '2026-11-25',
  notes: '',
}))

const CHECKER = {
  model_id: 'gemini-3.5-flash-lite',
  display_name: 'Gemini 3.5 Flash-Lite',
  role: 'evidence_checker',
  priority: 4,
  stability: 'stable',
  context_limit: 1048576,
  max_output: 65536,
  pdf_input: true,
  image_input: true,
  structured_outputs: true,
  thinking: false,
  free_tier: true,
  free_tier_used_for_product_improvement: true,
  retirement_date: null,
  source_url: 'https://ai.google.dev/gemini-api/docs/models',
  verified_on: '2026-11-25',
  notes: '',
}

const OVERVIEW = {
  keys_total: 3,
  keys_by_health: { HEALTHY: 2, INVALID: 1 },
  projects: 2,
  declared_projects: 2,
  verified_projects: 0,
  project_verification: 'OPERATOR_DECLARED',
  credential_pools: 3,
  pools_available: 2,
  pools_quarantined: 1,
  attempted_today: 25,
  requests_today: 25,
  successful_today: 18,
  failures_today: 7,
  input_tokens_today: 3000,
  output_tokens_today: 600,
  error_rate_today: 0.28,
  operational_status: 'DEGRADED',
  observed_at: '2026-11-25T11:00:00Z',
  day_started_at: '2026-11-25T00:00:00Z',
  reset_at: '2026-11-26T00:00:00Z',
  reset_timezone: 'UTC',
  projects_detail: [
    {
      project_id: 'shared-project',
      keys: 2,
      healthy: 1,
      disabled: 0,
      invalid: 1,
      pools: 2,
      routable_keys: 1,
      estimates: [],
      cooldown_until: null,
    },
    {
      project_id: 'other-project',
      keys: 1,
      healthy: 1,
      disabled: 0,
      invalid: 0,
      pools: 1,
      routable_keys: 1,
      estimates: [],
      cooldown_until: null,
    },
  ],
  model_registry: {
    verified_on: '2026-11-25',
    primary_models: PRIMARY,
    checker_models: [CHECKER],
    marking_excluded: [],
    retiring: [],
    sources: {},
  },
  model_scheduler: {
    enabled: false,
    would_choose: 'gemini-3.6-flash',
    reason: 'The scheduler is off; every paper uses the configured marking model.',
    candidates: [],
  },
}

const MODELS = {
  discovered_at: '2026-11-25T11:00:00Z',
  cached: false,
  ttl_seconds: 3600,
  projects: [{ project_id: 'shared-project', ok: true, models: 3, error: null, credential_fingerprint: 'fingerprint-aaaa1111' }],
  models: [],
  selections: { primary: 'gemini-3.6-flash', review: 'gemini-3.5-flash-lite', lightweight: 'gemini-3.1-flash-lite' },
  selection_sources: { primary: 'database', review: 'settings', lightweight: 'settings' },
  marking_policy: {
    marking_model: 'gemini-3.6-flash',
    disabled_models: ['gemini-3.1-flash-lite', 'gemini-3.5-flash-lite'],
    primary_chain: ['gemini-3.6-flash'],
    enforced: true,
    note: 'Only the configured marking model may mark a paper.',
  },
  note: 'Discovery is cached per project and key.',
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

async function open(page: Page) {
  await signIn(page)
  // The stored session is synthetic: answer Supabase's own session endpoints so
  // the shell does not wait on a token refresh it cannot complete.
  await page.route('**/auth/v1/**', (route) => {
    const url = route.request().url()
    const user = {
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      role: 'authenticated',
      email: 'owner@aetrix.test',
      email_confirmed_at: '2026-11-01T00:00:00Z',
      app_metadata: { provider: 'google', aetrix_role: 'owner' },
      user_metadata: { full_name: 'Rudro Pratihar' },
      identities: [],
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        url.includes('/user')
          ? { user }
          : {
              access_token: 'test-access-token',
              token_type: 'bearer',
              expires_in: 3600,
              expires_at: 4102444800,
              refresh_token: 'test-refresh-token',
              user,
            },
      ),
    })
  })

  // Every engine read the shell makes is answered here, so the spec is
  // hermetic instead of waiting on a development engine origin.
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const url = request.url()
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    const empty = { items: [], total: 0, unread: 0, read: 0, has_more: false }

    if (url.includes('/admin/providers/keys')) return json({ items: [KEY_A, KEY_B, KEY_C], total: 3, limit: 200, offset: 0 })
    if (url.includes('/admin/providers/overview')) return json(OVERVIEW)
    if (url.includes('/admin/providers/models')) return json(MODELS)
    if (url.includes('/admin/providers/alerts')) return json([])
    if (/\/api\/v1\/me(\?|$)/.test(url)) {
      return json({
        user_id: '00000000-0000-4000-8000-000000000001',
        subject: '00000000-0000-4000-8000-000000000001',
        email: 'owner@aetrix.test',
        display_name: 'Rudro Pratihar',
        tenant_id: '00000000-0000-4000-8000-000000000002',
        workspace_name: 'Signed-in workspace',
        workspace_slug: 'signed-in',
        role: 'PLATFORM_OWNER',
        ui_role: 'owner',
        capabilities: ['platform_admin', 'platform.allocations.manage'],
        is_platform_admin: true,
        is_demo: false,
      })
    }
    if (url.includes('/messaging/')) return json([])
    return json([])
  })

  const response = await page.goto('/platform/gemini', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('tab', { name: 'Overview' })).toBeVisible()
}

test.describe('gemini fleet pools and model architecture', () => {
  test('every API key is its own pool tile, with its own state', async ({ page }) => {
    await open(page)
    await page.getByRole('tab', { name: 'API keys' }).click()

    const pools = page.locator('.gem-pool')
    await expect(pools).toHaveCount(3)
    await expect(page.getByText(KEY_A.pool_id, { exact: true })).toBeVisible()
    await expect(page.getByText(KEY_B.pool_id, { exact: true })).toBeVisible()
    await expect(page.getByText(KEY_C.pool_id, { exact: true })).toBeVisible()
    await expect(page.getByText('fingerprint-aaaa1111')).toBeVisible()
    await expect(page.getByText('QUARANTINED', { exact: true })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('AIza')
  })

  test('two keys in one project are two pools and stay grouped under that project', async ({ page }) => {
    await open(page)
    await page.getByRole('tab', { name: 'API keys' }).click()
    await expect(page.locator('.gem-pool')).toHaveCount(3)

    await page.getByRole('tab', { name: 'Projects' }).click()
    const shared = page.locator('.app-card').filter({ hasText: 'shared-project' }).first()
    await expect(shared.getByText('fingerprint-aaaa1111')).toBeVisible()
    await expect(shared.getByText('fingerprint-bbbb2222')).toBeVisible()
    await expect(shared.getByText('Individual Aetrix pools under this project label')).toBeVisible()

    const other = page.locator('.app-card').filter({ hasText: 'other-project' }).first()
    await expect(other.getByText('fingerprint-cccc3333')).toBeVisible()
    await expect(other.getByText('fingerprint-aaaa1111')).toHaveCount(0)
  })

  test('primary models 1-3 and the independent checker are separate groups', async ({ page }) => {
    await open(page)

    const primary = page.getByRole('region', { name: 'Primary correction models' })
    await expect(primary.getByText('gemini-4-hydrogen')).toBeVisible()
    await expect(primary.getByText('gemini-3.8-flash')).toBeVisible()
    await expect(primary.getByText('gemini-3.6-flash')).toBeVisible()

    const checker = page.getByRole('region', { name: 'Independent verification model' })
    await expect(checker.getByText('gemini-3.5-flash-lite')).toBeVisible()

    // The checker must not be presented inside the primary group.
    await expect(primary.getByText('gemini-3.5-flash-lite')).toHaveCount(0)
  })

  test('the header and KPI cards report pools and projects, not a combined Google quota', async ({ page }) => {
    await open(page)

    const header = page.locator('.gem-head__facts')
    await expect(header).toContainText('3 registered keys')
    await expect(header).toContainText('3 individual pools')
    await expect(header).toContainText('2 Google projects')
    await expect(page.locator('.gem-kpi')).toContainText('Quarantined pools')
    await expect(page.locator('.gem-kpi')).toContainText('1')
  })
})
