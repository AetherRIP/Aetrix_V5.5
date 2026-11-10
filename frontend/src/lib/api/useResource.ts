import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiResult } from './client'

/** One bounded engine read, with the four states a screen must distinguish. */
export type Loaded<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number; errorCode?: string }

/**
 * Runs a loader when its key changes. A null loader means the screen cannot ask
 * yet (no workspace session), which is reported as an explicit state rather than
 * an indefinite spinner.
 */
export function useResource<T>(
  key: string,
  loader: ((signal: AbortSignal) => Promise<ApiResult<T>>) | null,
): [Loaded<T>, () => void] {
  const [state, setState] = useState<Loaded<T>>(
    loader ? { state: 'loading' } : { state: 'unavailable', reason: 'A workspace session is required.' },
  )
  const [tick, setTick] = useState(0)
  const ref = useRef(loader)
  ref.current = loader

  useEffect(() => {
    const current = ref.current
    if (!current) {
      setState({ state: 'unavailable', reason: 'A workspace session is required.' })
      return
    }
    const controller = new AbortController()
    let live = true
    setState({ state: 'loading' })
    void current(controller.signal).then((result) => {
      if (!live) return
      if (result.status === 'ok') setState({ state: 'ok', data: result.data })
      else if (result.status === 'unavailable') setState({ state: 'unavailable', reason: result.reason })
      else
        setState({
          state: 'error',
          reason: result.reason,
          code: result.code,
          errorCode: result.errorCode,
        })
    })
    return () => {
      live = false
      controller.abort()
    }
  }, [key, tick])

  const reload = useCallback(() => setTick((value) => value + 1), [])
  return [state, reload]
}
