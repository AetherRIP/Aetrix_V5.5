/**
 * Build-time configuration for the authenticated application.
 *
 * The Supabase URL and the publishable (anon) key are browser credentials by
 * design: they are shipped in every Supabase client and are constrained by the
 * project's authentication and row security policies. The service-role key is
 * never referenced in this bundle.
 *
 * `VITE_AETRIX_API_URL` is intentionally allowed to be absent. The correction
 * engine has no public HTTPS deployment yet, so the application renders an
 * explicit "work in progress" state instead of inventing an endpoint.
 */

type RawEnv = Record<string, string | undefined>

const raw = import.meta.env as unknown as RawEnv

function read(name: string): string {
  const value = raw[name]
  return typeof value === 'string' ? value.trim() : ''
}

export const env = {
  supabaseUrl: read('VITE_SUPABASE_URL'),
  supabaseAnonKey: read('VITE_SUPABASE_ANON_KEY'),
  apiBaseUrl: read('VITE_AETRIX_API_URL'),
} as const

/** Authentication can only run when both the project URL and browser key exist. */
export const isSupabaseConfigured = Boolean(env.supabaseUrl && env.supabaseAnonKey)

/** The engine API is optional until it is deployed. */
export const isApiConfigured = Boolean(env.apiBaseUrl)

/** Shown wherever a screen needs the engine and the engine is not deployed. */
export const API_UNAVAILABLE_REASON =
  'The Aetrix correction API has no public HTTPS deployment yet, so this screen has no data source.'

export const AUTH_UNAVAILABLE_REASON =
  'Supabase authentication is not configured for this build: VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY must be present at build time.'
