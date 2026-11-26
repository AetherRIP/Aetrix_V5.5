import { useEffect, useState } from 'react'
import { apiGet } from './api/client'

/**
 * What the *running* engine build can do.
 *
 * A control that calls an endpoint the deployed engine does not have is a
 * broken control, so optional features are advertised by the engine and hidden
 * when the answer is missing or negative. An older engine answers 404 here; that
 * is a normal "absent", not an error to show the user.
 */
export type EngineCapabilities = {
  scheme_criteria_authoring: boolean
  messaging_stream_payloads: boolean
}

const ABSENT: EngineCapabilities = {
  scheme_criteria_authoring: false,
  messaging_stream_payloads: false,
}

let pending: Promise<EngineCapabilities> | null = null

export function loadCapabilities(): Promise<EngineCapabilities> {
  if (!pending) {
    pending = apiGet<EngineCapabilities>('/api/v1/capabilities').then((result) =>
      result.status === 'ok' ? result.data : ABSENT,
    )
  }
  return pending
}

/** `null` while the answer is unknown; the caller must not render the control. */
export function useCapability(name: keyof EngineCapabilities): boolean | null {
  const [value, setValue] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    void loadCapabilities().then((capabilities) => {
      if (alive) setValue(Boolean(capabilities[name]))
    })
    return () => {
      alive = false
    }
  }, [name])
  return value
}
