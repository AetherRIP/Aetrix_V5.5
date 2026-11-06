import { apiGet, type ApiResult } from './api/client'
import type {
  Assignment,
  CorrectionJob,
  InboxItem,
  Report,
  Submission,
  Workspace,
} from './api/types'

export type ServiceOptions = { token?: string | null }

/**
 * Feature services. Each one is a thin, typed boundary over the engine API so
 * that screens depend on a contract rather than on `fetch`, a URL or Supabase.
 * Every call currently resolves to `unavailable` while the engine is undeployed.
 */
export const workspaceService = {
  list: (options?: ServiceOptions): Promise<ApiResult<Workspace[]>> =>
    apiGet<Workspace[]>('/api/v1/workspaces', options),

  get: (workspaceId: string, options?: ServiceOptions): Promise<ApiResult<Workspace>> =>
    apiGet<Workspace>(`/api/v1/workspaces/${workspaceId}`, options),
}

export const assignmentService = {
  list: (workspaceId: string, options?: ServiceOptions): Promise<ApiResult<Assignment[]>> =>
    apiGet<Assignment[]>(`/api/v1/workspaces/${workspaceId}/assignments`, options),

  get: (assignmentId: string, options?: ServiceOptions): Promise<ApiResult<Assignment>> =>
    apiGet<Assignment>(`/api/v1/assignments/${assignmentId}`, options),
}

export const submissionService = {
  list: (assignmentId: string, options?: ServiceOptions): Promise<ApiResult<Submission[]>> =>
    apiGet<Submission[]>(`/api/v1/assignments/${assignmentId}/submissions`, options),

  get: (submissionId: string, options?: ServiceOptions): Promise<ApiResult<Submission>> =>
    apiGet<Submission>(`/api/v1/submissions/${submissionId}`, options),

  jobs: (submissionId: string, options?: ServiceOptions): Promise<ApiResult<CorrectionJob[]>> =>
    apiGet<CorrectionJob[]>(`/api/v1/submissions/${submissionId}/corrections`, options),
}

export const queueService = {
  list: (workspaceId: string, options?: ServiceOptions): Promise<ApiResult<CorrectionJob[]>> =>
    apiGet<CorrectionJob[]>(`/api/v1/workspaces/${workspaceId}/corrections`, options),
}

export const inboxService = {
  list: (workspaceId: string, options?: ServiceOptions): Promise<ApiResult<InboxItem[]>> =>
    apiGet<InboxItem[]>(`/api/v1/workspaces/${workspaceId}/inbox`, options),
}

export const reportService = {
  list: (workspaceId: string, options?: ServiceOptions): Promise<ApiResult<Report[]>> =>
    apiGet<Report[]>(`/api/v1/workspaces/${workspaceId}/reports`, options),
}
