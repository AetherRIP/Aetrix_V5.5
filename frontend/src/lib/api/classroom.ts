/**
 * Google Classroom authorisation and course discovery.
 *
 * The engine derives the workspace from the verified token, so no call names a
 * workspace. Tokens never appear in these contracts: the connection is described
 * by its status, scopes and last sync, never by a credential.
 */

import { apiGet, apiPost, type ApiResult, type RequestOptions } from './client'

const BASE = '/api/v1/classroom'

export type ClassroomConnectionStatus =
  | 'NOT_CONNECTED'
  | 'CONNECTED'
  | 'RECONNECT_REQUIRED'

export type ClassroomConnection = {
  configured: boolean
  status: ClassroomConnectionStatus
  redirect_uri: string | null
  required_scopes: string[]
  granted_scopes: string[]
  connected_at: string | null
  connected_by_subject: string | null
  last_synced_at: string | null
  last_sync_status: 'SUCCEEDED' | 'FAILED' | null
  last_sync_counts: Record<string, number>
  last_error_code: string | null
  last_error_message: string | null
}

export type ClassroomAuthorizationStart = {
  authorization_url: string
  expires_at: string
  redirect_uri: string
  scopes: string[]
}

export type ClassroomSyncCounts = {
  discovered: number
  created: number
  updated: number
}

export type ClassroomSyncedCourse = {
  course_id: string
  name: string
  section: string | null
  course_state: 'ACTIVE' | 'ARCHIVED' | 'DELETED'
}

export type ClassroomSyncResult = {
  status: 'SUCCEEDED'
  synced_at: string
  counts: ClassroomSyncCounts
  truncated: boolean
  courses: ClassroomSyncedCourse[]
}

export type ClassroomDisconnectResult = {
  status: 'RECONNECT_REQUIRED'
  revoked: boolean
}

export function classroomConnection(
  options: RequestOptions,
): Promise<ApiResult<ClassroomConnection>> {
  return apiGet<ClassroomConnection>(`${BASE}/connection`, options)
}

export function startClassroomOAuth(
  options: RequestOptions,
): Promise<ApiResult<ClassroomAuthorizationStart>> {
  return apiPost<ClassroomAuthorizationStart>(`${BASE}/oauth/start`, undefined, options)
}

export function completeClassroomOAuth(
  payload: { code: string; state: string },
  options: RequestOptions,
): Promise<ApiResult<ClassroomConnection>> {
  return apiPost<ClassroomConnection>(`${BASE}/oauth/complete`, payload, options)
}

export function syncClassroom(
  options: RequestOptions,
): Promise<ApiResult<ClassroomSyncResult>> {
  return apiPost<ClassroomSyncResult>(`${BASE}/sync`, undefined, options)
}

export function disconnectClassroom(
  options: RequestOptions,
): Promise<ApiResult<ClassroomDisconnectResult>> {
  return apiPost<ClassroomDisconnectResult>(`${BASE}/disconnect`, undefined, options)
}
