import type { BrowserContext, Page } from '@playwright/test'
import { LEGAL_DOCUMENTS, LEGAL_REQUIRED_DOCUMENTS, type LegalDocumentId } from '../../src/lib/legal'

/**
 * The authenticated application reads legal acceptance from
 * `public.legal_acceptances` on every load. Specs that sign a seeded session in
 * must therefore answer that request; a real Supabase project would reject the
 * synthetic token, and the gate would (correctly) refuse the workspace.
 *
 * The stub mirrors the database contract: a GET returns the rows this account
 * has accepted, and an upsert adds rows with a server-side timestamp. It does
 * not bypass RLS — RLS is exercised separately against the real database by
 * `supabase/tests/legal_acceptances_rls.py`.
 */

export const TEST_USER_ID = '00000000-0000-4000-8000-000000000001'

export type AcceptanceRow = {
  user_id: string
  document_type: string
  document_version: string
  accepted_at: string
}

/** Rows for every required document at its current version. */
export function acceptedRows(
  overrides: Partial<Record<LegalDocumentId, string>> = {},
): AcceptanceRow[] {
  return Object.entries(LEGAL_REQUIRED_DOCUMENTS).map(([documentType, id]) => ({
    user_id: TEST_USER_ID,
    document_type: documentType,
    document_version: overrides[id] ?? LEGAL_DOCUMENTS[id].version,
    accepted_at: '2026-11-13T09:00:00.000Z',
  }))
}

export type StubOptions = {
  /** Rows the account already has. Pass `[]` for a first-time account. */
  rows?: AcceptanceRow[]
  /** Make the read fail, as an unavailable database would. */
  readFailure?: boolean
  /** Make the write fail while reads keep working. */
  writeFailure?: boolean
}

export async function stubLegalAcceptance(
  target: Page | BrowserContext,
  options: StubOptions = {},
): Promise<void> {
  const rows = [...(options.rows ?? acceptedRows())]

  await target.route('**/rest/v1/legal_acceptances**', async (route) => {
    const request = route.request()

    if (request.method() === 'GET') {
      if (options.readFailure) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ message: 'Service unavailable' }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(rows),
      })
      return
    }

    if (options.writeFailure) {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'new row violates row-level security policy' }),
      })
      return
    }

    const submitted = JSON.parse(request.postData() ?? '[]') as Array<{
      user_id: string
      document_type: string
      document_version: string
    }>
    for (const record of Array.isArray(submitted) ? submitted : [submitted]) {
      if (
        rows.some(
          (row) =>
            row.document_type === record.document_type &&
            row.document_version === record.document_version,
        )
      ) {
        continue
      }
      rows.push({
        ...record,
        accepted_at: new Date().toISOString(),
      })
    }
    await route.fulfill({ status: 201, body: '' })
  })
}
