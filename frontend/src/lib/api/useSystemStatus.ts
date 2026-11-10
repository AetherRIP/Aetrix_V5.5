import { useCallback, useEffect, useState } from 'react'
import type { ApiResult } from './client'
import { statusService, type SystemStatus } from '../services'

/** How often an open screen re-reads the engine's status. */
export const STATUS_POLL_MS = 30_000

export type SystemStatusState =
  | { state: 'loading' }
  | { state: 'ok'; data: SystemStatus; latencyMs: number }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

/**
 * One polled read of `/status`, with the four states the screen must keep apart.
 *
 * A transient failure replaces the card with an error and the next poll retries,
 * so a status card cannot stay green after the engine has gone away — and cannot
 * stay red after it has come back. A hidden tab pauses the poll and resumes on
 * visibility change, so a background tab does not hold a stale answer.
 */
export function useSystemStatus(): [SystemStatusState, () => void, Date | null] {
  const [value, setValue] = useState<SystemStatusState>({ state: 'loading' })
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [tick, setTick] = useState(0)

  const refresh = useCallback(() => setTick((current) => current + 1), [])

  useEffect(() => {
    let live = true
    const controller = new AbortController()

    const read = async () => {
      const started = performance.now()
      const result: ApiResult<SystemStatus> = await statusService.read({
        signal: controller.signal,
      })
      if (!live) return
      if (result.status === 'ok') {
        setValue({
          state: 'ok',
          data: result.data,
          latencyMs: Math.round(performance.now() - started),
        })
      } else if (result.status === 'unavailable') {
        setValue({ state: 'unavailable', reason: result.reason })
      } else {
        setValue({ state: 'error', reason: result.reason, code: result.code })
      }
      setCheckedAt(new Date())
    }

    void read()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void read()
    }, STATUS_POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void read()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      live = false
      controller.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [tick])

  return [value, refresh, checkedAt]
}
