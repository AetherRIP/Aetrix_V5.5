import { expect, test } from './support/fixtures'
import type { Page } from '@playwright/test'

/**
 * The health screen reads the engine's one status route — `GET /status` — which
 * reports the API, the correction engine, readiness, the database, the worker
 * and the provider separately. These tests drive that screen against a real
 * engine origin, supplied as `VITE_AETRIX_API_URL` both when the frontend was
 * built and to this test process.
 *
 * The engine calls go to the origin compiled into the bundle. The screen has no
 * localhost fallback: an unset origin renders the unconfigured state, which the
 * build-without-origin coverage in `status.spec.ts` exercises.
 */

const API = (process.env.VITE_AETRIX_API_URL ?? '').replace(/\/$/, '')

/** One channel of the instrument, scoped by its label rather than any text. */
function channel(page: Page, label: string) {
  return page.locator('.health-channel').filter({
    has: page.locator('.health-channel__label', { hasText: new RegExp(`^${label}$`) }),
  })
}

/** Seeds the stored Supabase session, exactly as `roles.spec.ts` does. */
async function signInAsOwner(page: Page) {
  const now = Math.floor(Date.now() / 1000)
  await page.addInitScript(
    ({ issuedAt }) => {
      window.localStorage.setItem(
        'aetrix:auth',
        JSON.stringify({
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
            email_confirmed_at: new Date(issuedAt * 1000).toISOString(),
            phone: '',
            confirmed_at: new Date(issuedAt * 1000).toISOString(),
            last_sign_in_at: new Date(issuedAt * 1000).toISOString(),
            app_metadata: { provider: 'google', aetrix_role: 'owner' },
            user_metadata: { full_name: 'Ana Ruiz', name: 'Ana Ruiz' },
            identities: [],
            created_at: new Date(issuedAt * 1000).toISOString(),
            updated_at: new Date(issuedAt * 1000).toISOString(),
          },
        }),
      )
    },
    { issuedAt: now },
  )
}

test.describe('engine health integration', () => {
  test.skip(!API, 'Set VITE_AETRIX_API_URL to the engine origin this build calls.')

  test('reads /status from the compiled origin and renders its answers', async ({ context }) => {
    const page = await context.newPage()
    await signInAsOwner(page)

    const requested: string[] = []
    page.on('request', (request) => requested.push(request.url()))

    const statusResponse = page.waitForResponse(
      (response) => response.url() === `${API}/status`,
      { timeout: 30_000 },
    )

    await page.goto('/platform/health', { waitUntil: 'load' })

    const status = await statusResponse
    expect(status.status()).toBe(200)

    // The values on screen come from that response, and each subsystem keeps
    // its own wording: "Connected" is the API answering, "Ready" is readiness.
    await expect(channel(page, 'API').locator('.health-channel__state')).toHaveText('Connected')
    await expect(channel(page, 'API')).toContainText('aetrix-engine')
    await expect(channel(page, 'Database').locator('.health-channel__state')).toHaveText(
      'Connected',
    )
    await expect(channel(page, 'Readiness').locator('.health-channel__state')).toHaveText('Ready')

    // The worker is a separate observation. A local engine with no worker
    // process must not be reported as online because the API answered.
    await expect(channel(page, 'Worker').locator('.health-channel__state')).toHaveText('Unknown')

    // Every engine request went to the origin this build was compiled with.
    const engineRequests = requested.filter((url) => url.startsWith(`${API}/`))
    expect(engineRequests.length).toBeGreaterThan(0)
    const hosts = [...new Set(engineRequests.map((url) => new URL(url).host))]
    expect(hosts).toEqual([new URL(API).host])
  })

  test('reports an unreachable engine instead of a healthy service', async ({ context }) => {
    const page = await context.newPage()
    await signInAsOwner(page)

    // A network failure, not a synthetic status: the client's own error path.
    await page.route(`${API}/status`, (route) => route.abort('failed'))

    await page.goto('/platform/health', { waitUntil: 'load' })

    await expect(channel(page, 'API').locator('.health-channel__state')).toHaveText('Unknown')
    await expect(page.locator('body')).not.toContainText('Connected')
    await expect(page.getByText(/could not be reached/i)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'The engine did not answer' })).toBeVisible()
    await expect(page.getByText(/An unreachable endpoint is reported as unreachable/i)).toBeVisible()
  })
})
