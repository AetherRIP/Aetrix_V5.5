import { expect, test } from './support/fixtures'
import type { Page } from '@playwright/test'

/**
 * The health screen is the one authenticated workspace screen whose engine
 * contract already exists (`GET /health` and `GET /ready`). These tests drive it
 * against a real engine origin, supplied as `VITE_AETRIX_API_URL` when the
 * frontend was built and to this test process.
 */

const API = (process.env.VITE_AETRIX_API_URL ?? '').replace(/\/$/, '')

/** One metric row, scoped by its label rather than any text in the row. */
function metric(page: Page, label: string) {
  return page.locator('.hub-stat').filter({
    has: page.locator('.hub-stat__label', { hasText: new RegExp(`^${label}$`) }),
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

  test('reads /health and /ready over HTTPS and renders their answers', async ({ context }) => {
    const page = await context.newPage()
    await signInAsOwner(page)

    const requested: string[] = []
    page.on('request', (request) => requested.push(request.url()))

    const healthResponse = page.waitForResponse(
      (response) => response.url() === `${API}/health`,
      { timeout: 30_000 },
    )
    const readyResponse = page.waitForResponse(
      (response) => response.url() === `${API}/ready`,
      { timeout: 30_000 },
    )

    await page.goto('/platform/health', { waitUntil: 'load' })

    const [health, ready] = await Promise.all([healthResponse, readyResponse])
    expect(health.status()).toBe(200)
    expect(ready.status()).toBe(200)

    // The values on screen come from those two responses.
    await expect(metric(page, 'API').locator('.hub-stat__value')).toHaveText('Reachable')
    await expect(metric(page, 'API').locator('.hub-stat__note')).toContainText('aetrix-engine')
    await expect(metric(page, 'Database').locator('.hub-stat__value')).toHaveText('Ready')

    // The engine calls go to the compiled public origin, never a localhost
    // fallback. (The preview's own assets are served from 127.0.0.1:3000.)
    const engineCalls = requested.filter(
      (url) => url === `${API}/health` || url === `${API}/ready`,
    )
    expect(engineCalls.sort()).toEqual([`${API}/health`, `${API}/ready`].sort())
    expect(new URL(API).hostname).not.toMatch(/^(localhost|127\.0\.0\.1)$/)
  })

  test('reports an unreachable engine instead of a healthy service', async ({ context }) => {
    const page = await context.newPage()
    await signInAsOwner(page)

    // A network failure, not a synthetic status: the client's own error path.
    await page.route(`${API}/health`, (route) => route.abort('failed'))
    await page.route(`${API}/ready`, (route) => route.abort('failed'))

    await page.goto('/platform/health', { waitUntil: 'load' })

    await expect(metric(page, 'API').locator('.hub-stat__value')).toHaveText('Unreachable')
    await expect(metric(page, 'Database').locator('.hub-stat__value')).toHaveText('Not ready')
    await expect(page.getByRole('heading', { name: 'The engine did not answer' })).toBeVisible()
  })
})
