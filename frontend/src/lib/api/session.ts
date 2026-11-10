import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { identityService } from '../services'
import type { Me } from './types'

export type EngineSessionStatus = 'loading' | 'ready' | 'unavailable' | 'error'

export type EngineSession = {
  token: string | null
  tenantId: string | null
  me: Me | null
  status: EngineSessionStatus
  reason: string | null
  /** Typed engine refusal, e.g. PROVISIONING_REQUIRED. */
  errorCode: string | null
  /** Permission names the engine reports for this account. */
  capabilities: string[]
  reload: () => void
}

/**
 * The engine's view of the signed-in account.
 *
 * The Supabase claim decides which shell the interface opens (and is tested as
 * such), but the engine decides what data exists and what may be done to it.
 * Screens read this to know their workspace id and capabilities; a refusal from
 * `/me` — for example ``PROVISIONING_REQUIRED`` — is shown as an explicit state,
 * not retried into a blank page.
 */
export function useEngineSession(): EngineSession {
  const { session, status: authStatus } = useAuth()
  const token = session?.access_token ?? null
  const [me, setMe] = useState<Me | null>(null)
  const [status, setStatus] = useState<EngineSessionStatus>('loading')
  const [reason, setReason] = useState<string | null>(null)
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (authStatus === 'loading') {
      setStatus('loading')
      return
    }
    if (!token) {
      setMe(null)
      setStatus('unavailable')
      setReason('Sign in to load workspace data.')
      setErrorCode(null)
      return
    }
    const controller = new AbortController()
    let live = true
    setStatus('loading')
    void identityService.me({ token, signal: controller.signal }).then((result) => {
      if (!live) return
      if (result.status === 'ok') {
        setMe(result.data)
        setReason(null)
        setErrorCode(null)
        setStatus('ready')
      } else if (result.status === 'unavailable') {
        setMe(null)
        setStatus('unavailable')
        setReason(result.reason)
        setErrorCode(null)
      } else {
        setMe(null)
        setStatus('error')
        setReason(result.reason)
        setErrorCode(result.errorCode ?? null)
      }
    })
    return () => {
      live = false
      controller.abort()
    }
  }, [authStatus, token, tick])

  const reload = useCallback(() => setTick((value) => value + 1), [])
  return {
    token,
    tenantId: me?.tenant_id ?? null,
    me,
    status,
    reason,
    errorCode,
    capabilities: me?.capabilities ?? [],
    reload,
  }
}
