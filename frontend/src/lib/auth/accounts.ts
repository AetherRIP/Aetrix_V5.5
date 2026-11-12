/**
 * Accounts saved on this device.
 *
 * Supabase persists exactly one session per browser (`aetrix:auth`). This module
 * keeps a small vault beside it, so a device can hold several signed-in accounts
 * and move between them without retyping credentials: the vault stores the same
 * session objects Supabase already persists, grouped by account, and a switch
 * hands one back to `auth.setSession`.
 *
 * It is a convenience, never an authority. Whichever account is active, the
 * engine resolves the tenant and role from that account's verified token.
 */

const VAULT_KEY = 'aetrix:auth-accounts'
const ADD_INTENT_KEY = 'aetrix:auth-add'

/** A device rarely needs more than a handful; the cap keeps the vault small. */
export const MAX_SAVED_ACCOUNTS = 5

/** An "add account" round-trip older than this is treated as abandoned. */
const ADD_INTENT_TTL_MS = 10 * 60 * 1000

export type SavedAccount = {
  /** The Supabase user id; the key that makes an account unique on a device. */
  id: string
  email: string
  name: string
  avatarUrl: string | null
  accessToken: string
  refreshToken: string
  /** Unix seconds, exactly as Supabase reports `session.expires_at`. */
  expiresAt: number | null
  /** When this device first saved the account; orders the list. */
  addedAt: number
}

/** What the interface may show: identity, never the tokens. */
export type SavedAccountSummary = Pick<SavedAccount, 'id' | 'email' | 'name' | 'avatarUrl'>

/** A session in the shape the vault stores, without the device-local timestamp. */
export type AccountRecord = Omit<SavedAccount, 'addedAt'>

/** The account a Google round-trip was started from, so a callback can tell it apart. */
export type AddAccountIntent = {
  /** The account that was active when the round-trip started; `null` if none. */
  previousUserId: string | null
  startedAt: number
}

function store(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    // Storage can be blocked by the browser; that is "no saved accounts", not a crash.
    return null
  }
}

function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isSavedAccount(value: unknown): value is SavedAccount {
  if (!value || typeof value !== 'object') return false
  const account = value as Record<string, unknown>
  return (
    isString(account.id) &&
    account.id.length > 0 &&
    isString(account.email) &&
    isString(account.name) &&
    (account.avatarUrl === null || isString(account.avatarUrl)) &&
    isString(account.accessToken) &&
    account.accessToken.length > 0 &&
    isString(account.refreshToken) &&
    account.refreshToken.length > 0 &&
    (account.expiresAt === null || typeof account.expiresAt === 'number') &&
    typeof account.addedAt === 'number'
  )
}

/**
 * Every account saved on this device, newest first. Anything that does not
 * satisfy the stored shape is dropped rather than trusted.
 */
export function readAccounts(): SavedAccount[] {
  const storage = store()
  if (!storage) return []
  const raw = storage.getItem(VAULT_KEY)
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isSavedAccount).slice(0, MAX_SAVED_ACCOUNTS)
  } catch {
    // A corrupted vault reads as empty; the user signs in again, nothing is invented.
    return []
  }
}

function writeAccounts(accounts: SavedAccount[]): SavedAccount[] {
  const storage = store()
  if (!storage) return accounts
  const capped = accounts.slice(0, MAX_SAVED_ACCOUNTS)
  try {
    storage.setItem(VAULT_KEY, JSON.stringify(capped))
  } catch {
    // A full or blocked store leaves the in-memory list as the truth for this page.
  }
  return capped
}

/**
 * Saves a session, or updates the saved one in place.
 *
 * Updating in place matters: Supabase rotates refresh tokens, so every refresh
 * must be written back or a later switch would present a dead token. The order
 * is left alone so the list does not jump around while the user reads it.
 */
export function rememberAccount(record: AccountRecord): SavedAccount[] {
  const existing = readAccounts()
  const previous = existing.find((account) => account.id === record.id)
  const saved: SavedAccount = { ...record, addedAt: previous?.addedAt ?? Date.now() }
  const next = previous
    ? existing.map((account) => (account.id === record.id ? saved : account))
    : [saved, ...existing]
  return writeAccounts(next)
}

/** Drops one account from this device. The account itself is untouched. */
export function forgetAccount(id: string): SavedAccount[] {
  return writeAccounts(readAccounts().filter((account) => account.id !== id))
}

export function summarise(accounts: SavedAccount[]): SavedAccountSummary[] {
  return accounts.map(({ id, email, name, avatarUrl }) => ({ id, email, name, avatarUrl }))
}

/** Records that a Google round-trip is being used to add an account. */
export function markAddingAccount(previousUserId: string | null): void {
  if (typeof window === 'undefined') return
  const intent: AddAccountIntent = { previousUserId, startedAt: Date.now() }
  try {
    window.sessionStorage.setItem(ADD_INTENT_KEY, JSON.stringify(intent))
  } catch {
    // Without the marker the callback simply forwards on the session it has.
  }
}

/** The pending add-account round-trip, or `null` when there is none or it went stale. */
export function readAddIntent(): AddAccountIntent | null {
  if (typeof window === 'undefined') return null
  let raw: string | null = null
  try {
    raw = window.sessionStorage.getItem(ADD_INTENT_KEY)
  } catch {
    return null
  }
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    const intent = parsed as Record<string, unknown>
    const previousUserId =
      intent.previousUserId === null || isString(intent.previousUserId)
        ? (intent.previousUserId as string | null)
        : null
    if (typeof intent.startedAt !== 'number') return null
    if (Date.now() - intent.startedAt > ADD_INTENT_TTL_MS) return null
    return { previousUserId, startedAt: intent.startedAt }
  } catch {
    return null
  }
}

export function clearAddingAccount(): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.removeItem(ADD_INTENT_KEY)
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}
