import { expect, test, type Locator, type Page } from '@playwright/test'

/**
 * Workspace allocation.
 *
 * The engine routes are intercepted with a small stateful fake so the screen is
 * exercised as an operator would: record a course, allocate it, release it, then
 * allocate and reassign again. The fake enforces the one-active-allocation rule,
 * so the UI cannot appear to succeed twice.
 */

const OWNER_ID = '00000000-0000-4000-8000-000000000001'
const ALPHA = '00000000-0000-4000-8000-000000000010'
const BETA = '00000000-0000-4000-8000-000000000020'

type Allocation = {
  id: string
  classroom_class_id: string
  course_id: string
  class_name: string
  class_section: string | null
  verification: 'UNVERIFIED' | 'VERIFIED'
  workspace_id: string
  workspace_name: string
  status: 'ACTIVE' | 'RELEASED'
  origin: 'ALLOCATE' | 'REASSIGN'
  allocated_by_subject: string
  allocated_by_label: string | null
  allocated_at: string
  released_by_subject: string | null
  released_by_label: string | null
  released_at: string | null
  release_reason: string | null
  reason: string | null
  previous_allocation_id: string | null
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
      id: OWNER_ID,
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

async function open(page: Page) {
  const workspaces = [
    {
      id: ALPHA,
      name: 'Alpha workspace',
      slug: 'alpha',
      owner_label: 'Teacher A',
      owner_email: 'a@aetrix.test',
      active_allocations: 0,
    },
    {
      id: BETA,
      name: 'Beta workspace',
      slug: 'beta',
      owner_label: 'Teacher B',
      owner_email: 'b@aetrix.test',
      active_allocations: 0,
    },
  ]
  let available: any[] = []
  const allocations: Allocation[] = []

  const json = (route: any, status: number, payload: unknown) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    })

  await signIn(page)
  await page.route('**/api/v1/admin/allocations**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (method === 'GET' && path.endsWith('/capability')) {
      return json(route, 200, {
        allocation_available: true,
        discovery_configured: false,
        verification: 'UNVERIFIED',
        reason:
          'No Google Classroom OAuth client is configured in this engine. The authorisation and sync routes exist, but they report CLASSROOM_NOT_CONFIGURED until the client is configured.',
        operations: [
          {
            name: 'discover classes from Google Classroom',
            supported: true,
            note: 'A workspace owner or administrator authorises the classroom.courses.readonly scope and runs a course sync.',
          },
        ],
      })
    }
    if (method === 'GET' && path.endsWith('/workspaces')) {
      return json(route, 200, workspaces)
    }
    if (method === 'GET' && path.endsWith('/available-classes')) {
      return json(route, 200, available)
    }
    if (method === 'GET' && path.endsWith('/allocations')) {
      const status = url.searchParams.get('status') ?? 'ALL'
      const items = allocations.filter((row) => status === 'ALL' || row.status === status)
      return json(route, 200, {
        items,
        total: items.length,
        limit: 50,
        offset: 0,
      })
    }
    if (method === 'POST' && path.endsWith('/classes')) {
      const draft = request.postDataJSON() as { course_id: string; name: string }
      const classroom = {
        id: '00000000-0000-4000-8000-0000000000c1',
        course_id: draft.course_id,
        name: draft.name,
        section: null,
        course_state: 'ACTIVE',
        verification: 'UNVERIFIED',
        source: 'operator_recorded',
        owner_email: null,
        synced_at: null,
        created_at: '2026-11-10T12:00:00Z',
      }
      available = [classroom]
      return json(route, 201, classroom)
    }
    if (method === 'POST' && path.endsWith('/allocations')) {
      const draft = request.postDataJSON() as {
        classroom_class_id: string
        workspace_id: string
      }
      if (allocations.some((row) => row.status === 'ACTIVE' && row.classroom_class_id === draft.classroom_class_id)) {
        return json(route, 409, {
          error: { code: 'CONFLICT', message: 'That class already has an active allocation.' },
        })
      }
      const classroom = available.find((row) => row.id === draft.classroom_class_id)
      const workspace = workspaces.find((row) => row.id === draft.workspace_id)!
      const allocation: Allocation = {
        id: `allocation-${allocations.length + 1}`,
        classroom_class_id: draft.classroom_class_id,
        course_id: classroom.course_id,
        class_name: classroom.name,
        class_section: null,
        verification: 'UNVERIFIED',
        workspace_id: workspace.id,
        workspace_name: workspace.name,
        status: 'ACTIVE',
        origin: 'ALLOCATE',
        allocated_by_subject: 'owner-subject',
        allocated_by_label: 'owner-subject',
        allocated_at: '2026-11-10T12:05:00Z',
        released_by_subject: null,
        released_by_label: null,
        released_at: null,
        release_reason: null,
        reason: null,
        previous_allocation_id: null,
      }
      allocations.unshift(allocation)
      available = available.filter((row) => row.id !== classroom.id)
      return json(route, 201, allocation)
    }
    if (method === 'POST' && path.endsWith('/release')) {
      const allocation = allocations.find((row) => path.includes(row.id))!
      allocation.status = 'RELEASED'
      allocation.released_at = '2026-11-10T12:10:00Z'
      allocation.release_reason = 'timetable change'
      available = [
        {
          id: allocation.classroom_class_id,
          course_id: allocation.course_id,
          name: allocation.class_name,
          section: null,
          course_state: 'ACTIVE',
          verification: allocation.verification,
          source: 'operator_recorded',
          owner_email: null,
          synced_at: null,
          created_at: '2026-11-10T12:00:00Z',
        },
      ]
      return json(route, 200, allocation)
    }
    if (method === 'POST' && path.endsWith('/reassign')) {
      const draft = request.postDataJSON() as { workspace_id: string; reason: string }
      const old = allocations.find((row) => path.includes(row.id))!
      old.status = 'RELEASED'
      old.released_at = '2026-11-10T12:20:00Z'
      old.release_reason = `Reassigned: ${draft.reason}`
      const workspace = workspaces.find((row) => row.id === draft.workspace_id)!
      const moved: Allocation = {
        ...old,
        id: `allocation-${allocations.length + 1}`,
        workspace_id: workspace.id,
        workspace_name: workspace.name,
        status: 'ACTIVE',
        origin: 'REASSIGN',
        allocated_at: '2026-11-10T12:20:00Z',
        released_at: null,
        released_by_subject: null,
        released_by_label: null,
        release_reason: null,
        previous_allocation_id: old.id,
      }
      allocations.unshift(moved)
      return json(route, 200, moved)
    }
    return json(route, 404, { error: { code: 'NOT_FOUND', message: 'no route' } })
  })

  const response = await page.goto('/platform/workspaces', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('heading', { level: 1, name: 'Workspace allocation' })).toBeVisible({
    timeout: 30_000,
  })
  await page.evaluate(() => {
    document.body.dataset.platformOverviewChanges = '0'
    window.addEventListener('aetrix:platform-overview-changed', () => {
      const current = Number(document.body.dataset.platformOverviewChanges ?? '0')
      document.body.dataset.platformOverviewChanges = String(current + 1)
    })
  })
}

function classRow(root: Locator, courseId: string) {
  return root.locator('tbody tr').filter({ hasText: courseId })
}

function panel(page: Page, title: string): Locator {
  return page.getByRole('region', { name: title })
}

test.describe('workspace allocation', () => {
  test('an operator records, allocates, releases and reassigns a class', async ({ page }) => {
    await open(page)

    await expect(
      page.getByRole('heading', { name: 'Google Classroom discovery is not configured' }),
    ).toBeVisible()
    await expect(page.getByText('Alpha workspace').first()).toBeVisible()
    await expect(page.getByText('Beta workspace').first()).toBeVisible()

    await page.locator('#classroom-course-id').fill('600100')
    await page.locator('#classroom-name').fill('10A Mathematics')
    await page.getByLabel(/I have read this course from Google Classroom/).check()
    await page.getByRole('button', { name: 'Record class' }).click()

    const availablePanel = panel(page, 'Available classes')
    const historyPanel = panel(page, 'Allocation history')
    const availableRow = classRow(availablePanel, '600100')
    await expect(availableRow).toContainText('UNVERIFIED')
    await expect(availableRow).toContainText('10A Mathematics')

    await availableRow.getByRole('button', { name: 'Allocate' }).click()
    await page.locator('#allocation-workspace').selectOption(BETA)
    await page.locator('#allocation-reason').fill('timetable')
    await page.getByRole('button', { name: 'Confirm' }).click()

    await expect(page.getByRole('status')).toContainText('Allocation succeeded.')
    await expect
      .poll(() => page.locator('body').getAttribute('data-platform-overview-changes'))
      .toBe('1')
    const activeRow = classRow(historyPanel, '600100')
    await expect(activeRow).toContainText('Beta workspace')
    await expect(activeRow).toContainText('ACTIVE')

    await activeRow.getByRole('button', { name: 'Release' }).click()
    await page.getByRole('button', { name: 'Release allocation' }).click()
    await expect(page.getByRole('status')).toContainText('Release succeeded.')
    await expect(classRow(historyPanel, '600100')).toContainText('RELEASED')
    await expect
      .poll(() => page.locator('body').getAttribute('data-platform-overview-changes'))
      .toBe('2')

    // Released means available again: allocate to Beta, then reassign to Alpha.
    await classRow(availablePanel, '600100').getByRole('button', { name: 'Allocate' }).click()
    await page.locator('#allocation-workspace').selectOption(BETA)
    await page.getByRole('button', { name: 'Confirm' }).click()
    await expect(page.getByRole('status')).toContainText('Allocation succeeded.')

    await classRow(historyPanel, '600100').getByRole('button', { name: 'Reassign' }).click()
    await page.locator('#allocation-workspace').selectOption(ALPHA)
    await page.locator('#allocation-reason').fill('teacher changed')
    await page.getByRole('button', { name: 'Confirm' }).click()
    await expect(page.getByRole('status')).toContainText('Reassignment succeeded.')

    const rows = classRow(historyPanel, '600100')
    await expect(rows).toHaveCount(3)
    await expect(rows.filter({ hasText: 'Alpha workspace' })).toContainText('ACTIVE')
    await expect(rows.filter({ hasText: 'Alpha workspace' })).toContainText('reassigned')
  })

  test('an empty platform offers the record form without inventing classes', async ({ page }) => {
    await open(page)
    await expect(page.getByText('No unallocated course is recorded.')).toBeVisible()
    await expect(page.getByText('No allocation matches this filter.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Record class' })).toBeDisabled()
  })
})
