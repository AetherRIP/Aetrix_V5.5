import { apiGet, apiPatch, apiPost, apiRequest, type ApiResult, type RequestOptions } from './client'

/**
 * Platform account administration. These calls are the only place the browser
 * sees platform-wide account data, and every one of them is authorized by the
 * engine from the verified `app_metadata.aetrix_role` claim. The service-role
 * key that actually reads Supabase Auth stays on the server.
 */

const BASE = '/api/v1/admin/accounts'

export type PlatformRole =
  | 'owner'
  | 'platform_operator'
  | 'supervisor'
  | 'assistant'
  | 'viewer'
  | 'unassigned'

/** Roles this interface may grant. Ownership is never among them. */
export type ManageableRole = 'platform_operator' | 'supervisor' | 'assistant' | 'viewer'

export type AccountStatus = 'ACTIVE' | 'SUSPENDED' | 'UNCONFIRMED'

export type AccountMembership = {
  tenant_id: string
  workspace_name: string
  workspace_slug: string
  role: string
  is_demo: boolean
  user_row_id: string
  joined_at: string
}

export type AccountInvitation = {
  id: string
  email: string
  role: string
  status: string
  tenant_id: string
  workspace_name: string
  expires_at: string
  created_at: string
}

export type AccountAuditEntry = {
  id: string
  action: string
  actor_subject: string
  actor_platform_role: string
  target_subject: string
  target_email: string | null
  detail: Record<string, unknown>
  created_at: string
}

export type PlatformAccount = {
  id: string
  email: string | null
  display_name: string | null
  role: PlatformRole
  status: AccountStatus
  created_at: string | null
  updated_at: string | null
  last_sign_in_at: string | null
  email_confirmed_at: string | null
  banned_until: string | null
  memberships: AccountMembership[]
  workspace_count: number
  has_workspace: boolean
  pending_invitation_count: number
}

export type PlatformAccountDetail = PlatformAccount & {
  invitations: AccountInvitation[]
  audit: AccountAuditEntry[]
}

/**
 * What a platform-role change did to one workspace membership row. The engine
 * reports rows it left alone too, so the screen never says "succeeded" when the
 * account's shell role cannot have moved.
 */
export type MembershipEffect = {
  state: 'changed' | 'skipped'
  reason: string
  workspace_name: string | null
  workspace_slug: string | null
  user_row_id: string | null
  previous_role: string | null
  role: string | null
}

/** The role-change result: the account after the change, plus every row. */
export type AccountRoleChange = {
  account: PlatformAccountDetail
  memberships: MembershipEffect[]
}

export type AccountPage = {
  items: PlatformAccount[]
  total: number
  page: number
  page_size: number
  source: string
  truncated: boolean
}

export type AccountOperation = { name: string; supported: boolean; note: string }

export type AccountCapability = {
  configured: boolean
  reason: string
  operations: AccountOperation[]
}

export type AccountAction = { status: string; message: string }

export type AccountFilters = {
  q?: string
  role?: PlatformRole
  status?: AccountStatus
  joined?: 'yes' | 'no'
  page?: number
  pageSize?: number
}

function queryString(filters: AccountFilters): string {
  const params = new URLSearchParams()
  if (filters.q) params.set('q', filters.q)
  if (filters.role) params.set('role', filters.role)
  if (filters.status) params.set('status', filters.status)
  if (filters.joined) params.set('joined', filters.joined)
  if (filters.page && filters.page > 1) params.set('page', String(filters.page))
  if (filters.pageSize) params.set('page_size', String(filters.pageSize))
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export function accountCapability(
  options?: RequestOptions,
): Promise<ApiResult<AccountCapability>> {
  return apiGet<AccountCapability>(`${BASE}/capability`, options)
}

export function listAccounts(
  filters: AccountFilters,
  options?: RequestOptions,
): Promise<ApiResult<AccountPage>> {
  return apiGet<AccountPage>(`${BASE}${queryString(filters)}`, options)
}

export function getAccount(
  accountId: string,
  options?: RequestOptions,
): Promise<ApiResult<PlatformAccountDetail>> {
  return apiGet<PlatformAccountDetail>(`${BASE}/${encodeURIComponent(accountId)}`, options)
}

export function updateAccountRole(
  accountId: string,
  role: ManageableRole,
  reason: string,
  options?: RequestOptions,
): Promise<ApiResult<AccountRoleChange>> {
  return apiPatch<AccountRoleChange>(
    `${BASE}/${encodeURIComponent(accountId)}/role`,
    { role, reason: reason.trim() || null },
    options,
  )
}

export function updateAccountStatus(
  accountId: string,
  status: 'ACTIVE' | 'SUSPENDED',
  reason: string,
  options?: RequestOptions,
): Promise<ApiResult<PlatformAccountDetail>> {
  return apiPatch<PlatformAccountDetail>(
    `${BASE}/${encodeURIComponent(accountId)}/status`,
    { status, reason: reason.trim() || null },
    options,
  )
}

export function requestAccountRecovery(
  accountId: string,
  options?: RequestOptions,
): Promise<ApiResult<AccountAction>> {
  return apiPost<AccountAction>(
    `${BASE}/${encodeURIComponent(accountId)}/recovery`,
    {},
    options,
  )
}

export function resendAccountInvitation(
  accountId: string,
  options?: RequestOptions,
): Promise<ApiResult<AccountAction>> {
  return apiPost<AccountAction>(
    `${BASE}/${encodeURIComponent(accountId)}/invitation`,
    {},
    options,
  )
}

/**
 * Kept so the interface can state the limitation precisely: Supabase Auth has no
 * service-role endpoint that revokes another account's sessions. The engine
 * answers 501 and this function never pretends otherwise.
 */
export function revokeAccountSessions(
  accountId: string,
  options?: RequestOptions,
): Promise<ApiResult<AccountAction>> {
  return apiPost<AccountAction>(
    `${BASE}/${encodeURIComponent(accountId)}/revoke-sessions`,
    {},
    options,
  )
}

export function deleteAccount(
  accountId: string,
  confirmEmail: string,
  reason: string,
  options?: RequestOptions,
): Promise<ApiResult<AccountAction>> {
  return apiRequest<AccountAction>(
    `${BASE}/${encodeURIComponent(accountId)}`,
    {
      method: 'DELETE',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ confirm_email: confirmEmail, reason }),
    },
    options,
  )
}
