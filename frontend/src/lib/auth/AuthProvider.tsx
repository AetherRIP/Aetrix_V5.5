import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { AUTH_UNAVAILABLE_REASON } from '../env'
import { AUTH_CALLBACK_PATH, getSupabase } from '../supabase'
import {
  clearAddingAccount,
  forgetAccount,
  markAddingAccount,
  readAccounts,
  readAddIntent,
  rememberAccount,
  summarise,
  type AccountRecord,
  type SavedAccount,
  type SavedAccountSummary,
} from './accounts'
import { readRole, type AccountRole } from './roles'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'unconfigured'

export type SwitchAccountResult = {
  ok: boolean
  message?: string
  /** The claim role of the account now in use, so a caller can pick a screen it may open. */
  role?: AccountRole | null
}

export type AuthValue = {
  status: AuthStatus
  session: Session | null
  user: User | null
  /** Message from a failed or cancelled round-trip, shown on the sign-in page. */
  error: string | null
  authUnavailableReason: string | null
  /** Every account saved on this device, newest first. Tokens are never exposed. */
  accounts: SavedAccountSummary[]
  /**
   * True while a Google round-trip is adding a second account and the new
   * session has not arrived yet. The callback screen waits on it instead of
   * forwarding on the account that was already signed in.
   */
  addingAccount: boolean
  signInWithGoogle: (nextPath?: string) => Promise<void>
  signInWithPassword: (
    email: string,
    password: string,
  ) => Promise<{ ok: boolean; message?: string; role?: AccountRole | null }>
  /** Reopens a saved account. The engine re-resolves everything from its token. */
  switchAccount: (id: string) => Promise<SwitchAccountResult>
  /** Drops a saved account from this device without touching the account. */
  forgetAccount: (id: string) => void
  /**
   * Signs the current account out. When another account is saved, it is opened
   * instead of leaving the user at the sign-in page; the result says which
   * happened, so a caller can tell whether the browser is still signed in.
   */
  signOut: () => Promise<boolean>
  dismissError: () => void
}

const AuthContext = createContext<AuthValue | null>(null)

/** Where to send the user after the OAuth round-trip. */
const NEXT_PATH_KEY = 'aetrix:auth-next'

const MESSAGES: Record<string, string> = {
  access_denied: 'Google sign-in was cancelled or denied. No account was changed.',
  invalid_request: 'The sign-in request was rejected. Try again.',
  server_error: 'The identity provider reported a server error. Try again shortly.',
  temporarily_unavailable: 'Sign-in is temporarily unavailable. Try again shortly.',
}

function humanise(raw: string | null): string {
  if (!raw) return 'Sign-in did not complete. Try again.'
  const key = raw.toLowerCase().replace(/\s+/g, '_')
  if (MESSAGES[key]) return MESSAGES[key]
  if (raw.includes('Invalid login credentials')) {
    return 'That email and password combination was not accepted.'
  }
  if (raw.includes('Email not confirmed')) {
    return 'That account still needs its email confirmation before signing in.'
  }
  return raw
}

export function storeNextPath(path: string | undefined): void {
  if (typeof window === 'undefined') return
  // Normalise a trailing slash so a directory-style URL from static hosting
  // does not produce a doubled path when it is used as a destination.
  const normalised = path ? path.replace(/\/+$/, '') : ''
  if (normalised && normalised !== '' && path?.startsWith('/')) {
    window.sessionStorage.setItem(NEXT_PATH_KEY, normalised || '/')
  } else {
    window.sessionStorage.removeItem(NEXT_PATH_KEY)
  }
}

/** Reads the pending destination without clearing it. */
export function peekNextPath(): string {
  if (typeof window === 'undefined') return '/dashboard'
  const value = window.sessionStorage.getItem(NEXT_PATH_KEY)
  return value && value.startsWith('/') ? value : '/dashboard'
}

/** Reads the pending destination and clears it, so it is used exactly once. */
export function takeNextPath(): string {
  const value = peekNextPath()
  if (typeof window !== 'undefined') window.sessionStorage.removeItem(NEXT_PATH_KEY)
  return value
}

/** A session in the shape the vault stores. */
function toRecord(session: Session): AccountRecord {
  const meta = (session.user.user_metadata ?? {}) as Record<string, unknown>
  return {
    id: session.user.id,
    email: session.user.email ?? '',
    name: displayName(session.user),
    avatarUrl: typeof meta.avatar_url === 'string' ? meta.avatar_url : null,
    accessToken: session.access_token,
    refreshToken: session.refresh_token ?? '',
    expiresAt: session.expires_at ?? null,
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const supabase = useMemo(() => getSupabase(), [])
  const [session, setSession] = useState<Session | null>(null)
  const [status, setStatus] = useState<AuthStatus>(supabase ? 'loading' : 'unconfigured')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<SavedAccount[]>([])
  const [addingAccount, setAddingAccount] = useState(false)
  // A handover is a load, not an absence: the guard must not bounce the browser
  // to /sign-in between revoking one session and opening the next.
  const [handover, setHandover] = useState(false)

  // The vault is device state, so it is read after mount rather than during
  // rendering. Until then the menu simply has no saved accounts to list.
  useEffect(() => {
    setSaved(readAccounts())
  }, [])

  const remember = useCallback((next: Session | null) => {
    // Only a session with a refresh token can be reopened later.
    if (!next?.refresh_token) return
    setSaved(rememberAccount(toRecord(next)))
  }, [])

  useEffect(() => {
    if (!supabase || typeof window === 'undefined') return

    let active = true

    // A cancelled or failed OAuth round-trip comes back as URL parameters.
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const query = new URLSearchParams(window.location.search)
    const urlError =
      hash.get('error_description') ??
      query.get('error_description') ??
      hash.get('error') ??
      query.get('error')
    if (urlError) {
      // The round-trip ended without a session for the new account, so there is
      // nothing left to wait for.
      clearAddingAccount()
      setAddingAccount(false)
      setError(humanise(urlError))
    } else if (readAddIntent()) {
      setAddingAccount(true)
    }

    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (!active) return
        setSession(data.session)
        setStatus(data.session ? 'authenticated' : 'anonymous')
        remember(data.session)
      })
      .catch(() => {
        if (active) setStatus('anonymous')
      })

    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      setSession(nextSession)
      setStatus(nextSession ? 'authenticated' : 'anonymous')
      if (nextSession) setError(null)
      remember(nextSession)
      // SIGNED_IN is the exchange that finishes an add-account round-trip: from
      // here the callback may forward on the session it now holds.
      if (event === 'SIGNED_IN') {
        clearAddingAccount()
        setAddingAccount(false)
      }
    })

    return () => {
      active = false
      data.subscription.unsubscribe()
    }
  }, [supabase, remember])

  const signInWithGoogle = useCallback(
    async (nextPath?: string) => {
      setError(null)
      if (!supabase || typeof window === 'undefined') {
        setError(AUTH_UNAVAILABLE_REASON)
        return
      }
      storeNextPath(nextPath)
      // Recorded before the redirect so the callback knows this is a second
      // account rather than a fresh sign-in that already has a session.
      markAddingAccount(session?.user.id ?? null)
      setAddingAccount(true)

      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}${AUTH_CALLBACK_PATH}`,
          queryParams: { prompt: 'select_account' },
        },
      })

      if (oauthError) {
        clearAddingAccount()
        setAddingAccount(false)
        setError(humanise(oauthError.message))
      }
    },
    [supabase, session],
  )

  const signInWithPassword = useCallback(
    async (email: string, password: string) => {
      if (!supabase) return { ok: false, message: AUTH_UNAVAILABLE_REASON }
      // The account already signed in stays in the vault, so signing in with a
      // second email adds it rather than replacing it.
      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      })
      if (signInError) return { ok: false, message: humanise(signInError.message) }
      return { ok: true, role: readRole(data.user) }
    },
    [supabase],
  )

  /**
   * Hands one saved session back to the client. Shared by switching and sign-out.
   *
   * `dead` means the identity provider rejected the token (revoked, or rotated by
   * another browser), so the entry is dropped. `unavailable` means it could not
   * be reached at all: that is retryable, so the account stays saved.
   */
  const openSaved = useCallback(
    async (
      account: SavedAccount,
    ): Promise<{ status: 'ok'; role: AccountRole | null } | { status: 'dead' | 'unavailable' }> => {
      if (!supabase) return { status: 'unavailable' }
      const { data, error: failure } = await supabase.auth.setSession({
        access_token: account.accessToken,
        refresh_token: account.refreshToken,
      })
      if (!failure && data.session) {
        setSession(data.session)
        setStatus('authenticated')
        remember(data.session)
        return { status: 'ok', role: readRole(data.session.user) }
      }
      const rejected =
        !failure || failure.status === 400 || failure.status === 401 || failure.status === 403
      if (rejected) {
        setSaved(forgetAccount(account.id))
        return { status: 'dead' }
      }
      return { status: 'unavailable' }
    },
    [supabase, remember],
  )

  const switchAccount = useCallback(
    async (id: string): Promise<SwitchAccountResult> => {
      if (!supabase) return { ok: false, message: AUTH_UNAVAILABLE_REASON }
      if (session?.user.id === id) return { ok: true }
      const account = readAccounts().find((entry) => entry.id === id)
      if (!account) {
        return { ok: false, message: 'That account is no longer saved on this device.' }
      }
      setError(null)
      setHandover(true)
      const opened = await openSaved(account)
      setHandover(false)
      if (opened.status === 'ok') return { ok: true, role: opened.role }
      return {
        ok: false,
        message:
          opened.status === 'dead'
            ? 'That account has to sign in again before it can be used here.'
            : 'The identity provider could not be reached, so that account was not opened. Try again.',
      }
    },
    [supabase, session, openSaved],
  )

  const forgetSaved = useCallback((id: string) => {
    setSaved(forgetAccount(id))
  }, [])

  const signOut = useCallback(async (): Promise<boolean> => {
    if (typeof window !== 'undefined') window.sessionStorage.removeItem(NEXT_PATH_KEY)
    clearAddingAccount()
    setAddingAccount(false)
    if (!supabase) return false

    const leaving = session?.user.id ?? null
    // The account being signed out is revoked below, so its saved tokens are
    // dead: drop the entry and continue with whatever remains.
    const remaining = leaving ? forgetAccount(leaving) : readAccounts()
    setSaved(remaining)

    const next = remaining[0] ?? null
    setHandover(Boolean(next))
    await supabase.auth.signOut()

    let opened = false
    if (next) {
      opened = (await openSaved(next)).status === 'ok'
      if (!opened) {
        setSession(null)
        setStatus('anonymous')
      }
    }
    setHandover(false)
    return opened
  }, [supabase, session, openSaved])

  const value = useMemo<AuthValue>(
    () => ({
      status: handover ? 'loading' : status,
      session,
      user: session?.user ?? null,
      error,
      authUnavailableReason: supabase ? null : AUTH_UNAVAILABLE_REASON,
      accounts: summarise(saved),
      addingAccount,
      signInWithGoogle,
      signInWithPassword,
      switchAccount,
      forgetAccount: forgetSaved,
      signOut,
      dismissError: () => setError(null),
    }),
    [
      handover,
      status,
      session,
      error,
      supabase,
      saved,
      addingAccount,
      signInWithGoogle,
      signInWithPassword,
      switchAccount,
      forgetSaved,
      signOut,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}

/** The signed-in user's display name, falling back to the email local part. */
export function displayName(user: User | null): string {
  if (!user) return 'Unknown user'
  const meta = (user.user_metadata ?? {}) as Record<string, unknown>
  const full = typeof meta.full_name === 'string' ? meta.full_name : ''
  const name = typeof meta.name === 'string' ? meta.name : ''
  const chosen = full || name
  if (chosen) return chosen
  return user.email ? user.email.split('@')[0] : 'Signed-in user'
}

export function initials(name: string): string {
  return name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}
