import { expect, test } from './support/fixtures'
import type { Page } from '@playwright/test'

const OWNER_ID = '00000000-0000-4000-8000-000000000001'
const TENANT_ID = '00000000-0000-4000-8000-000000000010'

const BASE_MODEL = {
  provider: 'Google',
  description: null,
  input_modalities: [],
  output_modalities: ['text'],
  context_window: null,
  max_output_tokens: null,
  supported_generation_methods: ['generateContent'],
  supports_generate: true,
  capabilities: {},
  capability_source: 'operator inventory',
  source_url: 'https://ai.google.dev/gemini-api/docs/models',
  replacement_model_id: null,
  pricing: { input_usd_per_million: null, output_usd_per_million: null },
  quota: {
    rpm_limit: 5,
    rpm_used: 2,
    rpm_unlimited: false,
    tpm_limit: 250000,
    tpm_used: 5510,
    tpm_unlimited: false,
    rpd_limit: 20,
    rpd_used: 23,
    rpd_unlimited: false,
    limits_provided: true,
    source: 'Google AI Studio operator snapshot',
    imported_at: '2026-11-10T00:00:00Z',
    observation_time_supplied: false,
    inconsistencies: ['RPD used 23 exceeds the supplied limit 20.'],
  },
}

const INVENTORY = {
  imported_at: '2026-11-10T00:00:00Z',
  models: [
    {
      ...BASE_MODEL,
      key: 'gemini-3.6-flash',
      display_name: 'Gemini 3.6 Flash',
      api_model_id: 'gemini-3.6-flash',
      supplied_api_id: null,
      id_status: 'VERIFIED',
      family: 'Gemini 3.6',
      version: '3.6',
      category: 'TEXT_OUT',
      lifecycle: 'STABLE',
      catalogue_state: 'REGISTERED',
      workloads: ['mathematics_marking', 'document_extraction'],
      availability: 'NOT_TESTED',
      limitations: ['RPD used 23 exceeds the supplied limit 20.'],
    },
    {
      ...BASE_MODEL,
      key: 'gemini-omni-1.2-flash',
      display_name: 'Gemini Omni 1.2 Flash',
      api_model_id: null,
      supplied_api_id: null,
      id_status: 'UNVERIFIED',
      family: 'Gemini Omni',
      version: '1.2 Flash',
      category: 'MULTIMODAL',
      lifecycle: 'UNKNOWN',
      catalogue_state: 'METADATA_INCOMPLETE',
      workloads: ['document_extraction', 'other'],
      availability: 'NOT_TESTED',
      limitations: ['No official API model ID was verified; do not send a guessed identifier.'],
    },
    {
      ...BASE_MODEL,
      key: 'nano-banana-pro',
      display_name: 'Nano Banana Pro',
      api_model_id: 'gemini-3-pro-image',
      supplied_api_id: null,
      id_status: 'VERIFIED',
      family: 'Nano Banana',
      version: '3 Pro',
      category: 'IMAGE_GENERATION',
      lifecycle: 'STABLE',
      catalogue_state: 'REGISTERED',
      workloads: ['image_generation'],
      availability: 'NOT_TESTED',
      limitations: [],
    },
  ],
  counts: {
    total: 3,
    by_category: { TEXT_OUT: 1, MULTIMODAL: 1, IMAGE_GENERATION: 1 },
    by_lifecycle: { STABLE: 2, UNKNOWN: 1 },
    by_workload: {
      mathematics_marking: 1,
      document_extraction: 2,
      image_generation: 1,
      audio_processing: 0,
      transcription: 0,
      embeddings: 0,
      agent_workflows: 0,
      other: 1,
    },
    by_availability: { AVAILABLE: 0, UNAVAILABLE: 0, NOT_TESTED: 3 },
    verified_api_ids: 2,
    corrected_api_ids: 0,
    unverified_api_ids: 1,
    math_marking_candidates: 1,
    quota_records: 3,
    quota_records_with_usage: 3,
    quota_inconsistencies: 3,
  },
  selections: {
    primary: 'gemini-3.6-flash',
    review: 'gemini-3.1-pro-preview',
    lightweight: 'gemini-3.1-flash-lite',
  },
  selection_sources: {
    primary: 'database',
    review: 'settings',
    lightweight: 'settings',
  },
  note: 'The inventory is configuration-backed and registered independently of project availability.',
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

async function signIn(page: Page) {
  const now = Math.floor(Date.now() / 1000)
  await page.addInitScript(
    (value) => {
      window.localStorage.setItem('aetrix:auth', JSON.stringify(value))
    },
    {
      access_token: 'test-access-token',
      token_type: 'bearer',
      expires_in: 3600,
      expires_at: 4102444800,
      refresh_token: 'test-refresh-token',
      user: {
        id: OWNER_ID,
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
    },
  )
}

async function open(page: Page) {
  const seen: { selection: unknown } = { selection: null }
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
    if (url.includes('/models/inventory')) return json(INVENTORY)
    if (url.includes('/overview')) return json(OVERVIEW)
    return json([])
  })

  const response = await page.goto('/platform/gemini', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await page.getByRole('tab', { name: 'Model catalogue' }).click()
  return seen
}

test.describe('model inventory', () => {
  test('shows the complete registered inventory and preserves a quota inconsistency', async ({
    page,
  }) => {
    await open(page)

    await expect(page.getByText('Operator catalogue')).toBeVisible()
    await expect(page.getByText('Gemini 3.6 Flash')).toBeVisible()
    await expect(page.getByText('Gemini Omni 1.2 Flash')).toBeVisible()
    await expect(page.getByText('Nano Banana Pro')).toBeVisible()
    await expect(page.getByText('RPD used 23 exceeds the supplied limit 20.').first()).toBeVisible()
    await expect(page.getByText('no verified API ID')).toBeVisible()
    await expect(page.getByText('unverified', { exact: true })).toBeVisible()
  })

  test('filters by workload and saves a correction role through the existing endpoint', async ({
    page,
  }) => {
    const seen = await open(page)

    await page.getByLabel('Workload').selectOption('mathematics_marking')
    await expect(page.getByText('Gemini 3.6 Flash')).toBeVisible()
    await expect(page.getByText('Nano Banana Pro')).toHaveCount(0)

    await page.getByLabel('Workload').selectOption('all')
    await page.getByLabel('Lifecycle').selectOption('STABLE')
    await expect(page.getByText('Gemini 3.6 Flash')).toBeVisible()
    await expect(page.getByText('Gemini Omni 1.2 Flash')).toHaveCount(0)
    await page.getByLabel('Lifecycle').selectOption('all')
    const row = page.locator('tbody tr').filter({ hasText: 'Gemini 3.6 Flash' })
    await row.getByRole('button', { name: 'Primary' }).click()

    await expect.poll(() => seen.selection).toEqual({ model: 'gemini-3.6-flash' })
    await expect(page.getByText('Primary correction now uses gemini-3.6-flash.')).toBeVisible()
  })

  test('does not offer a callable selector for an unverified identifier', async ({ page }) => {
    await open(page)

    const row = page.locator('tbody tr').filter({ hasText: 'Gemini Omni 1.2 Flash' })
    await expect(row.getByRole('button', { name: 'Primary' })).toHaveCount(0)
    await expect(row.getByText('Needs an ID first')).toBeVisible()
  })
})
