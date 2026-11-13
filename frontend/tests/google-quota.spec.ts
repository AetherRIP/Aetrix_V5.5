import { expect, test } from './support/fixtures'
import type { Page } from '@playwright/test'

/**
 * The Google quota tab. The report is intercepted, so this checks that Google's
 * values reach the screen with their sources and timestamps, that unavailable
 * facts stay words rather than zeros, and that Sync calls the manual endpoint.
 */

const OBSERVED = '2026-11-10T10:00:00Z'

const QUOTA = {
  quota_id: 'GenerateContentRequestsPerMinutePerProjectPerModel',
  metric: 'generativelanguage.googleapis.com/generate_content_requests',
  service: 'generativelanguage.googleapis.com',
  metric_display_name: 'Generate content requests',
  quota_display_name: 'Requests per minute',
  unit: '1/min',
  refresh_interval: 'minute',
  reset_time: '2026-11-11T00:00:00Z',
  container_type: 'PROJECT',
  is_precise: true,
  dimensions: { model: 'gemini-2.5-pro' },
  limit: 10,
  is_unlimited: false,
  limit_source: 'CLOUD_QUOTAS',
  usage: 4,
  usage_source: 'CLOUD_MONITORING',
  usage_metric: 'serviceruntime.googleapis.com/quota/allocation/usage',
  usage_observed_at: OBSERVED,
  exceeded: 0,
  observed_at: OBSERVED,
}

const REPORT = {
  observed_at: OBSERVED,
  service: 'generativelanguage.googleapis.com',
  fleet: {
    configured: true,
    credential_source: 'SERVICE_ACCOUNT_FILE',
    scheduled_sync_enabled: true,
    sync_interval_seconds: 900,
    stale_after_seconds: 3600,
    declared_projects: 1,
    verified_projects: 1,
    quotas_total: 1,
    usage_observed: 1,
    stale_projects: 0,
    last_success_at: OBSERVED,
    last_failure_at: null,
    last_failure_message: null,
  },
  projects: [
    {
      project_id: 'aetrix-prod',
      verification: 'VERIFIED',
      verified: true,
      project_number: '123456789',
      display_name: 'Aetrix production',
      lifecycle_state: 'ACTIVE',
      last_attempt_at: OBSERVED,
      last_verified_at: OBSERVED,
      last_success_at: OBSERVED,
      last_error_code: null,
      last_error_message: null,
      stale: false,
      quota_count: 1,
      usage_observed: 1,
      quotas: [QUOTA],
      runs: [
        {
          id: '11111111-1111-4111-8111-111111111111',
          trigger: 'SCHEDULED',
          status: 'SUCCEEDED',
          started_at: OBSERVED,
          finished_at: OBSERVED,
          quota_infos: 1,
          snapshots_written: 1,
          api_calls: 8,
          error_code: null,
          error_message: null,
        },
      ],
    },
  ],
  apis: [
    {
      service: 'monitoring.googleapis.com',
      name: 'Cloud Monitoring API',
      permission: 'monitoring.timeSeries.list',
      used_for: 'Read consumer-quota usage.',
      enabled: true,
    },
  ],
  ai_studio: {
    available: false,
    reason:
      'Google AI Studio displays active Gemini API rate limits and usage in its console, but publishes no public API for them.',
    source: 'https://ai.google.dev/gemini-api/docs/rate-limits',
  },
  coverage: {
    supported: ['Quota definitions and limits from Cloud Quotas.'],
    unavailable: ['AI Studio usage and the per-model RPM/RPD/TPM table.'],
  },
  note: 'Limits and usage carry their own sources and timestamps.',
  sync_results: [],
}

const OVERVIEW = {
  keys_total: 1,
  keys_by_health: { HEALTHY: 1 },
  projects: 1,
  requests_today: 4,
  input_tokens_today: 0,
  output_tokens_today: 0,
  failures_today: 0,
  error_rate_today: 0,
  observed_at: OBSERVED,
  day_started_at: '2026-11-10T08:00:00Z',
  reset_at: '2026-11-11T08:00:00Z',
  projects_detail: [],
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

async function open(page: Page, report: typeof REPORT, onSync?: () => void) {
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

    if (request.method() === 'POST' && url.endsWith('/google-quota/sync')) {
      onSync?.()
      return json({
        ...report,
        sync_results: [
          {
            project_id: 'aetrix-prod',
            status: 'SUCCEEDED',
            run_id: '22222222-2222-4222-8222-222222222222',
            verification: 'VERIFIED',
            quota_infos: 1,
            snapshots: 1,
            error_code: null,
            message: null,
          },
        ],
      })
    }
    if (url.endsWith('/google-quota')) return json(report)
    if (url.includes('/overview')) return json(OVERVIEW)
    return json([])
  })

  const response = await page.goto('/platform/gemini', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await page.getByRole('tab', { name: 'Google quota' }).click()
}

test.describe('Google Cloud quota tab', () => {
  test('shows Google sources, timestamps and unavailable AI Studio data', async ({ page }) => {
    await open(page, REPORT)

    await expect(page.getByText(/Read-only synchronisation of/)).toBeVisible()
    await expect(page.getByText('aetrix-prod')).toBeVisible()
    await expect(page.getByText('Requests per minute')).toBeVisible()
    await expect(page.getByText(/Cloud Quotas · reset/)).toBeVisible()
    await expect(page.getByText(/Cloud Monitoring ·/)).toBeVisible()
    await expect(page.getByText('10 1/min')).toBeVisible()
    await expect(page.getByText('4', { exact: true })).toBeVisible()
    await expect(page.getByText('Unavailable programmatically')).toBeVisible()
    await expect(page.getByText(/no public API/)).toBeVisible()
    await expect(page.getByText('SERVICE_ACCOUNT_FILE')).toBeVisible()
  })

  test('Sync now calls the manual endpoint and reports the outcome', async ({ page }) => {
    let syncs = 0
    await open(page, REPORT, () => {
      syncs += 1
    })

    await page.getByRole('button', { name: 'Sync now' }).click()

    await expect.poll(() => syncs).toBe(1)
    await expect(page.getByRole('status')).toContainText(
      'Google Cloud sync: aetrix-prod succeeded.',
    )
  })

  test('an unconfigured engine says so and disables Sync', async ({ page }) => {
    await open(page, {
      ...REPORT,
      fleet: {
        ...REPORT.fleet,
        configured: false,
        credential_source: 'NOT_CONFIGURED',
        scheduled_sync_enabled: false,
      },
      projects: [],
      ai_studio: REPORT.ai_studio,
    })

    await expect(page.getByText('No credential')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sync now' })).toBeDisabled()
    await expect(page.getByText(/AETRIX_GOOGLE_CLOUD__SERVICE_ACCOUNT_FILE/)).toBeVisible()
  })
})
