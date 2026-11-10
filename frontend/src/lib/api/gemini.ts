/**
 * The platform's Gemini fleet API.
 *
 * These calls are operator-only: the engine gates every route on the ADMIN
 * role resolved from the verified token, so a teacher's session receives 403
 * even if it reaches this module. Every result is an `ApiResult`, which means a
 * missing deployment is a first-class state rather than a thrown error.
 */

import { apiGet, apiPost, apiPut, apiRequest, type ApiResult, type RequestOptions } from './client'

const BASE = '/api/v1/admin/providers'

export type Confidence = 'CONFIRMED' | 'ESTIMATED' | 'UNKNOWN'

export type Health = 'HEALTHY' | 'INVALID' | 'DISABLED' | 'UNKNOWN'

/** Operational state is separate from credential validity. */
export type OperationalStatus =
  | 'OPERATIONAL'
  | 'DEGRADED'
  | 'RATE_LIMITED'
  | 'PROVIDER_UNAVAILABLE'
  | 'NETWORK_FAILURE'
  | 'NOT_TESTED'
  | 'DISABLED'

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
  reset_timezone?: string
  observed_at: string
  cooldown_until: string | null
  accounting?: string
  exhausted: boolean
  notes: string[]
}

export type ProjectVerification =
  | 'VERIFIED'
  | 'NOT_FOUND'
  | 'PERMISSION_DENIED'
  | 'ERROR'
  | 'UNVERIFIABLE'
  | 'UNVERIFIED'
  | 'OPERATOR_DECLARED'

export type ProjectRow = {
  project_id: string
  verification?: ProjectVerification
  verified?: boolean
  project_number?: string | null
  google_last_attempt_at?: string | null
  google_quota_last_synced_at?: string | null
  google_quota_stale?: boolean | null
  keys: number
  healthy: number
  unknown?: number
  disabled: number
  invalid: number
  operational_status?: OperationalStatus
  cooldown_until: string | null
  estimates: QuotaEstimate[]
}

export type FleetKey = {
  id: string
  contributor_id: string | null
  contributor_name: string | null
  revoked_at: string | null
  project_id: string
  account_label: string
  key_fingerprint: string
  auth_type: string
  tier: string
  health: Health
  operational_status?: OperationalStatus
  project_verification?: 'OPERATOR_DECLARED'
  model_access: string[]
  cooldown_until: string | null
  last_success_at: string | null
  last_failure_at: string | null
  last_failure_status: number | null
  last_failure_category?: string | null
  last_failure_provider_code?: string | null
  last_failure_message?: string | null
  last_failure_reached_provider?: boolean | null
  last_usage_at?: string | null
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
  declared_projects?: number
  verified_projects?: number
  project_verification?: 'OPERATOR_DECLARED' | 'GOOGLE_CLOUD'
  attempted_today?: number
  requests_today: number
  successful_today?: number
  input_tokens_today: number
  output_tokens_today: number
  failures_today: number
  reported_requests_today?: number
  error_rate_today: number | null
  operational_status?: OperationalStatus
  last_success_at?: string | null
  last_failure_at?: string | null
  last_failure_category?: string | null
  last_failure_message?: string | null
  observed_at: string
  day_started_at: string
  reset_at: string
  reset_timezone?: string
  quota_accounting?: string
  projects_detail: ProjectRow[]
}

export type RecentProviderCall = {
  id: string
  created_at: string
  credential_id: string | null
  credential_label: string | null
  project_id: string
  model: string
  purpose: string
  success: boolean
  http_status: number | null
  error_class: string | null
  error_category: string | null
  provider_code: string | null
  provider_message: string | null
  reached_provider: boolean | null
  input_tokens: number | null
  output_tokens: number | null
  request_id: string | null
  latency_ms: number | null
}

export type UsageReport = {
  since: string
  timezone?: string
  recent_calls?: RecentProviderCall[]
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

export type ValidationCategory =
  | 'ok'
  | 'authentication'
  | 'permission'
  | 'quota'
  | 'configuration'
  | 'network'
  | 'provider_server'
  | 'provider_response'
  | 'invalid_request'
  | 'unsupported_model'
  | 'internal'

export type Validation = {
  credential_id: string
  health: Health
  operational_status?: OperationalStatus
  valid: boolean
  detail: string | null
  category: ValidationCategory
  http_status: number | null
  model: string
  checked_at: string
  provider_code?: string | null
  provider_message: string | null
  reached_provider?: boolean | null
  recommendation: string | null
  latency_ms: number | null
  key_fingerprint: string
  project_id: string
  account_label: string
}

export type SelectionRole = 'primary' | 'review' | 'lightweight'

export type ModelStatus = 'stable' | 'preview' | 'deprecated' | 'unsupported'

export type ModelCapabilities = {
  structured_outputs: boolean | null
  thinking: boolean | null
  documented_inputs: string[] | null
  source: string | null
}

export type ModelProjectAccess = {
  project_id: string
  available: boolean
}

export type CatalogueModel = {
  id: string
  display_name: string | null
  description: string | null
  status: ModelStatus
  status_detail: string | null
  supports_generate: boolean
  input_token_limit: number | null
  output_token_limit: number | null
  capabilities: ModelCapabilities
  input_usd_per_million: number | null
  output_usd_per_million: number | null
  projects: ModelProjectAccess[]
}

export type CatalogueProject = {
  project_id: string
  credential_fingerprint: string
  ok: boolean
  models: number
  error: string | null
}

export type ModelCatalogue = {
  discovered_at: string
  cached: boolean
  ttl_seconds: number
  projects: CatalogueProject[]
  models: CatalogueModel[]
  selections: Record<SelectionRole, string>
  selection_sources: Record<SelectionRole, string>
  note: string
}

export type ModelSelection = {
  role: SelectionRole
  model: string
  updated_at: string
  updated_by: string | null
}

export type InventoryIdStatus = 'VERIFIED' | 'CORRECTED' | 'UNVERIFIED'

export type InventoryCategory =
  | 'TEXT_OUT'
  | 'OTHER'
  | 'EMBEDDING'
  | 'AGENT'
  | 'IMAGE_GENERATION'
  | 'MULTIMODAL'
  | 'MUSIC_GENERATION'
  | 'TEXT_TO_SPEECH'
  | 'TRANSCRIPTION'
  | 'LIVE_API'

export type InventoryLifecycle =
  | 'STABLE'
  | 'PREVIEW'
  | 'EXPERIMENTAL'
  | 'LEGACY'
  | 'DEPRECATED'
  | 'RETIRED'
  | 'UNKNOWN'

export type InventoryAvailability =
  | 'AVAILABLE'
  | 'UNAVAILABLE'
  | 'ACCESS_RESTRICTED'
  | 'QUOTA_EXHAUSTED'
  | 'NOT_TESTED'
  | 'UNKNOWN'

export type InventoryWorkload =
  | 'mathematics_marking'
  | 'document_extraction'
  | 'image_generation'
  | 'audio_processing'
  | 'transcription'
  | 'embeddings'
  | 'agent_workflows'
  | 'other'

export type InventoryQuota = {
  rpm_limit: number | null
  rpm_used: number
  rpm_unlimited: boolean
  tpm_limit: number | null
  tpm_used: number
  tpm_unlimited: boolean
  rpd_limit: number | null
  rpd_used: number
  rpd_unlimited: boolean
  limits_provided: boolean
  source: string
  imported_at: string
  observation_time_supplied: boolean
  inconsistencies: string[]
}

export type InventoryModel = {
  key: string
  display_name: string
  api_model_id: string | null
  supplied_api_id: string | null
  id_status: InventoryIdStatus
  provider: string
  family: string
  version: string | null
  category: InventoryCategory
  lifecycle: InventoryLifecycle
  catalogue_state: string
  description: string | null
  input_modalities: string[]
  output_modalities: string[]
  context_window: number | null
  max_output_tokens: number | null
  supported_generation_methods: string[]
  supports_generate: boolean
  capabilities: Record<string, boolean | null>
  capability_source: string
  limitations: string[]
  workloads: InventoryWorkload[]
  availability: InventoryAvailability
  source_url: string | null
  replacement_model_id: string | null
  pricing: {
    input_usd_per_million: number | null
    output_usd_per_million: number | null
  }
  quota: InventoryQuota
}

export type InventoryCounts = {
  total: number
  by_category: Record<string, number>
  by_lifecycle: Record<string, number>
  by_workload: Record<string, number>
  by_availability: Record<string, number>
  verified_api_ids: number
  corrected_api_ids: number
  unverified_api_ids: number
  math_marking_candidates: number
  quota_records: number
  quota_records_with_usage: number
  quota_inconsistencies: number
}

export type ModelInventory = {
  imported_at: string
  models: InventoryModel[]
  counts: InventoryCounts
  selections: Record<SelectionRole, string>
  selection_sources: Record<SelectionRole, string>
  note: string
}

export function listModels(
  refresh: boolean,
  options: RequestOptions,
): Promise<ApiResult<ModelCatalogue>> {
  return apiGet<ModelCatalogue>(`${BASE}/models${refresh ? '?refresh=true' : ''}`, options)
}

export function listModelInventory(
  options: RequestOptions,
): Promise<ApiResult<ModelInventory>> {
  return apiGet<ModelInventory>(`${BASE}/models/inventory`, options)
}

export function selectModel(
  role: SelectionRole,
  model: string,
  options: RequestOptions,
): Promise<ApiResult<ModelSelection>> {
  return apiPut<ModelSelection>(`${BASE}/models/selection/${role}`, { model }, options)
}

export function testModel(
  model: string,
  body: { credential_id?: string; project_id?: string },
  options: RequestOptions,
): Promise<ApiResult<Validation>> {
  return apiPost<Validation>(
    `${BASE}/models/${encodeURIComponent(model)}/test`,
    body,
    options,
  )
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

export type GoogleQuotaValue = {
  quota_id: string
  metric: string
  service: string
  metric_display_name: string | null
  quota_display_name: string | null
  unit: string | null
  refresh_interval: string | null
  reset_time: string | null
  container_type: string | null
  is_precise: boolean | null
  dimensions: Record<string, string>
  limit: number | null
  is_unlimited: boolean
  limit_source: 'CLOUD_QUOTAS' | 'CLOUD_MONITORING' | 'UNAVAILABLE'
  usage: number | null
  usage_source: 'CLOUD_MONITORING' | 'NOT_EXPOSED'
  usage_metric: string | null
  usage_observed_at: string | null
  exceeded: number | null
  observed_at: string
}

export type GoogleQuotaRun = {
  id: string
  trigger: 'MANUAL' | 'SCHEDULED'
  status: 'SUCCEEDED' | 'PARTIAL' | 'FAILED'
  started_at: string
  finished_at: string | null
  quota_infos: number
  snapshots_written: number
  api_calls: number
  error_code: string | null
  error_message: string | null
}

export type GoogleQuotaProject = {
  project_id: string
  verification: ProjectVerification
  verified: boolean
  project_number: string | null
  display_name: string | null
  lifecycle_state: string | null
  last_attempt_at: string | null
  last_verified_at: string | null
  last_success_at: string | null
  last_error_code: string | null
  last_error_message: string | null
  stale: boolean
  quota_count: number
  usage_observed: number
  quotas: GoogleQuotaValue[]
  runs: GoogleQuotaRun[]
}

export type GoogleApiRequirement = {
  service: string
  name: string
  permission: string
  used_for: string
  enabled: boolean | null
}

export type GoogleQuotaReport = {
  observed_at: string
  service: string
  fleet: {
    configured: boolean
    credential_source: string
    scheduled_sync_enabled: boolean
    sync_interval_seconds: number
    stale_after_seconds: number
    declared_projects: number
    verified_projects: number
    quotas_total: number
    usage_observed: number
    stale_projects: number
    last_success_at: string | null
    last_failure_at: string | null
    last_failure_message: string | null
  }
  projects: GoogleQuotaProject[]
  apis: GoogleApiRequirement[]
  ai_studio: { available: boolean; reason: string; source: string }
  coverage: { supported: string[]; unavailable: string[] }
  note: string
  sync_results: {
    project_id: string
    status: 'SUCCEEDED' | 'PARTIAL' | 'FAILED'
    run_id: string | null
    verification: ProjectVerification
    quota_infos: number
    snapshots: number
    error_code: string | null
    message: string | null
  }[]
}

export function googleQuota(options: RequestOptions): Promise<ApiResult<GoogleQuotaReport>> {
  return apiGet<GoogleQuotaReport>(`${BASE}/google-quota`, options)
}

export function syncGoogleQuota(
  projectId: string | undefined,
  options: RequestOptions,
): Promise<ApiResult<GoogleQuotaReport>> {
  return apiPost<GoogleQuotaReport>(
    `${BASE}/google-quota/sync`,
    projectId ? { project_id: projectId } : {},
    options,
  )
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

const CONTRIBUTIONS = `${BASE}/contributions`

export type ContributorStatus = 'ACTIVE' | 'SUSPENDED' | 'WITHDRAWN'

export type Contributor = {
  id: string
  user_id: string | null
  display_name: string
  contact_email: string | null
  status: ContributorStatus
  consent_version: string
  consent_at: string
  consent_reference: string | null
  status_reason: string | null
  suspended_at: string | null
  withdrawn_at: string | null
  created_at: string
}

export type ContributionUsage = {
  requests: number
  input_tokens: number
  output_tokens: number
  failures: number
  quota_failures: number
  last_success_at: string | null
}

export type ContributorRow = {
  contributor: Contributor
  keys_total: number
  keys_eligible: number
  keys_revoked: number
  projects: string[]
  window: ContributionUsage
  today: ContributionUsage
}

export type CapacityProject = {
  project_id: string
  contributors: number
  keys: number
  requests_per_minute_remaining: number | null
  requests_per_day_remaining: number | null
  confidence: Confidence
  cooldown_until: string | null
}

export type CapacityModel = {
  model: string
  projects: CapacityProject[]
  totals: {
    projects: number
    requests_per_minute_remaining: number | null
    requests_per_day_remaining: number | null
    windows_measured: number
    windows_unknown: number
    confidence: Confidence
  }
}

export type ContributionSummary = {
  observed_at: string
  window_started_at: string
  day_started_at: string
  aggregate: {
    contributors_total: number
    contributors_by_status: Record<string, number>
    keys_contributed: number
    keys_eligible: number
    keys_revoked: number
    platform_keys: number
    orphaned_contributor_keys: number
    projects: number
    shared_projects: number
    requests_in_window: number
    requests_today: number
    input_tokens_in_window: number
    output_tokens_in_window: number
    failures_in_window: number
  }
  contributors: ContributorRow[]
  capacity: { models: CapacityModel[]; note: string }
}

export type ContributorDraft = {
  display_name: string
  contact_email?: string
  user_id?: string
  consent_version: string
  consent_reference?: string
}

export type ContributorKeyDraft = {
  project_id: string
  api_key: string
  label?: string
  tier?: 'FREE' | 'PAID' | 'UNKNOWN'
}

export type Withdrawal = {
  contributor_id: string
  status: ContributorStatus
  keys_revoked: number
}

export function contributionSummary(
  days: number,
  options: RequestOptions,
): Promise<ApiResult<ContributionSummary>> {
  return apiGet<ContributionSummary>(`${CONTRIBUTIONS}?window_days=${days}`, options)
}

export function createContributor(
  draft: ContributorDraft,
  options: RequestOptions,
): Promise<ApiResult<Contributor>> {
  return apiPost<Contributor>(CONTRIBUTIONS, draft, options)
}

export function addContributorKey(
  contributorId: string,
  draft: ContributorKeyDraft,
  options: RequestOptions,
): Promise<ApiResult<FleetKey>> {
  return apiPost<FleetKey>(`${CONTRIBUTIONS}/${contributorId}/keys`, draft, options)
}

export function revokeContributorKey(
  contributorId: string,
  credentialId: string,
  options: RequestOptions,
): Promise<ApiResult<null>> {
  return apiRequest<null>(`${CONTRIBUTIONS}/${contributorId}/keys/${credentialId}`, { method: 'DELETE' }, options)
}

export function suspendContributor(
  contributorId: string,
  reason: string,
  options: RequestOptions,
): Promise<ApiResult<Contributor>> {
  return apiPost<Contributor>(`${CONTRIBUTIONS}/${contributorId}/suspend`, { reason }, options)
}

export function reinstateContributor(
  contributorId: string,
  options: RequestOptions,
): Promise<ApiResult<Contributor>> {
  return apiPost<Contributor>(`${CONTRIBUTIONS}/${contributorId}/reinstate`, {}, options)
}

export function withdrawContributor(
  contributorId: string,
  reason: string,
  options: RequestOptions,
): Promise<ApiResult<Withdrawal>> {
  return apiPost<Withdrawal>(`${CONTRIBUTIONS}/${contributorId}/withdraw`, { reason }, options)
}
