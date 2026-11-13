import { expect, test } from './support/fixtures'
import type { Page, Route } from '@playwright/test'

/**
 * Teacher dashboard Classroom allocations.
 *
 * The dashboard reads the tenant-scoped allocation endpoint; these tests state
 * the engine's answer explicitly and check that only active allocations are
 * presented, with the class details the engine returns.
 */

const OWNER_ID = '00000000-0000-4000-8000-000000000001'
const TENANT_ID = '00000000-0000-4000-8000-000000000010'

type WorkspaceAllocation = {
  id: string
  course_id: string
  class_name: string
  class_section: string | null
  verification: 'UNVERIFIED' | 'VERIFIED'
  allocated_at: string
  allocated_by_label: string | null
}

const ALLOCATIONS: WorkspaceAllocation[] = [
  {
    id: '00000000-0000-4000-8000-000000000101',
    course_id: '600100',
    class_name: '10A Mathematics',
    class_section: 'Section A',
    verification: 'UNVERIFIED',
    allocated_at: '2026-11-09T10:15:00Z',
    allocated_by_label: 'Platform operator',
  },
  {
    id: '00000000-0000-4000-8000-000000000102',
    course_id: '600200',
    class_name: '11B Physics',
    class_section: 'Section B',
    verification: 'UNVERIFIED',
    allocated_at: '2026-11-10T08:30:00Z',
    allocated_by_label: 'Platform owner',
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
      id: OWNER_ID,
      aud: 'authenticated',
      role: 'authenticated',
      email: 'ana@aetrix.test',
      email_confirmed_at: new Date(now * 1000).toISOString(),
      phone: '',
      confirmed_at: new Date(now * 1000).toISOString(),
      last_sign_in_at: new Date(now * 1000).toISOString(),
      app_metadata: { provider: 'google', aetrix_role: 'supervisor' },
      user_metadata: { full_name: 'Ana Ruiz', name: 'Ana Ruiz' },
      identities: [],
      created_at: new Date(now * 1000).toISOString(),
      updated_at: new Date(now * 1000).toISOString(),
    },
  })
}

function json(route: Route, payload: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
}

async function open(page: Page, allocations: WorkspaceAllocation[]) {
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
      ui_role: 'supervisor',
      capabilities: ['read', 'manage_exams', 'review', 'approve'],
      is_demo: false,
    }),
  )
  await page.route('**/api/v1/workspaces/*/dashboard', (route) =>
    json(route, {
      assignments: 3,
      submissions: 5,
      jobs_active: 1,
      awaiting_review: 0,
      failed_jobs: 0,
      approved_results: 2,
      recent_jobs: [],
    }),
  )
  await page.route('**/api/v1/workspaces/*/classroom-allocations', (route) =>
    json(route, allocations),
  )

  const response = await page.goto('/dashboard', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('heading', { level: 1, name: /Ana/ })).toBeVisible({
    timeout: 30_000,
  })
}

function allocationCount(page: Page) {
  return page
    .locator('.hub-stat')
    .filter({ hasText: 'Classroom classes' })
    .locator('.hub-stat__value')
}

test.describe('teacher dashboard Classroom allocations', () => {
  test('shows the active count and each allocated class', async ({ page }) => {
    await open(page, ALLOCATIONS)

    const panel = page.getByRole('region', { name: 'Classroom classes' })
    await expect(panel).toContainText('2 active')
    await expect(panel.locator('tbody tr')).toHaveCount(2)
    await expect(panel).toContainText('10A Mathematics')
    await expect(panel).toContainText('Section A')
    await expect(panel).toContainText('600100')
    await expect(panel).toContainText('11B Physics')
    await expect(panel).toContainText('Section B')
    await expect(panel).toContainText('600200')
    await expect(panel).toContainText('Platform operator')
    await expect(panel).toContainText('Platform owner')
    await expect(panel.getByText('UNVERIFIED')).toHaveCount(2)
    await expect(allocationCount(page)).toHaveText('2')
  })

  test('shows a measured zero with an explicit no-classes state', async ({ page }) => {
    await open(page, [])

    const panel = page.getByRole('region', { name: 'Classroom classes' })
    await expect(panel).toContainText('0 active')
    await expect(panel).toContainText(
      'No Google Classroom course is currently allocated to this workspace.',
    )
    await expect(allocationCount(page)).toHaveText('0')
  })
})
