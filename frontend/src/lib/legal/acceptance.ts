import type { SupabaseClient } from '@supabase/supabase-js'
import {
  LEGAL_DOCUMENTS,
  LEGAL_REQUIRED_DOCUMENTS,
  type LegalDocumentId,
} from '../legal'

/**
 * Legal acceptance, stored in `public.legal_acceptances` and read back from it.
 *
 * The browser writes through the Supabase Data API with the signed-in user's
 * own token. It never holds a service-role key, and it does not decide who may
 * read or write a row: the table's RLS policies do that, keyed on `auth.uid()`.
 *
 * The rule this module enforces for the interface is exact-version matching. An
 * acceptance of Terms 1.0 satisfies a required 1.0 and nothing else, so bumping
 * a document to 1.1 asks for that document again without touching the others.
 */

export type LegalAcceptanceRow = {
  document_type: string
  document_version: string
  accepted_at: string
}

export type RequiredAcceptance = {
  /** Stored identifier, e.g. `terms_of_service`. */
  documentType: string
  documentId: LegalDocumentId
  title: string
  version: string
}

export const REQUIRED_ACCEPTANCES: readonly RequiredAcceptance[] = Object.entries(
  LEGAL_REQUIRED_DOCUMENTS,
).map(([documentType, documentId]) => ({
  documentType,
  documentId,
  title: LEGAL_DOCUMENTS[documentId].title,
  version: LEGAL_DOCUMENTS[documentId].version,
}))

/** Documents whose current version has no matching acceptance row. */
export function missingAcceptances(
  rows: readonly LegalAcceptanceRow[],
): RequiredAcceptance[] {
  return REQUIRED_ACCEPTANCES.filter(
    (required) =>
      !rows.some(
        (row) =>
          row.document_type === required.documentType &&
          row.document_version === required.version,
      ),
  )
}

export type AcceptanceRead =
  | { status: 'ok'; rows: LegalAcceptanceRow[]; missing: RequiredAcceptance[] }
  | { status: 'error'; reason: string }

export type AcceptanceWrite =
  | { status: 'ok' }
  | { status: 'error'; reason: string }

function readable(message: string | undefined): string {
  const detail = (message ?? '').trim()
  if (/jwt|token|expired/i.test(detail)) {
    return 'Your session could not be verified. Sign in again to continue.'
  }
  if (/permission|policy|denied/i.test(detail)) {
    return 'The database refused to record the acceptance for this account.'
  }
  return detail
    ? `The acceptance record could not be read: ${detail}`
    : 'The acceptance record could not be read.'
}

/**
 * Reads this user's acceptance rows. The explicit `user_id` filter is for
 * determinism; RLS would return only these rows anyway.
 */
export async function readAcceptances(
  client: SupabaseClient,
  userId: string,
): Promise<AcceptanceRead> {
  try {
    const { data, error } = await client
      .from('legal_acceptances')
      .select('document_type, document_version, accepted_at')
      .eq('user_id', userId)
      // PostgREST retries 503 and network failures on its own, with backoff of
      // one to four seconds per attempt. A gate that blocks the workspace must
      // not sit silently for that long: it reports the failure straight away
      // and offers an explicit retry instead.
      .retry(false)
    if (error) return { status: 'error', reason: readable(error.message) }
    const rows = (data ?? []) as LegalAcceptanceRow[]
    return { status: 'ok', rows, missing: missingAcceptances(rows) }
  } catch {
    return {
      status: 'error',
      reason: 'The acceptance record could not be reached. Check the connection and try again.',
    }
  }
}

/**
 * Records acceptance for the documents that are still missing, then reads the
 * rows back. Access is granted only if the database now holds every required
 * version; a local flag is never enough.
 */
export async function recordAcceptances(
  client: SupabaseClient,
  userId: string,
  required: readonly RequiredAcceptance[],
): Promise<AcceptanceWrite> {
  if (required.length === 0) return { status: 'ok' }

  try {
    // The unique constraint and the RLS insert policy make this safe to retry:
    // a second tab or a duplicate submission cannot create a second row, and the
    // server, not the client, stamps the time.
    const { error } = await client.from('legal_acceptances').upsert(
      required.map((document) => ({
        user_id: userId,
        document_type: document.documentType,
        document_version: document.version,
      })),
      {
        onConflict: 'user_id,document_type,document_version',
        ignoreDuplicates: true,
      },
    )
    if (error) {
      return {
        status: 'error',
        reason: readable(error.message) || 'The acceptance could not be saved.',
      }
    }
  } catch {
    return {
      status: 'error',
      reason: 'The acceptance could not be saved. Check the connection and try again.',
    }
  }

  const confirmed = await readAcceptances(client, userId)
  if (confirmed.status === 'error') {
    return {
      status: 'error',
      reason: `The acceptance was sent but could not be confirmed. ${confirmed.reason}`,
    }
  }
  if (confirmed.missing.length > 0) {
    return {
      status: 'error',
      reason:
        'The database did not store the acceptance, so access has not been granted. Try again.',
    }
  }
  return { status: 'ok' }
}
