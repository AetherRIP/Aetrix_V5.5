import { expect, test } from './support/fixtures'
import type { Page, Route } from '@playwright/test'

/**
 * Google Classroom connection screen.
 *
 * The engine's connection contract is stated explicitly here. The tests check
 * that the screen distinguishes "not configured" from "not connected", and that
 * a sync renders the counts and courses the engine returned rather than an
 * optimistic local result.
 */

const OWNER_ID = '00000000-0000-4000-8000-000000000001'
const TENANT_ID = '00000000-0000-4000-8000-000000000010'
const SCOPE = 'https://www.googleapis.com/auth/classroom.courses.readonly'

type Connection = {
  configured: boolean
  status: 'NOT_CONNECTED' | 'CONNECTED' | 'RECONNECT_REQUIRED'
  redirect_uri: string
  required_scopes: string[]
  granted_scopes: string[]
  connected_at: string | null
  connected_by_subject: string | null
  last_synced_at: string | null
  last_sync_status: 'SUCCEEDED' | 'FAILED' | null
  last_sync_counts: Record<string, number>
  last_error_code: string | null
  last_error_message: string | null
}

const NO_CONNECTION: Connection = {
  configured: true,
  status: 'NOT_CONNECTED',
  redirect_uri: 'http://127.0.0.1:3000/auth/classroom',
  required_scopes: [SCOPE],
  granted_scopes: [],
  connected_at: null,
  connected_by_subject: null,
  last_synced_at: null,
  last_sync_status: null,
  last_sync_counts: {},
  last_error_code: null,
  last_error_message: null,
}

const CONNECTED: Connection = {
  ...NO_CONNECTION,
  status: 'CONNECTED',
  granted_scopes: [SCOPE],
  connected_at: '2026-11-10T09:00:00Z',
  connected_by_subject: 'ana-subject',
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
        email: 'ana@aetrix.test',
        email_confirmed_at: new Date(now * 1000).toISOString(),
        phone: '',
        confirmed_at: new Date(now * 1000).toISOString(),
        last_sign_in_at: new Date(now * 1000).toISOString(),
        app_metadata: { provider: 'google', aetrix_role: 'owner' },
        user_metadata: { full_name: 'Ana Ruiz', name: 'Ana Ruiz' },
        identities: [],
        created_at: new Date(now * 1000).toISOString(),
        updated_at: new Date(now * 1000).toISOString(),
      },
    },
  )
}

function json(route: Route, payload: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
}

async function open(page: Page, connection: Connection) {
  await signIn(page)
  await page.route('**/api/v1/me', (route) =>
    json(route, {
      user_id: OWNER_ID,
      subject: 'ana-subject',
      email: 'ana@aetrix.test',
      display_name: 'Ana Ruiz',
      tenant_id: TENANT_ID,
      workspace_name: 'Alpha workspace',
      workspace_slug: 'alpha',
      role: 'OWNER',
      ui_role: 'owner',
      capabilities: ['read', 'manage_exams', 'review', 'approve'],
      is_demo: false,
    }),
  )
  await page.route('**/api/v1/workspaces/*/classroom-allocations', (route) =>
    json(route, []),
  )
  await page.route('**/api/v1/classroom/connection', (route) => json(route, connection))

  const response = await page.goto('/classroom', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('region', { name: 'Connection', exact: true })).toBeVisible({
    timeout: 30_000,
  })
}

test.describe('Google Classroom connection', () => {
  test('explains a deployment without an OAuth client instead of offering a fake connect', async ({
    page,
  }) => {
    await open(page, { ...NO_CONNECTION, configured: false, redirect_uri: '' })

    const panel = page.getByRole('region', { name: 'Connection', exact: true })
    await expect(panel).toContainText('no Google OAuth client')
    await expect(panel).toContainText('CLASSROOM_NOT_CONFIGURED')
    await expect(panel.getByRole('button', { name: /Connect Google Classroom/ })).toHaveCount(
      0,
    )
  })

  test('offers authorisation when configured and no grant is stored', async ({ page }) => {
    await open(page, NO_CONNECTION)

    const panel = page.getByRole('region', { name: 'Connection', exact: true })
    await expect(panel.getByText('Not connected')).toBeVisible()
    await expect(
      panel.getByRole('button', { name: 'Connect Google Classroom' }),
    ).toBeVisible()
  })

  test('syncs courses and renders the engine counts and verified rows', async ({ page }) => {
    await open(page, CONNECTED)
    let syncPosts = 0
    await page.route('**/api/v1/classroom/sync', (route) => {
      syncPosts += 1
      if (route.request().method() !== 'POST') return route.fallback()
      return json(route, {
        status: 'SUCCEEDED',
        synced_at: '2026-11-10T10:00:00Z',
        counts: { discovered: 2, created: 1, updated: 1 },
        truncated: false,
        courses: [
          {
            course_id: '600100',
            name: '10A Mathematics',
            section: 'Section A',
            course_state: 'ACTIVE',
          },
          {
            course_id: '600200',
            name: '11B Physics',
            section: null,
            course_state: 'ACTIVE',
          },
        ],
      })
    })

    const panel = page.getByRole('region', { name: 'Connection', exact: true })
    await expect(panel.getByText('Connected', { exact: true })).toBeVisible()
    await panel.getByRole('button', { name: 'Sync courses' }).click()

    await expect(
      page.getByText('Google listed 2 active courses: 1 new, 1 updated.'),
    ).toBeVisible()
    const result = page.getByRole('region', { name: 'Courses found by the last sync' })
    await expect(result.locator('tbody tr')).toHaveCount(2)
    await expect(result).toContainText('10A Mathematics')
    await expect(result).toContainText('Section A')
    await expect(result).toContainText('600100')
    await expect(result).toContainText('11B Physics')
    await expect(result).toContainText('600200')
    await expect(result.getByText('VERIFIED')).toHaveCount(2)
    expect(syncPosts).toBe(1)
  })
})
