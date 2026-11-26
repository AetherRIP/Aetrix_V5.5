import { expect, test } from './support/fixtures'
import type { Page, Route } from '@playwright/test'

/**
 * Google Classroom screens.
 *
 * The engine's contracts are stated explicitly here. The platform screen checks
 * that one central connection is distinguished from "not configured" and from
 * "reconnect required", and that a sync renders the counts and courses the
 * engine actually returned. The workspace screen checks that only allocated
 * courses appear and that an empty allocation is not dressed up as data.
 */

const OWNER_ID = '00000000-0000-4000-8000-000000000001'
const TENANT_ID = '00000000-0000-4000-8000-000000000010'
const COURSES_SCOPE = 'https://www.googleapis.com/auth/classroom.courses.readonly'
const ROSTERS_SCOPE = 'https://www.googleapis.com/auth/classroom.rosters.readonly'

type Connection = {
  configured: boolean
  status: 'NOT_CONNECTED' | 'CONNECTED' | 'RECONNECT_REQUIRED'
  redirect_uri: string | null
  required_scopes: string[]
  granted_scopes: string[]
  missing_scopes: string[]
  connected_at: string | null
  connected_by_subject: string | null
  connected_account_email: string | null
  connected_account_name: string | null
  last_refresh_at: string | null
  last_synced_at: string | null
  last_sync_status: 'SUCCEEDED' | 'FAILED' | null
  last_sync_counts: Record<string, number>
  last_error_code: string | null
  last_error_message: string | null
  recent_runs: unknown[]
}

const NO_CONNECTION: Connection = {
  configured: true,
  status: 'NOT_CONNECTED',
  redirect_uri: 'http://127.0.0.1:3000/auth/classroom',
  required_scopes: [COURSES_SCOPE, ROSTERS_SCOPE],
  granted_scopes: [],
  missing_scopes: [COURSES_SCOPE, ROSTERS_SCOPE],
  connected_at: null,
  connected_by_subject: null,
  connected_account_email: null,
  connected_account_name: null,
  last_refresh_at: null,
  last_synced_at: null,
  last_sync_status: null,
  last_sync_counts: {},
  last_error_code: null,
  last_error_message: null,
  recent_runs: [],
}

const CONNECTED: Connection = {
  ...NO_CONNECTION,
  status: 'CONNECTED',
  granted_scopes: [COURSES_SCOPE, ROSTERS_SCOPE],
  missing_scopes: [],
  connected_at: '2026-11-10T09:00:00Z',
  connected_by_subject: 'operator-subject',
  connected_account_email: 'central@aetrix.test',
  connected_account_name: 'Aetrix Central',
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

async function mockSession(
  page: Page,
  capabilities: string[],
  isPlatformAdmin = false,
) {
  await signIn(page)
  await page.route('**/api/v1/me', (route) =>
    json(route, {
      user_id: OWNER_ID,
      subject: 'operator-subject',
      email: 'ana@aetrix.test',
      display_name: 'Ana Ruiz',
      tenant_id: TENANT_ID,
      workspace_name: 'Alpha workspace',
      workspace_slug: 'alpha',
      role: 'OWNER',
      ui_role: 'owner',
      capabilities,
      is_platform_admin: isPlatformAdmin,
      is_demo: false,
    }),
  )
}

async function openPlatform(page: Page, connection: Connection) {
  await mockSession(page, ['platform_admin', 'platform.allocations.manage'], true)
  await page.route('**/api/v1/admin/classroom/connection', (route) => json(route, connection))
  await page.route('**/api/v1/admin/classroom/courses*', (route) =>
    json(route, [
      {
        id: '11111111-1111-4111-8111-111111111111',
        course_id: '600100',
        name: '10A Mathematics',
        section: 'Section A',
        room: null,
        course_state: 'ACTIVE',
        teacher_name: 'Aetrix Central',
        owner_email: 'central@aetrix.test',
        verification: 'VERIFIED',
        synced_at: '2026-11-10T09:30:00Z',
        workspace_id: null,
        workspace_name: null,
        allocation_id: null,
        allocated_at: null,
      },
    ]),
  )
  await page.route('**/api/v1/admin/classroom/sync-runs', (route) => json(route, []))

  const response = await page.goto('/platform/classroom', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(
    page.getByRole('region', { name: 'Central Google account', exact: true }),
  ).toBeVisible({ timeout: 30_000 })
}

test.describe('platform Google Classroom connection', () => {
  test('explains a deployment without an OAuth client instead of offering a fake connect', async ({
    page,
  }) => {
    await openPlatform(page, { ...NO_CONNECTION, configured: false, redirect_uri: null })

    const panel = page.getByRole('region', { name: 'Central Google account', exact: true })
    await expect(panel).toContainText('No Google OAuth client is configured')
    await expect(panel).toContainText('CLASSROOM_NOT_CONFIGURED')
    await expect(
      panel.getByRole('button', { name: /Connect the central account/ }),
    ).toHaveCount(0)
  })

  test('offers authorisation when configured and no grant is stored', async ({ page }) => {
    await openPlatform(page, NO_CONNECTION)

    const panel = page.getByRole('region', { name: 'Central Google account', exact: true })
    await expect(panel.getByText('Not connected')).toBeVisible()
    await expect(
      panel.getByRole('button', { name: 'Connect the central account' }),
    ).toBeVisible()
  })

  test('syncs courses and renders the engine counts and verified rows', async ({ page }) => {
    await openPlatform(page, CONNECTED)
    let syncPosts = 0
    await page.route('**/api/v1/admin/classroom/sync', (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      syncPosts += 1
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

    const panel = page.getByRole('region', { name: 'Central Google account', exact: true })
    await expect(panel.getByText('Connected', { exact: true })).toBeVisible()
    await panel.getByRole('button', { name: 'Synchronise courses' }).click()

    await expect(
      page.getByText('Google listed 2 course(s): 1 new, 1 updated.'),
    ).toBeVisible()
    const courses = page.getByRole('region', { name: 'Discovered courses' })
    await expect(courses).toContainText('10A Mathematics')
    await expect(courses).toContainText('600100')
    await expect(courses).toContainText('VERIFIED')
    await expect(courses).toContainText('not allocated')
    expect(syncPosts).toBe(1)
  })
})

test.describe('workspace Google Classroom courses', () => {
  test('lists only the courses allocated to this workspace', async ({ page }) => {
    await mockSession(page, ['workspace.classroom.connect'])
    await page.route('**/api/v1/workspaces/*/classroom/courses', (route) =>
      json(route, [
        {
          allocation_id: '22222222-2222-4222-8222-222222222222',
          classroom_class_id: '11111111-1111-4111-8111-111111111111',
          course_id: '600100',
          name: '10A Mathematics',
          section: 'Section A',
          course_state: 'ACTIVE',
          students: 0,
          coursework: 0,
        },
      ]),
    )
    await page.route('**/api/v1/workspaces/*/classroom/coursework', (route) => json(route, []))
    await page.route('**/api/v1/workspaces/*/assignments', (route) => json(route, []))

    await page.goto('/classroom', { waitUntil: 'load' })

    await expect(
      page.getByRole('region', { name: 'Your class workflow' }),
    ).toContainText('Create the assignment in Aetrix')

    const panel = page.getByRole('region', { name: 'Allocated Classroom courses' })
    await expect(panel).toContainText('10A Mathematics')
    await expect(panel).toContainText('600100')
    // The teacher screen never offers to connect or move a course.
    await expect(page.getByRole('button', { name: /Connect/ })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Allocate|Reassign/ })).toHaveCount(0)
  })

  test('says plainly when no course has been allocated', async ({ page }) => {
    await mockSession(page, ['workspace.classroom.connect'])
    await page.route('**/api/v1/workspaces/*/classroom/courses', (route) => json(route, []))
    await page.route('**/api/v1/workspaces/*/classroom/coursework', (route) => json(route, []))
    await page.route('**/api/v1/workspaces/*/assignments', (route) => json(route, []))

    await page.goto('/classroom', { waitUntil: 'load' })

    const panel = page.getByRole('region', { name: 'Allocated Classroom courses' })
    await expect(panel).toContainText('No Classroom course is allocated to this workspace')
  })
})
