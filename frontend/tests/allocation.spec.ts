import { expect, test } from './support/fixtures'
import type { Locator, Page } from '@playwright/test'

/**
 * Workspaces and Classroom allocation.
 *
 * The engine routes are intercepted with a small stateful fake so the screen is
 * exercised as an operator would: record a course, allocate it through the
 * guided flow, release it, allocate again and move it. The fake enforces the
 * one-active-allocation rule, so the UI cannot appear to succeed twice.
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

type Workspace = {
  id: string
  name: string
  slug: string
  owner_label: string
  owner_email: string
  active_allocations: number
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

async function open(
  page: Page,
  options: {
    workspaces?: Workspace[]
    deny?: boolean
    unavailable?: boolean
    failAllocate?: boolean
  } = {},
) {
  const workspaces: Workspace[] = options.workspaces ?? [
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

    if (options.deny && method === 'GET') {
      return json(route, 403, {
        error: { code: 'FORBIDDEN', message: 'Platform authority is required.' },
      })
    }
    if (options.unavailable && method === 'GET') {
      return json(route, 503, {
        error: { code: 'UNAVAILABLE', message: 'The correction engine is not available.' },
      })
    }

    if (method === 'GET' && path.endsWith('/capability')) {
      return json(route, 200, {
        allocation_available: true,
        discovery_configured: false,
        verification: 'UNVERIFIED',
        reason:
          'No Google Classroom OAuth client is configured in this engine. The authorisation and sync routes exist, but they report CLASSROOM_NOT_CONFIGURED until the client is configured.',
        operations: [],
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
      if (options.failAllocate) {
        return json(route, 409, {
          error: {
            code: 'CONFLICT',
            message: 'That class already has an active allocation.',
          },
        })
      }
      const draft = request.postDataJSON() as {
        classroom_class_id: string
        workspace_id: string
      }
      if (
        allocations.some(
          (row) => row.status === 'ACTIVE' && row.classroom_class_id === draft.classroom_class_id,
        )
      ) {
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
  await expect(page.getByRole('heading', { level: 1, name: 'Workspaces' })).toBeVisible({
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

function historyRow(page: Page, courseId: string): Locator {
  return page
    .getByRole('region', { name: 'Allocation history' })
    .locator('tbody tr')
    .filter({ hasText: courseId })
}

function readyRow(page: Page, courseId: string): Locator {
  return page
    .getByRole('region', { name: 'Classes ready to allocate' })
    .locator('.ws-ready__row')
    .filter({ hasText: courseId })
}

async function recordClass(page: Page, courseId: string, name: string) {
  await page.locator('.ws-manual summary').click()
  await page.locator('#classroom-course-id').fill(courseId)
  await page.locator('#classroom-name').fill(name)
  await page.getByLabel(/I have read this course from Google Classroom/).check()
  await page.getByRole('button', { name: 'Record class' }).click()
  await expect(page.getByRole('status')).toContainText('Class record succeeded.')
}

test.describe('workspaces and allocation', () => {
  test('an operator records, allocates, releases, reallocates and moves a class', async ({
    page,
  }) => {
    await open(page)

    await expect(page.getByRole('region', { name: 'Workspaces' })).toContainText(
      'Alpha workspace',
    )
    await expect(page.getByRole('region', { name: 'Workspaces' })).toContainText(
      'Beta workspace',
    )
    await expect(page.getByText('is not configured', { exact: false })).toBeVisible()

    await recordClass(page, '600100', '10A Mathematics')

    const ready = readyRow(page, '600100')
    await expect(ready).toContainText('UNVERIFIED')
    await expect(ready).toContainText('10A Mathematics')

    // The guided flow: the class is already chosen, then workspace, review and write.
    await ready.getByRole('button', { name: 'Allocate…' }).click()
    const dialog = page.locator('.ws-dialog')
    await expect(dialog.getByRole('heading', { name: 'Attach a class to a workspace' })).toBeVisible()
    await dialog.getByRole('radio', { name: /Beta workspace/ }).check()
    await dialog.getByRole('button', { name: 'Continue' }).click()
    await expect(dialog.getByRole('heading', { name: 'Review the allocation' })).toBeVisible()
    await expect(dialog).toContainText('10A Mathematics')
    await expect(dialog).toContainText('Teacher B')
    await expect(dialog).toContainText('does not invite or remove Google Classroom teachers')
    await dialog.getByLabel('Reason (optional)').fill('timetable')
    await dialog.getByRole('button', { name: 'Allocate class' }).click()

    const allocated = page.getByRole('status').filter({ hasText: 'Class allocated' })
    await expect(allocated).toContainText('Beta workspace')
    await expect(allocated).toContainText('Teacher B')
    await expect
      .poll(() => page.locator('body').getAttribute('data-platform-overview-changes'))
      .toBe('1')

    await expect(historyRow(page, '600100')).toContainText('Beta workspace')
    await expect(historyRow(page, '600100')).toContainText('ACTIVE')
    await expect(
      page.locator('.ws-card').filter({ hasText: 'Beta workspace' }).locator('.ws-classes'),
    ).toContainText('10A Mathematics')

    // Release is a confirmation, not an immediate write.
    await historyRow(page, '600100').getByRole('button', { name: 'Release…' }).click()
    const release = page.getByRole('alertdialog', { name: /Release 10A Mathematics/ })
    await expect(release).toContainText('teachers lose access')
    await release.getByRole('button', { name: 'Release allocation' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Allocation released' })).toBeVisible()
    await expect
      .poll(() => page.locator('body').getAttribute('data-platform-overview-changes'))
      .toBe('2')
    await expect(historyRow(page, '600100')).toContainText('RELEASED')
    await expect(readyRow(page, '600100')).toBeVisible()

    // A released class can be allocated again.
    await readyRow(page, '600100').getByRole('button', { name: 'Allocate…' }).click()
    await dialog.getByRole('radio', { name: /Beta workspace/ }).check()
    await dialog.getByRole('button', { name: 'Continue' }).click()
    await dialog.getByRole('button', { name: 'Allocate class' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Class allocated' })).toBeVisible()

    // Moving requires a reason and states which workspace loses access.
    await historyRow(page, '600100').getByRole('button', { name: 'Move…' }).click()
    const move = page.getByRole('dialog', { name: 'Move 10A Mathematics' })
    await expect(move).toContainText('Beta workspace')
    await move.getByLabel('Move to workspace').selectOption(ALPHA)
    await move.getByLabel('Reason (required)').fill('teacher changed')
    await move.getByRole('button', { name: 'Move class' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Class moved' })).toBeVisible()

    await expect(historyRow(page, '600100')).toHaveCount(3)
    const active = historyRow(page, '600100').filter({ hasText: 'Alpha workspace' })
    await expect(active).toContainText('ACTIVE')
    await expect(active).toContainText('moved here')
  })

  test('an empty platform explains what is missing without inventing rows', async ({ page }) => {
    await open(page)

    await expect(page.getByText('No unallocated class is recorded')).toBeVisible()
    await expect(page.getByText('No allocation matches this filter')).toBeVisible()

    await page.locator('.ws-manual summary').click()
    await expect(page.getByRole('button', { name: 'Record class' })).toBeDisabled()

    await page.getByRole('button', { name: 'Allocate a Classroom class' }).click()
    const dialog = page.locator('.ws-dialog')
    await expect(dialog).toContainText('No Classroom class is ready to allocate')
    await expect(dialog.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  test('with no workspace, allocation is withheld and explained', async ({ page }) => {
    await open(page, { workspaces: [] })

    await expect(page.getByText('No workspace exists yet')).toBeVisible()
    const allocate = page.getByRole('button', { name: 'Allocate a Classroom class' })
    await expect(allocate).toBeDisabled()
    await expect(allocate).toHaveAttribute(
      'title',
      'A workspace must exist before a class can be allocated to it.',
    )
  })

  test('a refused allocation stays in the dialog with the engine reason', async ({ page }) => {
    await open(page, { failAllocate: true })
    await recordClass(page, '600101', '10B Mathematics')

    await readyRow(page, '600101').getByRole('button', { name: 'Allocate…' }).click()
    const dialog = page.locator('.ws-dialog')
    await dialog.getByRole('radio', { name: /Beta workspace/ }).check()
    await dialog.getByRole('button', { name: 'Continue' }).click()
    await dialog.getByRole('button', { name: 'Allocate class' }).click()

    await expect(dialog.getByRole('alert')).toContainText(
      'That class already has an active allocation.',
    )
    await expect(dialog).toBeVisible()
    await expect(historyRow(page, '600101')).toHaveCount(0)
  })

  test('an unavailable engine is reported instead of an empty page', async ({ page }) => {
    await open(page, { unavailable: true })

    await expect(
      page.getByRole('heading', { name: 'The correction engine is not available.' }),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' }).first()).toBeVisible()
    await expect(page.locator('.ws-card')).toHaveCount(0)
  })

  test('permission denial is reported without any allocation controls', async ({ page }) => {
    await open(page, { deny: true })

    await expect(
      page.getByRole('heading', {
        name: 'Platform authority is required to read workspaces',
      }),
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Allocate a Classroom class' }),
    ).toHaveCount(0)
  })
})
