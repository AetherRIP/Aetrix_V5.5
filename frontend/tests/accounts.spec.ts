import { expect, test } from './support/fixtures'
import type { Page } from '@playwright/test'

/**
 * Platform account management.
 *
 * Supabase's account API is intercepted here, so each test states the identity
 * provider's answer explicitly. The security claims under test are the ones the
 * screen can make: platform owner sees every account, an administrator is
 * offered only the roles it may grant, an account cannot edit itself, and a
 * missing service-role key is reported instead of replaced with workspace rows.
 */

type Role = 'owner' | 'platform_operator' | 'supervisor'

const SELF_ID = '00000000-0000-4000-8000-000000000001'

function session(role: Role) {
  const now = Math.floor(Date.now() / 1000)
  return {
    access_token: 'test-access-token',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: 4102444800,
    refresh_token: 'test-refresh-token',
    user: {
      id: SELF_ID,
      aud: 'authenticated',
      role: 'authenticated',
      email: role === 'owner' ? 'owner@aetrix.test' : `${role}@aetrix.test`,
      email_confirmed_at: new Date(now * 1000).toISOString(),
      phone: '',
      confirmed_at: new Date(now * 1000).toISOString(),
      last_sign_in_at: new Date(now * 1000).toISOString(),
      app_metadata: { provider: 'google', aetrix_role: role },
      user_metadata: { full_name: 'Operator One', name: 'Operator One' },
      identities: [],
      created_at: new Date(now * 1000).toISOString(),
      updated_at: new Date(now * 1000).toISOString(),
    },
  }
}

async function signIn(page: Page, role: Role) {
  await page.addInitScript((value) => {
    window.localStorage.setItem('aetrix:auth', JSON.stringify(value))
  }, session(role))
}

type Account = {
  id: string
  email: string
  display_name: string
  role: 'owner' | 'platform_operator' | 'supervisor' | 'assistant' | 'viewer' | 'unassigned'
  status: 'ACTIVE' | 'SUSPENDED' | 'UNCONFIRMED'
  created_at: string
  updated_at: string | null
  last_sign_in_at: string | null
  email_confirmed_at: string | null
  banned_until: string | null
  memberships: {
    tenant_id: string
    workspace_name: string
    workspace_slug: string
    role: string
    is_demo: boolean
    user_row_id: string
    joined_at: string
  }[]
  workspace_count: number
  has_workspace: boolean
  pending_invitation_count: number
}

const ADA: Account = {
  id: '00000000-0000-4000-8000-0000000000a1',
  email: 'ada@aetrix.test',
  display_name: 'Ada Lovelace',
  role: 'platform_operator',
  status: 'ACTIVE',
  created_at: '2026-01-02T03:04:05Z',
  updated_at: '2026-02-01T00:00:00Z',
  last_sign_in_at: '2026-11-09T10:00:00Z',
  email_confirmed_at: '2026-01-02T03:05:00Z',
  banned_until: null,
  memberships: [],
  workspace_count: 0,
  has_workspace: false,
  pending_invitation_count: 0,
}

const BO: Account = {
  id: '00000000-0000-4000-8000-0000000000b2',
  email: 'bo@aetrix.test',
  display_name: 'Bo Chen',
  role: 'viewer',
  status: 'SUSPENDED',
  created_at: '2026-01-03T03:04:05Z',
  updated_at: null,
  last_sign_in_at: null,
  email_confirmed_at: '2026-01-03T03:05:00Z',
  banned_until: '2126-01-03T03:05:00Z',
  memberships: [
    {
      tenant_id: '00000000-0000-4000-8000-000000000010',
      workspace_name: 'Alpha workspace',
      workspace_slug: 'alpha',
      role: 'TEACHER',
      is_demo: false,
      user_row_id: '00000000-0000-4000-8000-0000000000c3',
      joined_at: '2026-01-04T09:00:00Z',
    },
    {
      tenant_id: '00000000-0000-4000-8000-000000000011',
      workspace_name: 'Beta workspace',
      workspace_slug: 'beta',
      role: 'REVIEWER',
      is_demo: false,
      user_row_id: '00000000-0000-4000-8000-0000000000c4',
      joined_at: '2026-02-05T09:00:00Z',
    },
  ],
  workspace_count: 2,
  has_workspace: true,
  pending_invitation_count: 0,
}

const SELF: Account = {
  ...ADA,
  id: SELF_ID,
  email: 'platform_operator@aetrix.test',
  display_name: 'Operator One',
}

const OVERVIEW = {
  generated_at: '2026-11-10T12:00:00Z',
  metrics: [],
  account_census: {
    available: true,
    captured_at: '2026-11-10T11:59:30Z',
    cached: false,
    active_accounts: 2,
    reason: null,
  },
}

const AUDIT = [
  {
    id: '00000000-0000-4000-8000-0000000000d4',
    action: 'account.role_changed',
    actor_subject: 'owner-subject',
    actor_platform_role: 'PLATFORM_OWNER',
    target_subject: BO.id,
    target_email: BO.email,
    detail: { previous_role: 'assistant', role: 'viewer' },
    created_at: '2026-11-01T12:00:00Z',
  },
]

async function open(
  page: Page,
  role: Role,
  options: { configured?: boolean; selfIsOperator?: boolean } = {},
) {
  const { configured = true, selfIsOperator = false } = options
  const seen = { query: '' }
  const accounts: Account[] = selfIsOperator ? [SELF, BO] : [ADA, BO]

  const detail = (id: string | undefined) => {
    const base = accounts.find((account) => account.id === id) ?? BO
    return {
      ...base,
      invitations: [],
      audit: base.id === BO.id ? AUDIT : [],
    }
  }

  await signIn(page, role)
  await page.route('**/api/v1/admin/accounts**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      })

    if (path.endsWith('/capability')) {
      return json({
        configured,
        reason: configured
          ? 'Reading accounts and changing them happens through the Supabase Auth administration API.'
          : 'AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY and AETRIX_PLATFORM_ADMIN__SUPABASE_URL are not set on the engine.',
        operations: [
          {
            name: 'list and inspect accounts',
            supported: configured,
            note: 'Supabase Auth users, including creation and last sign-in.',
          },
          {
            name: 'revoke sessions',
            supported: false,
            note: 'Supabase Auth has no service-role endpoint to revoke sessions.',
          },
        ],
      })
    }
    if (request.method() !== 'GET') {
      if (path.endsWith('/role')) {
        // The real route answers with the account and the effect of the change
        // on every membership row. Alpha moves; Beta is already REVIEWER.
        const account = detail(path.split('/').slice(-2)[0])
        return json({
          account,
          memberships: account.memberships.map((membership) =>
            membership.workspace_slug === 'alpha'
              ? {
                  state: 'changed',
                  reason: `Workspace membership moved from ${membership.role} to REVIEWER.`,
                  workspace_name: membership.workspace_name,
                  workspace_slug: membership.workspace_slug,
                  user_row_id: membership.user_row_id,
                  previous_role: membership.role,
                  role: 'REVIEWER',
                }
              : {
                  state: 'skipped',
                  reason: `The workspace role is already ${membership.role}.`,
                  workspace_name: membership.workspace_name,
                  workspace_slug: membership.workspace_slug,
                  user_row_id: membership.user_row_id,
                  previous_role: membership.role,
                  role: membership.role,
                },
          ),
        })
      }
      return json({ status: 'OK', message: 'Recorded.' })
    }
    if (path.endsWith('/accounts')) {
      seen.query = url.search
      return json({
        items: accounts,
        total: accounts.length,
        page: 1,
        page_size: 50,
        source: 'supabase-auth',
        truncated: false,
      })
    }
    return json(detail(path.split('/').pop()))
  })

  const response = await page.goto('/platform/users', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  // The seeded session is hydrated on the client. Asserting before the shell has
  // resolved would read the "Checking your session" state, not this screen.
  await expect(page.getByRole('heading', { level: 1, name: 'Account management' })).toBeVisible({
    timeout: 30_000,
  })
  await page.evaluate(() => {
    document.body.dataset.platformOverviewChanges = '0'
    window.addEventListener('aetrix:platform-overview-changed', () => {
      const current = Number(document.body.dataset.platformOverviewChanges ?? '0')
      document.body.dataset.platformOverviewChanges = String(current + 1)
    })
  })
  return seen
}

test.describe('platform account management', () => {
  test('the owner sees every account and inspects memberships and activity', async ({ page }) => {
    await open(page, 'owner')

    await expect(page.getByText('ada@aetrix.test')).toBeVisible()
    await expect(page.getByText('bo@aetrix.test')).toBeVisible()

    const adaRow = page.locator('.data-table tbody tr').filter({ hasText: 'ada@aetrix.test' })
    await expect(adaRow.getByText('Administrator')).toBeVisible()
    // Ada is in no workspace; that is stated, not rendered as a zero.
    await expect(adaRow.getByText('None')).toBeVisible()

    const boRow = page.locator('.data-table tbody tr').filter({ hasText: 'bo@aetrix.test' })
    await expect(boRow.getByText('SUSPENDED')).toBeVisible()
    await boRow.getByRole('button', { name: 'Inspect' }).click()

    await expect(page.getByRole('heading', { name: 'Workspace memberships' })).toBeVisible()
    await expect(page.getByText('Alpha workspace')).toBeVisible()
    await expect(page.getByText('workspace role TEACHER')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Platform activity' })).toBeVisible()
    await expect(page.getByText('account.role_changed')).toBeVisible()
  })

  test('a role change shows the changed and skipped membership rows', async ({ page }) => {
    await open(page, 'owner')
    page.on('dialog', (dialog) => void dialog.accept())

    await page
      .locator('.data-table tbody tr')
      .filter({ hasText: 'bo@aetrix.test' })
      .getByRole('button', { name: 'Inspect' })
      .click()

    await page.getByLabel('New platform role').selectOption('assistant')
    await page.getByRole('button', { name: 'Change role' }).click()

    await expect(page.getByText('Workspace membership effect')).toBeVisible()
    await expect(page.getByText('changed', { exact: true })).toBeVisible()
    await expect(page.getByText('skipped', { exact: true })).toBeVisible()
    await expect(
      page.getByText('Alpha workspace: workspace role TEACHER → REVIEWER'),
    ).toBeVisible()
    await expect(
      page.getByText('Beta workspace: The workspace role is already REVIEWER.'),
    ).toBeVisible()
    await expect(
      page.getByText('Platform role saved; 1 workspace membership row moved.'),
    ).toBeVisible()
  })

  test('search and status filters travel to the engine as query parameters', async ({ page }) => {
    const seen = await open(page, 'owner')

    await page.getByLabel('Search').fill('ada')
    await page.getByRole('button', { name: 'Search', exact: true }).click()
    await expect.poll(() => new URLSearchParams(seen.query).get('q')).toBe('ada')

    await page.getByLabel('Status').selectOption('SUSPENDED')
    await expect.poll(() => new URLSearchParams(seen.query).get('status')).toBe('SUSPENDED')
  })

  test('without a credential the screen reports it and shows no account table', async ({ page }) => {
    await open(page, 'owner', { configured: false })

    await expect(
      page.getByRole('heading', {
        name: 'Platform-wide accounts need a Supabase service-role key',
      }),
    ).toBeVisible()
    await expect(page.getByText(/AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY/).first()).toBeVisible()
    await expect(page.locator('.data-table')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Inspect' })).toHaveCount(0)
  })

  test('an administrator is offered only the roles and actions it may use', async ({ page }) => {
    await open(page, 'platform_operator')

    await page
      .locator('.data-table tbody tr')
      .filter({ hasText: 'bo@aetrix.test' })
      .getByRole('button', { name: 'Inspect' })
      .click()

    // The account is suspended, so the offered action is the reactivation.
    await expect(page.getByRole('button', { name: 'Reactivate account' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Delete account' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Send recovery email' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Revoke sessions' })).toBeDisabled()

    const roleSelect = page.getByLabel('New platform role')
    await expect(roleSelect.locator('option', { hasText: 'Administrator' })).toHaveCount(0)
    await expect(roleSelect.locator('option', { hasText: 'Teacher' })).toHaveCount(1)
  })

  test('an administrator cannot change their own platform role', async ({ page }) => {
    await open(page, 'platform_operator', { selfIsOperator: true })

    await page
      .locator('.data-table tbody tr')
      .filter({ hasText: 'platform_operator@aetrix.test' })
      .getByRole('button', { name: 'Inspect' })
      .click()

    await expect(page.getByText(/This is your own account/)).toBeVisible()
    await expect(page.getByLabel('New platform role')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Suspend account' })).toHaveCount(0)
  })

  test('a successful account change announces a platform overview refresh', async ({
    page,
  }) => {
    await open(page, 'owner')
    page.on('dialog', (dialog) => void dialog.accept())

    await page
      .locator('.data-table tbody tr')
      .filter({ hasText: 'bo@aetrix.test' })
      .getByRole('button', { name: 'Inspect' })
      .click()
    await page.getByRole('button', { name: 'Reactivate account' }).click()

    await expect
      .poll(() => page.locator('body').getAttribute('data-platform-overview-changes'))
      .toBe('1')
    await expect
      .poll(() =>
        page.evaluate(() => sessionStorage.getItem('aetrix:platform-overview-stale')),
      )
      .toBe('1')
  })

  test('a successful account change refreshes an overview open in another tab', async ({
    page,
    context,
  }) => {
    await open(page, 'owner')

    const other = await context.newPage()
    await signIn(other, 'owner')
    const overviewRequests: string[] = []
    await other.route('**/api/v1/admin/overview**', (route) => {
      overviewRequests.push(route.request().url())
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(OVERVIEW),
      })
    })
    const response = await other.goto('/platform', { waitUntil: 'load' })
    expect(response?.status()).toBe(200)
    await expect(
      other.getByRole('heading', { name: 'Platform overview' }),
    ).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => overviewRequests.length).toBeGreaterThan(0)
    await other.waitForTimeout(200)
    const beforeChange = overviewRequests.length

    page.on('dialog', (dialog) => void dialog.accept())
    await page
      .locator('.data-table tbody tr')
      .filter({ hasText: 'bo@aetrix.test' })
      .getByRole('button', { name: 'Inspect' })
      .click()
    await page.getByRole('button', { name: 'Reactivate account' }).click()

    await expect.poll(() => overviewRequests.length).toBeGreaterThan(beforeChange)
    expect(overviewRequests.at(-1)).toContain('refresh=true')
  })

  test('a teacher is sent to the workspace and never sees the section', async ({ page }) => {
    await signIn(page, 'supervisor')
    await page.goto('/platform/users', { waitUntil: 'load' })

    await expect(page).toHaveURL(/\/dashboard\/?$/, { timeout: 20_000 })
    await expect(
      page.locator('.app-nav').getByRole('link', { name: 'Account management' }),
    ).toHaveCount(0)
  })
})
