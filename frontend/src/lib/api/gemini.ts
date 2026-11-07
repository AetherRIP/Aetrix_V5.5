/**
 * The platform's Gemini fleet API.
 *
 * These calls are operator-only: the engine gates every route on the ADMIN
 * role resolved from the verified token, so a teacher's session receives 403
 * even if it reaches this module. Every result is an `ApiResult`, which means a
 * missing deployment is a first-class state rather than a thrown error.
 */

import { apiGet, apiPost, apiRequest, type ApiResult, type RequestOptions } from './client'

const BASE = '/api/v1/admin/providers'

export type Confidence = 'CONFIRMED' | 'ESTIMATED' | 'UNKNOWN'

export type Health = 'HEALTHY' | 'COOLDOWN' | 'INVALID' | 'DISABLED' | 'UNKNOWN'

export type QuotaWindow = {
  limit: number | null
  used: number
  remaining: number | null
  used_share: number | null
  confidence: Confidence
}

export type QuotaEstimate = {
  project_id: string
  model: string
  confidence: Confidence
  requests_per_minute: QuotaWindow
  tokens_per_minute: QuotaWindow
  requests_per_day: QuotaWindow
  reset_at: string
  observed_at: string
  cooldown_until: string | null
  exhausted: boolean
  notes: string[]
}

export type ProjectRow = {
  project_id: string
  keys: number
  healthy: number
  disabled: number
  invalid: number
  cooldown_until: string | null
  estimates: QuotaEstimate[]
}

export type FleetKey = {
  id: string
  project_id: string
  account_label: string
  key_fingerprint: string
  auth_type: string
  tier: string
  health: Health
  model_access: string[]
  cooldown_until: string | null
  last_success_at: string | null
  last_failure_at: string | null
  last_failure_status: number | null
  last_validated_at: string | null
  last_error: string | null
  requests: number
  input_tokens: number
  output_tokens: number
  failures: number
  quota_failures: number
}

export type KeyPage = {
  items: FleetKey[]
  total: number
  limit: number
  offset: number
}

export type FleetOverview = {
  keys_total: number
  keys_by_health: Partial<Record<Health, number>>
  projects: number
  requests_today: number
  input_tokens_today: number
  output_tokens_today: number
  failures_today: number
  error_rate_today: number | null
  observed_at: string
  day_started_at: string
  reset_at: string
  projects_detail: ProjectRow[]
}

export type UsageReport = {
  since: string
  daily: { day: string; requests: number; input_tokens: number; output_tokens: number; failures: number }[]
  by_model: { model: string; requests: number; input_tokens: number; output_tokens: number; failures: number }[]
  by_project: {
    project_id: string
    requests: number
    input_tokens: number
    output_tokens: number
    failures: number
    quota_failures: number
  }[]
}

export type FleetAlert = {
  severity: 'critical' | 'warning' | 'info'
  kind: string
  project_id: string | null
  message: string
}

export type KeyDraft = {
  project_id: string
  api_key: string
  label?: string
  tier?: 'FREE' | 'PAID' | 'UNKNOWN'
  auth_type?: 'api_key' | 'oauth'
  model_access?: string[]
}

export type ImportRow = {
  index: number
  label: string
  project_id: string
  outcome: 'added' | 'duplicate' | 'rejected'
  detail: string | null
  credential_id: string | null
}

export type Validation = {
  credential_id: string
  health: Health
  valid: boolean
  detail: string | null
}

export function listKeys(
  params: { projectId?: string; health?: string; q?: string; limit?: number; offset?: number },
  options: RequestOptions,
): Promise<ApiResult<KeyPage>> {
  const query = new URLSearchParams()
  if (params.projectId) query.set('project_id', params.projectId)
  if (params.health) query.set('health', params.health)
  if (params.q) query.set('q', params.q)
  query.set('limit', String(params.limit ?? 50))
  query.set('offset', String(params.offset ?? 0))
  return apiGet<KeyPage>(`${BASE}/keys?${query.toString()}`, options)
}

export function overview(options: RequestOptions): Promise<ApiResult<FleetOverview>> {
  return apiGet<FleetOverview>(`${BASE}/overview`, options)
}

export function alerts(options: RequestOptions): Promise<ApiResult<FleetAlert[]>> {
  return apiGet<FleetAlert[]>(`${BASE}/alerts`, options)
}

export function usage(days: number, options: RequestOptions): Promise<ApiResult<UsageReport>> {
  return apiGet<UsageReport>(`${BASE}/usage?days=${days}`, options)
}

export function addKey(draft: KeyDraft, options: RequestOptions): Promise<ApiResult<FleetKey>> {
  return apiPost<FleetKey>(`${BASE}/keys`, draft, options)
}

export function importKeys(
  entries: KeyDraft[],
  options: RequestOptions,
): Promise<ApiResult<ImportRow[]>> {
  return apiPost<ImportRow[]>(`${BASE}/keys/import`, { keys: entries }, options)
}

export function validateKey(id: string, options: RequestOptions): Promise<ApiResult<Validation>> {
  return apiPost<Validation>(`${BASE}/keys/${id}/validate`, {}, options)
}

export function setKeyEnabled(
  id: string,
  enabled: boolean,
  options: RequestOptions,
): Promise<ApiResult<FleetKey>> {
  return apiPost<FleetKey>(`${BASE}/keys/${id}/enabled`, { enabled }, options)
}

export function removeKey(id: string, options: RequestOptions): Promise<ApiResult<null>> {
  return apiRequest<null>(`${BASE}/keys/${id}`, { method: 'DELETE' }, options)
}
