/**
 * Accounts this device has seen.
 *
 * Supabase persists exactly one session (`aetrix:auth`) and rotates its refresh
 * token. This module keeps only the *identity* beside it — enough to list the
 * accounts, show whose they are, and sign in to one again — so no second copy of
 * a credential exists anywhere in the browser.
 *
 * An earlier build persisted each account's access and refresh token here, which
 * meant up to five long-lived credentials sat in `localStorage` alongside the
 * active session. `localStorage` offers no protection against script execution
 * in this origin, an extension, or a later user of the same machine, so that
 * vault multiplied any XSS into account takeover. The token fields are removed
 * below, and `readAccounts` scrubs them out of a vault written by that build the
 * first time it runs on the device.
 *
 * Resuming a saved account therefore means signing in to it again. That is the
 * point: this module is a convenience, never an authority, and it holds nothing
 * that could be replayed. The engine still resolves the tenant and the role from
 * whichever account's verified token is in use.
 */

const VAULT_KEY = 'aetrix:auth-accounts'
const ADD_INTENT_KEY = 'aetrix:auth-add'

/** A device rarely needs more than a handful; the cap keeps the vault small. */
export const MAX_SAVED_ACCOUNTS = 5

/** An "add account" round-trip older than this is treated as abandoned. */
const ADD_INTENT_TTL_MS = 10 * 60 * 1000

/**
 * Fields a previous build wrote here. They are never read, and their presence is
 * what makes `readAccounts` rewrite the entry so they stop existing on disk.
 */
const LEGACY_CREDENTIAL_FIELDS = ['accessToken', 'refreshToken', 'expiresAt'] as const

export type SavedAccount = {
  /** The Supabase user id; the key that makes an account unique on a device. */
  id: string
  email: string
  name: string
  avatarUrl: string | null
  /** When this device first saved the account; orders the list. */
  addedAt: number
}

/** What the interface may show. It is the whole record, because it holds no secret. */
export type SavedAccountSummary = SavedAccount

/** A saved account without the device-local timestamp. */
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

/**
 * The identity fields of a stored entry, copied one by one.
 *
 * Copying is deliberate: a spread would carry any extra property a previous
 * build wrote — including a token — straight back into storage.
 */
function sanitise(value: unknown): SavedAccount | null {
  if (!value || typeof value !== 'object') return null
  const account = value as Record<string, unknown>
  if (!isString(account.id) || account.id.length === 0) return null
  if (!isString(account.email)) return null
  if (!isString(account.name)) return null
  if (account.avatarUrl !== null && !isString(account.avatarUrl)) return null
  if (typeof account.addedAt !== 'number') return null
  return {
    id: account.id,
    email: account.email,
    name: account.name,
    avatarUrl: account.avatarUrl,
    addedAt: account.addedAt,
  }
}

/**
 * Every account this device has seen, newest first.
 *
 * An entry that does not satisfy the stored shape is dropped rather than trusted,
 * and a vault written by a build that persisted credentials is rewritten without
 * them so the tokens stop existing on the device.
 */
export function readAccounts(): SavedAccount[] {
  const storage = store()
  if (!storage) return []
  const raw = storage.getItem(VAULT_KEY)
  if (!raw) return []

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    // A corrupted vault reads as empty; the user signs in again, nothing is invented.
    return []
  }
  if (!Array.isArray(parsed)) return []

  const accounts = parsed
    .map(sanitise)
    .filter((account): account is SavedAccount => account !== null)
    .slice(0, MAX_SAVED_ACCOUNTS)

  const heldCredential = parsed.some(
    (entry) =>
      Boolean(entry) &&
      typeof entry === 'object' &&
      LEGACY_CREDENTIAL_FIELDS.some((field) => field in (entry as Record<string, unknown>)),
  )
  if (heldCredential || accounts.length !== parsed.length) {
    // Drop the credentials (and anything malformed) from the device now, rather
    // than waiting for the account to be saved again.
    writeAccounts(accounts)
  }
  return accounts
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
 * Records that an account has signed in on this device, or updates its identity.
 *
 * The order is left alone so the list does not jump around while the user reads
 * it; only the display fields can change.
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

/**
 * Drops one account from this device. The account itself is untouched.
 *
 * Nothing credential-shaped is removed here: signing out is what revokes and
 * clears the session, and that happens in `AuthProvider`.
 */
export function forgetAccount(id: string): SavedAccount[] {
  return writeAccounts(readAccounts().filter((account) => account.id !== id))
}

export function summarise(accounts: SavedAccount[]): SavedAccountSummary[] {
  return accounts.map(({ id, email, name, avatarUrl, addedAt }) => ({
    id,
    email,
    name,
    avatarUrl,
    addedAt,
  }))
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
