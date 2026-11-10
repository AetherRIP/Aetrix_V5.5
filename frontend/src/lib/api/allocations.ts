/**
 * Platform Classroom course allocation.
 *
 * An operator-recorded course stays UNVERIFIED; a workspace Classroom sync
 * writes VERIFIED rows. These calls are operator-only except the workspace
 * read, which is tenant-scoped by the engine.
 */

import { apiGet, apiPost, type ApiResult, type RequestOptions } from './client'

const BASE = '/api/v1/admin/allocations'

export type Verification = 'UNVERIFIED' | 'VERIFIED'
export type CourseState = 'ACTIVE' | 'ARCHIVED' | 'DELETED'
export type AllocationStatus = 'ACTIVE' | 'RELEASED'
export type AllocationOrigin = 'ALLOCATE' | 'REASSIGN'

export type ClassroomClass = {
  id: string
  course_id: string
  name: string
  section: string | null
  course_state: CourseState
  verification: Verification
  source: string
  owner_email: string | null
  synced_at: string | null
  created_at: string
}

export type WorkspaceTarget = {
  id: string
  name: string
  slug: string
  owner_label: string | null
  owner_email: string | null
  active_allocations: number
}

export type Allocation = {
  id: string
  classroom_class_id: string
  course_id: string
  class_name: string
  class_section: string | null
  verification: Verification
  workspace_id: string
  workspace_name: string
  status: AllocationStatus
  origin: AllocationOrigin
  allocated_by_subject: string
  allocated_by_label: string | null
  allocated_at: string
  released_by_subject: string | null
  released_by_label: string | null
  released_at: string | null
  release_reason: string | null
  reason: string | null
  previous_allocation_id: string | null
}

export type AllocationPage = {
  items: Allocation[]
  total: number
  limit: number
  offset: number
}

export type ClassroomOperation = {
  name: string
  supported: boolean
  note: string
}

export type ClassroomCapability = {
  allocation_available: boolean
  discovery_configured: boolean
  verification: Verification
  reason: string
  operations: ClassroomOperation[]
}

export type WorkspaceAllocation = {
  id: string
  course_id: string
  class_name: string
  class_section: string | null
  verification: Verification
  allocated_at: string
  allocated_by_label: string | null
}

export type ClassroomClassDraft = {
  course_id: string
  name: string
  section?: string
  owner_email?: string
  attested: true
}

export function classroomCapability(options: RequestOptions): Promise<ApiResult<ClassroomCapability>> {
  return apiGet<ClassroomCapability>(`${BASE}/capability`, options)
}

export function listWorkspaceTargets(options: RequestOptions): Promise<ApiResult<WorkspaceTarget[]>> {
  return apiGet<WorkspaceTarget[]>(`${BASE}/workspaces`, options)
}

export function listAvailableClasses(
  q: string,
  options: RequestOptions,
): Promise<ApiResult<ClassroomClass[]>> {
  const query = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''
  return apiGet<ClassroomClass[]>(`${BASE}/available-classes${query}`, options)
}

export function listAllocations(
  params: { status: 'ALL' | AllocationStatus; q?: string; limit?: number; offset?: number },
  options: RequestOptions,
): Promise<ApiResult<AllocationPage>> {
  const query = new URLSearchParams()
  query.set('status', params.status)
  query.set('limit', String(params.limit ?? 50))
  query.set('offset', String(params.offset ?? 0))
  if (params.q?.trim()) query.set('q', params.q.trim())
  return apiGet<AllocationPage>(`${BASE}?${query.toString()}`, options)
}

export function registerClassroomClass(
  draft: ClassroomClassDraft,
  options: RequestOptions,
): Promise<ApiResult<ClassroomClass>> {
  return apiPost<ClassroomClass>(`${BASE}/classes`, draft, options)
}

export function allocateClass(
  draft: { classroom_class_id: string; workspace_id: string; reason?: string },
  options: RequestOptions,
): Promise<ApiResult<Allocation>> {
  return apiPost<Allocation>(BASE, draft, options)
}

export function releaseAllocation(
  allocationId: string,
  reason: string,
  options: RequestOptions,
): Promise<ApiResult<Allocation>> {
  return apiPost<Allocation>(`${BASE}/${allocationId}/release`, { reason }, options)
}

export function reassignAllocation(
  allocationId: string,
  draft: { workspace_id: string; reason: string },
  options: RequestOptions,
): Promise<ApiResult<Allocation>> {
  return apiPost<Allocation>(`${BASE}/${allocationId}/reassign`, draft, options)
}

export function workspaceAllocations(
  workspaceId: string,
  options: RequestOptions,
): Promise<ApiResult<WorkspaceAllocation[]>> {
  return apiGet<WorkspaceAllocation[]>(
    `/api/v1/workspaces/${workspaceId}/classroom-allocations`,
    options,
  )
}
