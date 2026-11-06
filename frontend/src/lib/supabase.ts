import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { env, isSupabaseConfigured } from './env'

let client: SupabaseClient | null = null

/**
 * Returns the browser Supabase client, or `null` when the build has no
 * configuration. Callers must treat `null` as "authentication unavailable"
 * rather than falling back to a fabricated session.
 */
export function getSupabase(): SupabaseClient | null {
  if (!isSupabaseConfigured) return null
  if (client) return client

  client = createClient(env.supabaseUrl, env.supabaseAnonKey, {
    auth: {
      // PKCE is the correct flow for a statically hosted browser application.
      flowType: 'pkce',
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storageKey: 'aetrix:auth',
    },
  })

  return client
}

/** Test seam: forget the cached client (used by the route-level tests). */
export function resetSupabaseClient(): void {
  client = null
}

export const AUTH_CALLBACK_PATH = '/auth/callback'
