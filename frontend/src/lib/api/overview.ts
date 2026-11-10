/**
 * Platform-wide aggregates for the owner dashboard.
 *
 * Counts only: the engine never returns individual accounts, workspaces or
 * classes here. A metric can be available, a measured zero, or unavailable;
 * the last state is not a zero and must not be rendered as one.
 */

import { apiGet, type ApiResult, type RequestOptions } from './client'

/**
 * Broadcast after a successful mutation that changes a platform-wide count.
 * The overview listens for this instead of polling or waiting for window focus.
 * The stale marker survives navigation and a reload, so the next read also
 * bypasses the engine's cached identity census rather than showing old counts.
 */
export const PLATFORM_OVERVIEW_CHANGED_EVENT = 'aetrix:platform-overview-changed'
const PLATFORM_OVERVIEW_CHANNEL = 'aetrix:platform-overview'
const PLATFORM_OVERVIEW_CHANGED_KEY = 'aetrix:platform-overview-changed-at'
const PLATFORM_OVERVIEW_STALE_KEY = 'aetrix:platform-overview-stale'
let staleInMemory = false
let channel: BroadcastChannel | null = null

function overviewChannel(): BroadcastChannel | null {
  if (typeof window === 'undefined' || typeof BroadcastChannel === 'undefined') return null
  if (channel) return channel
  try {
    channel = new BroadcastChannel(PLATFORM_OVERVIEW_CHANNEL)
  } catch {
    // BroadcastChannel can be blocked by an embedding context. The storage
    // event fallback still reaches other tabs when storage is available.
    channel = null
  }
  return channel
}

export function announcePlatformOverviewChanged(): void {
  if (typeof window === 'undefined') return
  staleInMemory = true
  try {
    window.sessionStorage.setItem(PLATFORM_OVERVIEW_STALE_KEY, '1')
  } catch {
    // Storage can be disabled; the in-memory marker still covers this page.
  }

  const broadcast = overviewChannel()
  if (broadcast) {
    broadcast.postMessage('changed')
  } else {
    try {
      window.localStorage.setItem(PLATFORM_OVERVIEW_CHANGED_KEY, String(Date.now()))
    } catch {
      // No cross-tab transport is available; this tab still refreshes below.
    }
  }
  window.dispatchEvent(new Event(PLATFORM_OVERVIEW_CHANGED_EVENT))
}

/**
 * Subscribe the overview to changes from this tab and every other tab on the
 * same origin. ``BroadcastChannel`` is used when available; a storage event is
 * the fallback for browsers or embeddings that block it. No focus listener is
 * involved, so a hidden tab does not wait for the user to return.
 */
export function subscribePlatformOverviewChanged(onChange: () => void): () => void {
  if (typeof window === 'undefined') return () => {}

  const onLocalChange = () => onChange()
  window.addEventListener(PLATFORM_OVERVIEW_CHANGED_EVENT, onLocalChange)

  const broadcast = overviewChannel()
  const onBroadcast = (event: MessageEvent) => {
    if (event.data === 'changed') onChange()
  }
  broadcast?.addEventListener('message', onBroadcast)

  const onStorage = (event: StorageEvent) => {
    if (event.key === PLATFORM_OVERVIEW_CHANGED_KEY) onChange()
  }
  if (!broadcast) window.addEventListener('storage', onStorage)

  return () => {
    window.removeEventListener(PLATFORM_OVERVIEW_CHANGED_EVENT, onLocalChange)
    broadcast?.removeEventListener('message', onBroadcast)
    if (!broadcast) window.removeEventListener('storage', onStorage)
  }
}

export function consumePlatformOverviewStale(): boolean {
  if (typeof window === 'undefined') return false
  let stored = false
  try {
    stored = window.sessionStorage.getItem(PLATFORM_OVERVIEW_STALE_KEY) === '1'
    window.sessionStorage.removeItem(PLATFORM_OVERVIEW_STALE_KEY)
  } catch {
    // Storage can be disabled; fall back to the in-memory marker.
  }
  const stale = staleInMemory || stored
  staleInMemory = false
  return stale
}

export type MetricKey =
  | 'teacher_workspaces'
  | 'teachers'
  | 'assistant_accounts'
  | 'active_class_allocations'

export type MetricState = 'available' | 'no_records' | 'unavailable'

export type OverviewMetric = {
  key: MetricKey
  label: string
  value: number | null
  state: MetricState
  definition: string
  source: string
  reason: string | null
}

export type AccountCensus = {
  available: boolean
  captured_at: string | null
  cached: boolean
  active_accounts: number | null
  reason: string | null
}

export type PlatformOverview = {
  generated_at: string
  metrics: OverviewMetric[]
  account_census: AccountCensus
}

export function platformOverview(
  refresh: boolean,
  options: RequestOptions,
): Promise<ApiResult<PlatformOverview>> {
  return apiGet<PlatformOverview>(
    `/api/v1/admin/overview${refresh ? '?refresh=true' : ''}`,
    options,
  )
}
