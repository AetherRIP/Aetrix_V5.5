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

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'unconfigured'

export type AuthValue = {
  status: AuthStatus
  session: Session | null
  user: User | null
  /** Message from a failed or cancelled round-trip, shown on the sign-in page. */
  error: string | null
  authUnavailableReason: string | null
  signInWithGoogle: (nextPath?: string) => Promise<void>
  signInWithPassword: (
    email: string,
    password: string,
  ) => Promise<{ ok: boolean; message?: string }>
  signOut: () => Promise<void>
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const supabase = useMemo(() => getSupabase(), [])
  const [session, setSession] = useState<Session | null>(null)
  const [status, setStatus] = useState<AuthStatus>(supabase ? 'loading' : 'unconfigured')
  const [error, setError] = useState<string | null>(null)

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
    if (urlError) setError(humanise(urlError))

    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (!active) return
        setSession(data.session)
        setStatus(data.session ? 'authenticated' : 'anonymous')
      })
      .catch(() => {
        if (active) setStatus('anonymous')
      })

    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
      setStatus(nextSession ? 'authenticated' : 'anonymous')
      if (nextSession) setError(null)
    })

    return () => {
      active = false
      data.subscription.unsubscribe()
    }
  }, [supabase])

  const signInWithGoogle = useCallback(
    async (nextPath?: string) => {
      setError(null)
      if (!supabase || typeof window === 'undefined') {
        setError(AUTH_UNAVAILABLE_REASON)
        return
      }
      storeNextPath(nextPath)

      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}${AUTH_CALLBACK_PATH}`,
          queryParams: { prompt: 'select_account' },
        },
      })

      if (oauthError) setError(humanise(oauthError.message))
    },
    [supabase],
  )

  const signInWithPassword = useCallback(
    async (email: string, password: string) => {
      if (!supabase) return { ok: false, message: AUTH_UNAVAILABLE_REASON }
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      })
      if (signInError) return { ok: false, message: humanise(signInError.message) }
      return { ok: true }
    },
    [supabase],
  )

  const signOut = useCallback(async () => {
    if (typeof window !== 'undefined') window.sessionStorage.removeItem(NEXT_PATH_KEY)
    await supabase?.auth.signOut()
  }, [supabase])

  const value = useMemo<AuthValue>(
    () => ({
      status,
      session,
      user: session?.user ?? null,
      error,
      authUnavailableReason: supabase ? null : AUTH_UNAVAILABLE_REASON,
      signInWithGoogle,
      signInWithPassword,
      signOut,
      dismissError: () => setError(null),
    }),
    [status, session, error, supabase, signInWithGoogle, signInWithPassword, signOut],
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
