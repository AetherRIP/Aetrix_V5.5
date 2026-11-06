import { API_UNAVAILABLE_REASON, env, isApiConfigured } from '../env'

/**
 * Every data read resolves to one of these. A missing deployment is a normal,
 * expected outcome — not an error to swallow and not a reason to render zeros.
 */
export type ApiResult<T> =
  | { status: 'ok'; data: T }
  | { status: 'unavailable'; reason: string }
  | { status: 'error'; reason: string; code?: number }

export function unavailable<T>(reason: string = API_UNAVAILABLE_REASON): ApiResult<T> {
  return { status: 'unavailable', reason }
}

export type RequestOptions = {
  /** Supabase access token; the engine verifies it as a JWT bearer. */
  token?: string | null
  signal?: AbortSignal
}

/**
 * Single place where the application talks to the correction engine. When the
 * API base URL is absent this returns `unavailable` without any network call, so
 * no component needs to know the engine's hosting state.
 */
export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  if (!isApiConfigured) return unavailable<T>()

  const headers = new Headers(init.headers)
  headers.set('accept', 'application/json')
  if (options.token) headers.set('authorization', `Bearer ${options.token}`)

  try {
    const response = await fetch(`${env.apiBaseUrl.replace(/\/$/, '')}${path}`, {
      ...init,
      headers,
      signal: options.signal,
    })

    if (!response.ok) {
      return {
        status: 'error',
        reason: `The engine rejected the request (${response.status}).`,
        code: response.status,
      }
    }

    return { status: 'ok', data: (await response.json()) as T }
  } catch {
    return {
      status: 'error',
      reason: 'The engine could not be reached. Check the deployment and network.',
    }
  }
}

export async function apiGet<T>(path: string, options?: RequestOptions): Promise<ApiResult<T>> {
  return apiRequest<T>(path, { method: 'GET' }, options)
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  options?: RequestOptions,
): Promise<ApiResult<T>> {
  return apiRequest<T>(
    path,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    },
    options,
  )
}
