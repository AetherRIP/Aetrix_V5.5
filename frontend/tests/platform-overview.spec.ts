import { expect, test, type Page } from '@playwright/test'

/**
 * Platform overview.
 *
 * The aggregate endpoint is intercepted, so each test states the engine's answer
 * explicitly. The screen must show measured numbers, a real zero, an unavailable
 * metric or a denied/error state — never a dash standing in for a statistic.
 */

const SELF_ID = '00000000-0000-4000-8000-000000000001'

type MetricState = 'available' | 'no_records' | 'unavailable'
type MetricKey =
  | 'teacher_workspaces'
  | 'teachers'
  | 'assistant_accounts'
  | 'active_class_allocations'

type Metric = {
  key: MetricKey
  label: string
  value: number | null
  state: MetricState
  definition: string
  source: string
  reason: string | null
}

function metric(
  key: MetricKey,
  label: string,
  value: number | null,
  state: MetricState,
  reason: string | null = null,
): Metric {
  return {
    key,
    label,
    value,
    state,
    definition: `${label} definition: active, non-demo records only.`,
    source: key === 'teacher_workspaces' || key === 'active_class_allocations'
      ? 'PostgreSQL'
      : 'Supabase Auth',
    reason,
  }
}

function body(metrics: Metric[]) {
  return {
    generated_at: '2026-11-10T12:00:00Z',
    metrics,
    account_census: {
      available: metrics.find((row) => row.key === 'teachers')?.state !== 'unavailable',
      captured_at: '2026-11-10T11:59:30Z',
      cached: true,
      active_accounts: 9,
      reason: null,
    },
  }
}

async function signIn(page: Page) {
  const now = Math.floor(Date.now() / 1000)
  await page.addInitScript((value) => {
    window.localStorage.setItem('aetrix:auth', JSON.stringify(value))
  }, {
    access_token: 'test-access-token',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: 4102444800,
    refresh_token: 'test-refresh-token',
    user: {
      id: SELF_ID,
      aud: 'authenticated',
      role: 'authenticated',
      email: 'owner@aetrix.test',
      email_confirmed_at: new Date(now * 1000).toISOString(),
      phone: '',
      confirmed_at: new Date(now * 1000).toISOString(),
      last_sign_in_at: new Date(now * 1000).toISOString(),
      app_metadata: { provider: 'google', aetrix_role: 'owner' },
      user_metadata: { full_name: 'Platform Owner', name: 'Platform Owner' },
      identities: [],
      created_at: new Date(now * 1000).toISOString(),
      updated_at: new Date(now * 1000).toISOString(),
    },
  })
}

function card(page: Page, label: string) {
  return page
    .locator('.platform-metric')
    .filter({ has: page.getByText(label, { exact: true }) })
}

async function open(
  page: Page,
  payload: unknown,
  status = 200,
): Promise<{ requests: string[] }> {
  const requests: string[] = []
  await signIn(page)
  await page.route('**/api/v1/admin/overview**', (route) => {
    requests.push(route.request().url())
    return route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    })
  })
  const response = await page.goto('/platform', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('heading', { name: 'Platform overview' })).toBeVisible({
    timeout: 30_000,
  })
  return { requests }
}

test.describe('platform overview', () => {
  test('shows measured platform counts, not placeholders', async ({ page }) => {
    await open(
      page,
      body([
        metric('teacher_workspaces', 'Teacher workspaces', 3, 'available'),
        metric('teachers', 'Teachers', 7, 'available'),
        metric('assistant_accounts', 'Assistant accounts', 2, 'available'),
        metric('active_class_allocations', 'Active class allocations', 5, 'available'),
      ]),
    )

    await expect(card(page, 'Teacher workspaces').locator('.platform-metric__value')).toHaveText('3')
    await expect(card(page, 'Teachers').locator('.platform-metric__value')).toHaveText('7')
    await expect(card(page, 'Assistant accounts').locator('.platform-metric__value')).toHaveText('2')
    await expect(card(page, 'Active class allocations').locator('.platform-metric__value')).toHaveText('5')
    await expect(page.getByText('No records')).toHaveCount(0)
    await expect(page.locator('body')).not.toContainText('no platform endpoint')
    await expect(page.locator('body')).not.toContainText('Awaits engine')
  })

  test('an empty platform is a real zero with a no-records state', async ({ page }) => {
    await open(
      page,
      body([
        metric('teacher_workspaces', 'Teacher workspaces', 0, 'no_records'),
        metric('teachers', 'Teachers', 0, 'no_records'),
        metric('assistant_accounts', 'Assistant accounts', 0, 'no_records'),
        metric('active_class_allocations', 'Active class allocations', 0, 'no_records'),
      ]),
    )

    for (const label of [
      'Teacher workspaces',
      'Teachers',
      'Assistant accounts',
      'Active class allocations',
    ]) {
      await expect(card(page, label).locator('.platform-metric__value')).toHaveText('0')
      await expect(card(page, label).getByText('No records')).toBeVisible()
    }
    await expect(page.locator('.platform-metric__value')).not.toContainText(['—'])
  })

  test('a missing identity census makes only those metrics unavailable', async ({ page }) => {
    await open(
      page,
      body([
        metric('teacher_workspaces', 'Teacher workspaces', 4, 'available'),
        metric(
          'teachers',
          'Teachers',
          null,
          'unavailable',
          'No service-role key is configured on the engine.',
        ),
        metric('assistant_accounts', 'Assistant accounts', 0, 'no_records'),
        metric('active_class_allocations', 'Active class allocations', 6, 'available'),
      ]),
    )

    await expect(card(page, 'Teacher workspaces').locator('.platform-metric__value')).toHaveText('4')
    await expect(card(page, 'Teachers').locator('.platform-metric__value')).toHaveText('Unavailable')
    await expect(
      card(page, 'Teachers').getByText('No service-role key is configured on the engine.'),
    ).toBeVisible()
    await expect(card(page, 'Assistant accounts').locator('.platform-metric__value')).toHaveText('0')
    await expect(card(page, 'Active class allocations').locator('.platform-metric__value')).toHaveText('6')
  })

  test('a workspace owner is told access is denied', async ({ page }) => {
    await open(
      page,
      { error: { code: 'FORBIDDEN', message: 'Platform overview is restricted.' } },
      403,
    )

    await expect(page.getByRole('heading', { name: 'Access denied' })).toBeVisible()
    await expect(page.locator('.platform-metric')).toHaveCount(0)
  })

  test('an engine failure states the reason and offers a retry', async ({ page }) => {
    await open(
      page,
      { error: { code: 'INTERNAL_ERROR', message: 'The platform aggregates could not be read.' } },
      503,
    )

    await expect(
      page.getByRole('heading', { name: 'Platform figures could not be read' }),
    ).toBeVisible()
    await expect(page.getByText('The platform aggregates could not be read.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  })

  test('refresh asks the engine to bypass its census cache', async ({ page }) => {
    const { requests } = await open(
      page,
      body([metric('teacher_workspaces', 'Teacher workspaces', 3, 'available')]),
    )
    expect(requests).toHaveLength(1)
    expect(requests[0]).not.toContain('refresh=true')

    await page.getByRole('button', { name: 'Refresh' }).click()

    await expect.poll(() => requests.length).toBeGreaterThan(1)
    expect(requests.at(-1)).toContain('refresh=true')
  })

  test('a platform data change refreshes immediately without focus or polling', async ({
    page,
  }) => {
    const { requests } = await open(
      page,
      body([metric('teacher_workspaces', 'Teacher workspaces', 3, 'available')]),
    )
    expect(requests).toHaveLength(1)

    // Focus is no longer the refresh trigger: only a real data change is.
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await page.waitForTimeout(150)
    expect(requests).toHaveLength(1)

    await page.evaluate(() =>
      window.dispatchEvent(new Event('aetrix:platform-overview-changed')),
    )

    await expect.poll(() => requests.length).toBe(2)
    expect(requests[1]).toContain('refresh=true')
  })

  test('a change while the overview was closed bypasses the census cache on the next read', async ({
    page,
  }) => {
    await page.addInitScript(() =>
      window.sessionStorage.setItem('aetrix:platform-overview-stale', '1'),
    )
    const { requests } = await open(
      page,
      body([metric('teacher_workspaces', 'Teacher workspaces', 3, 'available')]),
    )

    expect(requests).toHaveLength(1)
    expect(requests[0]).toContain('refresh=true')
  })

  test('loading is an explicit state before the figures arrive', async ({ page }) => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await signIn(page)
    await page.route('**/api/v1/admin/overview**', async (route) => {
      await gate
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          body([metric('teacher_workspaces', 'Teacher workspaces', 3, 'available')]),
        ),
      })
    })

    await page.goto('/platform', { waitUntil: 'load' })
    await expect(page.getByText('Loading…').first()).toBeVisible({ timeout: 30_000 })

    release()
    await expect(card(page, 'Teacher workspaces').locator('.platform-metric__value')).toHaveText('3')
  })
})
