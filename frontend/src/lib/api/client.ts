import { API_NOT_DEPLOYED_REASON, env, isApiConfigured } from '../env'

/**
 * Every data read resolves to one of these. A missing deployment is a normal,
 * expected outcome — not an error to swallow and not a reason to render zeros.
 */
export type ApiResult<T> =
  | { status: 'ok'; data: T }
  | { status: 'unavailable'; reason: string }
  | { status: 'error'; reason: string; code?: number; errorCode?: string }

export function unavailable<T>(reason: string = API_NOT_DEPLOYED_REASON): ApiResult<T> {
  return { status: 'unavailable', reason }
}

export type RequestOptions = {
  /** Supabase access token; the engine verifies it as a JWT bearer. */
  token?: string | null
  signal?: AbortSignal
}

async function failure(response: Response): Promise<ApiResult<never>> {
  let reason = `The engine rejected the request (${response.status}).`
  let errorCode: string | undefined
  try {
    const body = (await response.json()) as {
      error?: { code?: unknown; message?: unknown }
    }
    const message = body?.error?.message
    if (typeof message === 'string' && message.trim()) reason = message
    if (typeof body?.error?.code === 'string' && body.error.code.trim()) {
      errorCode = body.error.code
    }
  } catch {
    // The body was not the engine's JSON error shape; keep the status message.
  }
  return { status: 'error', reason, code: response.status, errorCode }
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
    if (!response.ok) return failure(response)
    // A successful DELETE is 204 No Content. `response.json()` throws on the
    // empty body, which used to be indistinguishable from a network failure.
    if (response.status === 204 || response.status === 205) {
      return { status: 'ok', data: undefined as T }
    }
    const body = await response.text()
    if (!body.trim()) return { status: 'ok', data: undefined as T }
    try {
      return { status: 'ok', data: JSON.parse(body) as T }
    } catch {
      return {
        status: 'error',
        reason: 'The engine returned a response that could not be read.',
        code: response.status,
      }
    }
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
  body?: unknown,
  options?: RequestOptions,
): Promise<ApiResult<T>> {
  return apiRequest<T>(
    path,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    },
    options,
  )
}

export async function apiPut<T>(
  path: string,
  body: unknown,
  options?: RequestOptions,
): Promise<ApiResult<T>> {
  return apiRequest<T>(
    path,
    {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    },
    options,
  )
}

export async function apiPatch<T>(
  path: string,
  body: unknown,
  options?: RequestOptions,
): Promise<ApiResult<T>> {
  return apiRequest<T>(
    path,
    {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    },
    options,
  )
}

/** Multipart upload: the browser sets the boundary, so no content-type here. */
export async function apiUpload<T>(
  path: string,
  form: FormData,
  options?: RequestOptions,
): Promise<ApiResult<T>> {
  return apiRequest<T>(path, { method: 'POST', body: form }, options)
}

/**
 * Binary read (a rendered page image). The bearer token cannot ride on an
 * `<img src>`, so the page is fetched and shown from an object URL instead.
 */
export async function apiBlob(
  path: string,
  options?: RequestOptions,
): Promise<ApiResult<Blob>> {
  if (!isApiConfigured) return unavailable<Blob>()

  const headers = new Headers()
  if (options?.token) headers.set('authorization', `Bearer ${options.token}`)
  try {
    const response = await fetch(`${env.apiBaseUrl.replace(/\/$/, '')}${path}`, {
      headers,
      signal: options?.signal,
    })
    if (!response.ok) return failure(response)
    return { status: 'ok', data: await response.blob() }
  } catch {
    return {
      status: 'error',
      reason: 'The engine could not be reached. Check the deployment and network.',
    }
  }
}
