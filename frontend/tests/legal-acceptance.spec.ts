import { expect, test, type Page } from '@playwright/test'
import {
  TEST_USER_ID,
  acceptedRows,
  stubLegalAcceptance,
} from './support/legal-acceptance'

/**
 * The acceptance gate is the one place the workspace can be entered, and its
 * source of truth is `public.legal_acceptances`. These tests drive the interface
 * against the database contract (answered by the stub) and assert what is sent:
 * the account id, the document types and the current versions — never a
 * client-supplied timestamp.
 *
 * The access rules themselves (RLS, grants, duplicate rejection) are verified
 * against the real database by `supabase/tests/legal_acceptances_rls.py`.
 */

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

/** The app shell's content region, which the gate replaces entirely. */
const workspace = (page: Page) => page.locator('#app-content')
const gate = (page: Page) => page.locator('.legal-gate')

function acceptancesWritten(page: Page) {
  const writes: Array<Array<Record<string, unknown>>> = []
  const reads: string[] = []
  page.on('request', (request) => {
    if (!request.url().includes('/rest/v1/legal_acceptances')) return
    if (request.method() === 'GET') reads.push(request.url())
    if (request.method() === 'POST') {
      const body = JSON.parse(request.postData() ?? '[]')
      writes.push(Array.isArray(body) ? body : [body])
    }
  })
  return { writes, reads }
}

test.describe('legal acceptance', () => {
  test('a first sign-in asks for acceptance before the workspace opens', async ({ page }) => {
    await signInAsOwner(page)
    await stubLegalAcceptance(page, { rows: [] })
    await page.goto('/dashboard', { waitUntil: 'load' })

    await expect(
      page.getByRole('heading', { name: 'Accept the documents to continue' }),
    ).toBeVisible()
    await expect(page.getByRole('checkbox')).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Accept and continue' })).toBeDisabled()

    // The workspace is not rendered underneath the gate.
    await expect(workspace(page)).toHaveCount(0)
  })

  test('accepting records the current versions against the account and opens the workspace', async ({
    page,
  }) => {
    await signInAsOwner(page)
    await stubLegalAcceptance(page, { rows: [] })
    const { writes } = acceptancesWritten(page)
    await page.goto('/dashboard', { waitUntil: 'load' })

    await page.getByRole('checkbox', { name: /Terms of Service/ }).check()
    await page.getByRole('checkbox', { name: /Privacy Policy/ }).check()
    const submit = page.getByRole('button', { name: 'Accept and continue' })
    await expect(submit).toBeEnabled()
    await submit.click()

    await expect(workspace(page)).toBeVisible()
    await expect(gate(page)).toHaveCount(0)

    expect(writes).toHaveLength(1)
    const records = writes[0]
    expect(
      records.map((record) => [record.document_type, record.document_version]),
    ).toEqual([
      ['terms_of_service', '1.0'],
      ['privacy_policy', '1.0'],
    ])
    expect(records.every((record) => record.user_id === TEST_USER_ID)).toBe(true)
    // The timestamp is the server's; the browser never sends one.
    expect(records.every((record) => !('accepted_at' in record))).toBe(true)
  })

  test('a returning account is not asked again', async ({ page }) => {
    await signInAsOwner(page)
    await stubLegalAcceptance(page, { rows: acceptedRows() })
    await page.goto('/dashboard', { waitUntil: 'load' })

    await expect(workspace(page)).toBeVisible()
    await expect(gate(page)).toHaveCount(0)
    await expect(page.getByRole('checkbox')).toHaveCount(0)
  })

  test('a browser refresh does not ask again', async ({ page }) => {
    await signInAsOwner(page)
    await stubLegalAcceptance(page, { rows: acceptedRows() })
    await page.goto('/dashboard', { waitUntil: 'load' })
    await expect(workspace(page)).toBeVisible()

    await page.reload({ waitUntil: 'load' })

    await expect(workspace(page)).toBeVisible()
    await expect(gate(page)).toHaveCount(0)
  })

  test('clearing browser storage and signing in again does not ask again', async ({
    page,
  }) => {
    await signInAsOwner(page)
    await stubLegalAcceptance(page, { rows: acceptedRows() })
    await page.goto('/dashboard', { waitUntil: 'load' })
    await expect(workspace(page)).toBeVisible()

    // The acceptance lives in the database, so losing every value on this device
    // — the session included — must not change the answer for this account.
    await page.evaluate(() => window.localStorage.clear())
    await signInAsOwner(page)
    await page.reload({ waitUntil: 'load' })

    await expect(workspace(page)).toBeVisible()
    await expect(gate(page)).toHaveCount(0)
  })

  test('only the document whose version changed is requested again', async ({ page }) => {
    await signInAsOwner(page)
    // The Privacy Policy is current; the Terms accepted at 0.9 are stale.
    await stubLegalAcceptance(page, {
      rows: acceptedRows({ terms: '0.9' }),
    })
    const { writes } = acceptancesWritten(page)
    await page.goto('/dashboard', { waitUntil: 'load' })

    const checkboxes = page.getByRole('checkbox')
    await expect(checkboxes).toHaveCount(1)
    await expect(checkboxes.first()).toHaveAccessibleName(/Terms of Service/)
    await expect(page.locator('.legal-gate__docs')).toContainText('version 1.0')

    await checkboxes.first().check()
    await page.getByRole('button', { name: 'Accept and continue' }).click()
    await expect(workspace(page)).toBeVisible()

    expect(writes.flat().map((record) => record.document_type)).toEqual([
      'terms_of_service',
    ])
    expect(writes.flat()[0].document_version).toBe('1.0')
  })

  test('an unavailable database does not grant access', async ({ page }) => {
    await signInAsOwner(page)
    await stubLegalAcceptance(page, { readFailure: true })
    await page.goto('/dashboard', { waitUntil: 'load' })

    await expect(
      page.getByRole('heading', { name: 'Your acceptance could not be checked' }),
    ).toBeVisible()
    await expect(page.getByRole('alert')).toContainText('could not be read')
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
    await expect(workspace(page)).toHaveCount(0)
  })

  test('a failed write keeps the workspace closed and is reported', async ({ page }) => {
    await signInAsOwner(page)
    await stubLegalAcceptance(page, { rows: [], writeFailure: true })
    await page.goto('/dashboard', { waitUntil: 'load' })

    await page.getByRole('checkbox', { name: /Terms of Service/ }).check()
    await page.getByRole('checkbox', { name: /Privacy Policy/ }).check()
    await page.getByRole('button', { name: 'Accept and continue' }).click()

    await expect(page.getByRole('alert')).toContainText(
      'refused to record the acceptance for this account',
    )
    await expect(
      page.getByRole('heading', { name: 'Accept the documents to continue' }),
    ).toBeVisible()
    await expect(workspace(page)).toHaveCount(0)
  })

  test('an anonymous visitor is sent to sign-in, not to the acceptance gate', async ({
    page,
  }) => {
    await stubLegalAcceptance(page, { rows: [] })
    const { reads, writes } = acceptancesWritten(page)
    await page.goto('/dashboard', { waitUntil: 'load' })

    await expect(page).toHaveURL(/\/sign-in/)
    await expect(gate(page)).toHaveCount(0)
    expect(reads).toHaveLength(0)
    expect(writes).toHaveLength(0)
  })
})
