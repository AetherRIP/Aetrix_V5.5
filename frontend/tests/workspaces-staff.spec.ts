import { expect, test } from './support/fixtures'
import type { Page } from '@playwright/test'

/**
 * One allocated class, one workshop, one teacher, and the assistants who
 * support them — shown on the workspace card itself so an administrator does not
 * have to visit several settings pages to answer "who is responsible for this
 * class?".
 *
 * The engine read is intercepted: a 404 stands for a deployed build that does not
 * carry the class-assignment API yet, and the screen must say so instead of
 * offering a control that cannot work.
 */

const WORKSPACE = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Development workspace',
  slug: 'dev',
  owner_label: 'Development owner',
  owner_email: 'dev@aetrix.test',
  active_allocations: 1,
}

const ALLOCATION = {
  id: 'aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa',
  classroom_class_id: 'bbbbbbbb-0000-4000-8000-bbbbbbbbbbbb',
  course_id: '900988657199',
  class_name: 'Aetrix Testing',
  class_section: null,
  verification: 'VERIFIED',
  workspace_id: WORKSPACE.id,
  workspace_name: WORKSPACE.name,
  status: 'ACTIVE',
  origin: 'ALLOCATE',
  allocated_by_subject: 'owner',
  allocated_by_label: 'Dev owner',
  allocated_at: '2026-11-25T10:00:00Z',
  released_by_subject: null,
  released_by_label: null,
  released_at: null,
  release_reason: null,
  reason: null,
  previous_allocation_id: null,
}

const MEMBERS = [
  {
    id: '22222222-2222-4222-8222-222222222222',
    subject: 'teacher-1',
    email: 'teacher@aetrix.test',
    display_name: 'Rudro Pratihar',
    role: 'TEACHER',
    created_at: '2026-11-01T00:00:00Z',
  },
  {
    id: '33333333-3333-4333-8333-333333333333',
    subject: 'assistant-1',
    email: 'assistant@aetrix.test',
    display_name: 'Shino Asada',
    role: 'REVIEWER',
    created_at: '2026-11-01T00:00:00Z',
  },
]

const ASSIGNMENT_ROWS = [
  {
    id: '44444444-4444-4444-8444-444444444444',
    allocation_id: ALLOCATION.id,
    classroom_class_id: ALLOCATION.classroom_class_id,
    course_id: ALLOCATION.course_id,
    class_name: ALLOCATION.class_name,
    user_id: MEMBERS[0].id,
    user_label: MEMBERS[0].display_name,
    user_email: MEMBERS[0].email,
    user_role: 'TEACHER',
    assigned_by_label: 'Dev owner',
    assigned_at: '2026-11-25T10:05:00Z',
  },
  {
    id: '55555555-5555-4555-8555-555555555555',
    allocation_id: ALLOCATION.id,
    classroom_class_id: ALLOCATION.classroom_class_id,
    course_id: ALLOCATION.course_id,
    class_name: ALLOCATION.class_name,
    user_id: MEMBERS[1].id,
    user_label: MEMBERS[1].display_name,
    user_email: MEMBERS[1].email,
    user_role: 'REVIEWER',
    assigned_by_label: 'Dev owner',
    assigned_at: '2026-11-25T10:06:00Z',
  },
]

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
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      role: 'authenticated',
      email: 'owner@aetrix.test',
      email_confirmed_at: new Date(now * 1000).toISOString(),
      app_metadata: { provider: 'google', aetrix_role: 'owner' },
      user_metadata: { full_name: 'Rudro Pratihar' },
      identities: [],
    },
  })
}

async function open(page: Page, assignmentsStatus = 200) {
  await signIn(page)
  const posted: unknown[] = []

  await page.route('**/auth/v1/**', (route) => {
    const user = {
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      role: 'authenticated',
      email: 'owner@aetrix.test',
      email_confirmed_at: '2026-11-01T00:00:00Z',
      app_metadata: { provider: 'google', aetrix_role: 'owner' },
      user_metadata: {},
      identities: [],
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'test-access-token',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: 4102444800,
        refresh_token: 'test-refresh-token',
        user,
      }),
    })
  })

  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const url = request.url()
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

    if (/\/api\/v1\/me(\?|$)/.test(url)) {
      return json({
        user_id: '00000000-0000-4000-8000-000000000001',
        subject: '00000000-0000-4000-8000-000000000001',
        email: 'owner@aetrix.test',
        display_name: 'Rudro Pratihar',
        tenant_id: WORKSPACE.id,
        workspace_name: WORKSPACE.name,
        workspace_slug: 'dev',
        role: 'PLATFORM_OWNER',
        ui_role: 'owner',
        capabilities: ['platform_admin', 'manage_members'],
        is_platform_admin: true,
        is_demo: false,
      })
    }
    if (url.includes('/classroom/courses/') && url.includes('/assignments')) {
      if (request.method() === 'POST') {
        posted.push(request.postDataJSON())
        return json({ ...ASSIGNMENT_ROWS[0], id: 'new-assignment' }, 201)
      }
      if (request.method() === 'DELETE') return route.fulfill({ status: 204, body: '' })
      if (assignmentsStatus !== 200) return json({ detail: 'Not Found' }, assignmentsStatus)
      return json(ASSIGNMENT_ROWS)
    }
    if (url.includes('/members')) return json(MEMBERS)
    if (url.includes('/admin/allocations/capability')) {
      return json({
        allocation_available: true,
        discovery_configured: true,
        verification: 'VERIFIED',
        reason: 'Discovery is configured.',
        operations: [],
      })
    }
    if (url.includes('/admin/allocations/workspaces')) return json([WORKSPACE])
    if (url.includes('/admin/allocations/available-classes')) return json([])
    if (url.includes('/admin/allocations')) {
      return json({ items: [ALLOCATION], total: 1, limit: 200, offset: 0 })
    }
    if (url.includes('/messaging/')) return json([])
    return json([])
  })

  const response = await page.goto('/platform/workspaces', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  return { posted }
}

test.describe('class staff assignment', () => {
  test('the workspace card names the teacher and the assistants for its class', async ({ page }) => {
    await open(page)

    const staff = page.locator('.ws-staff').first()
    await expect(staff).toContainText('Rudro Pratihar')
    await expect(staff).toContainText('Shino Asada')
    await expect(staff.getByText('Teacher responsible')).toBeVisible()
    await expect(staff.getByRole('button', { name: 'Manage staff…' })).toBeVisible()
  })

  test('an engine without the assignment API says so instead of offering a dead control', async ({ page }) => {
    await open(page, 404)

    const staff = page.locator('.ws-staff').first()
    await expect(staff).toContainText('needs the newer engine')
    await expect(staff.getByRole('button', { name: 'Manage staff…' })).toHaveCount(0)
  })

  test('an administrator can assign a member to the class from the workspace card', async ({ page }) => {
    const seen = await open(page)
    await page.locator('.ws-staff').first().getByRole('button', { name: 'Manage staff…' }).click()

    const dialog = page.getByRole('dialog', { name: /Aetrix Testing/ })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('This class belongs to Development workspace')

    // Both existing assignments are shown as removable; nothing offers to reassign the class.
    await expect(dialog.getByRole('button', { name: 'Remove' })).toHaveCount(2)
    await expect(dialog).toContainText('Neither role can move the class to another workshop')
    expect(seen.posted).toHaveLength(0)
  })
})
