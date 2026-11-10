import {
  apiBlob,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  apiUpload,
  type ApiResult,
  type RequestOptions,
} from './api/client'
import type {
  Assignment,
  AuditEvent,
  Blueprint,
  DocumentMeta,
  Exam,
  Gradebook,
  InboxItem,
  Invitation,
  Job,
  JobDetail,
  JobResults,
  MarkingHistoryPage,
  Me,
  Member,
  Notification,
  PageMeta,
  ReportRow,
  SchemeUpload,
  SchemeVersion,
  SchoolClass,
  Student,
  StudentImportResult,
  Submission,
  Workspace,
  Dashboard,
} from './api/types'

/**
 * The typed engine boundary.
 *
 * Every function takes the caller's bearer token explicitly: the screens never
 * build a URL, and a component cannot accidentally call the API without the
 * session that authorises it.
 */

type Opts = RequestOptions | undefined

export const identityService = {
  me: (options?: Opts): Promise<ApiResult<Me>> => apiGet<Me>('/api/v1/me', options),

  members: (workspaceId: string, options?: Opts): Promise<ApiResult<Member[]>> =>
    apiGet<Member[]>(`/api/v1/workspaces/${workspaceId}/members`, options),

  updateMemberRole: (
    workspaceId: string,
    userId: string,
    body: { role: string; reason?: string | null },
    options?: Opts,
  ): Promise<ApiResult<Member>> =>
    apiPatch<Member>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, body, options),

  invitations: (options?: Opts): Promise<ApiResult<Invitation[]>> =>
    apiGet<Invitation[]>('/api/v1/invitations', options),

  invite: (
    workspaceId: string,
    body: { email: string; role: string; expires_in_days?: number; note?: string },
    options?: Opts,
  ): Promise<ApiResult<Invitation>> =>
    apiPost<Invitation>(`/api/v1/workspaces/${workspaceId}/invitations`, body, options),

  revoke: (invitationId: string, reason: string, options?: Opts): Promise<ApiResult<Invitation>> =>
    apiPost<Invitation>(
      `/api/v1/invitations/${invitationId}/revoke?reason=${encodeURIComponent(reason)}`,
      {},
      options,
    ),

  accept: (code: string, options?: Opts): Promise<ApiResult<Me>> =>
    apiPost<Me>('/api/v1/invitations/accept', { code }, options),
}

export const workspaceService = {
  list: (options?: Opts): Promise<ApiResult<Workspace[]>> =>
    apiGet<Workspace[]>('/api/v1/workspaces', options),

  get: (workspaceId: string, options?: Opts): Promise<ApiResult<Workspace>> =>
    apiGet<Workspace>(`/api/v1/workspaces/${workspaceId}`, options),

  dashboard: (workspaceId: string, options?: Opts): Promise<ApiResult<Dashboard>> =>
    apiGet<Dashboard>(`/api/v1/workspaces/${workspaceId}/dashboard`, options),

  inbox: (workspaceId: string, options?: Opts): Promise<ApiResult<InboxItem[]>> =>
    apiGet<InboxItem[]>(`/api/v1/workspaces/${workspaceId}/inbox`, options),

  reports: (workspaceId: string, options?: Opts): Promise<ApiResult<ReportRow[]>> =>
    apiGet<ReportRow[]>(`/api/v1/workspaces/${workspaceId}/reports`, options),

  gradebook: (workspaceId: string, options?: Opts): Promise<ApiResult<Gradebook>> =>
    apiGet<Gradebook>(`/api/v1/workspaces/${workspaceId}/gradebook`, options),

  audit: (workspaceId: string, options?: Opts): Promise<ApiResult<AuditEvent[]>> =>
    apiGet<AuditEvent[]>(`/api/v1/workspaces/${workspaceId}/audit`, options),

  notifications: (workspaceId: string, options?: Opts): Promise<ApiResult<Notification[]>> =>
    apiGet<Notification[]>(`/api/v1/workspaces/${workspaceId}/notifications`, options),

  markingHistory: (
    workspaceId: string,
    query?: { limit?: number; offset?: number; state?: string },
    options?: Opts,
  ): Promise<ApiResult<MarkingHistoryPage>> => {
    const params = new URLSearchParams()
    if (query?.limit !== undefined) params.set('limit', String(query.limit))
    if (query?.offset !== undefined) params.set('offset', String(query.offset))
    if (query?.state) params.set('state', query.state)
    const suffix = params.toString() ? `?${params.toString()}` : ''
    return apiGet<MarkingHistoryPage>(
      `/api/v1/workspaces/${workspaceId}/marking-history${suffix}`,
      options,
    )
  },
}

export const rosterService = {
  classes: (workspaceId: string, options?: Opts): Promise<ApiResult<SchoolClass[]>> =>
    apiGet<SchoolClass[]>(`/api/v1/workspaces/${workspaceId}/classes`, options),

  createClass: (
    workspaceId: string,
    body: { name: string; year_group?: string | null },
    options?: Opts,
  ): Promise<ApiResult<SchoolClass>> =>
    apiPost<SchoolClass>(`/api/v1/workspaces/${workspaceId}/classes`, body, options),

  students: (
    workspaceId: string,
    query?: { class_id?: string },
    options?: Opts,
  ): Promise<ApiResult<Student[]>> =>
    apiGet<Student[]>(
      `/api/v1/workspaces/${workspaceId}/students${
        query?.class_id ? `?class_id=${encodeURIComponent(query.class_id)}` : ''
      }`,
      options,
    ),

  createStudent: (
    workspaceId: string,
    body: { student_ref: string; display_name?: string | null; class_id?: string | null },
    options?: Opts,
  ): Promise<ApiResult<Student>> =>
    apiPost<Student>(`/api/v1/workspaces/${workspaceId}/students`, body, options),

  importStudents: (
    workspaceId: string,
    file: File,
    options?: Opts,
  ): Promise<ApiResult<StudentImportResult>> => {
    const form = new FormData()
    form.set('file', file)
    return apiUpload<StudentImportResult>(
      `/api/v1/workspaces/${workspaceId}/students/import`,
      form,
      options,
    )
  },
}

export const examService = {
  list: (options?: Opts): Promise<ApiResult<Exam[]>> => apiGet<Exam[]>('/api/v1/exams', options),

  create: (
    body: { title: string; board?: string | null; paper_code?: string | null },
    options?: Opts,
  ): Promise<ApiResult<Exam>> => apiPost<Exam>('/api/v1/exams', body, options),

  blueprint: (examId: string, options?: Opts): Promise<ApiResult<Blueprint>> =>
    apiGet<Blueprint>(`/api/v1/exams/${examId}/blueprint`, options),

  putBlueprint: (
    examId: string,
    body: { structure: Blueprint['structure']; approve: boolean; reason?: string },
    options?: Opts,
  ): Promise<ApiResult<Blueprint>> =>
    apiPut<Blueprint>(`/api/v1/exams/${examId}/blueprint`, body, options),

  schemeVersions: (examId: string, options?: Opts): Promise<ApiResult<SchemeVersion[]>> =>
    apiGet<SchemeVersion[]>(`/api/v1/exams/${examId}/scheme-versions`, options),

  uploadScheme: (
    examId: string,
    title: string,
    file: File,
    options?: Opts,
  ): Promise<ApiResult<SchemeUpload>> => {
    const form = new FormData()
    form.set('title', title)
    form.set('file', file)
    return apiUpload<SchemeUpload>(`/api/v1/exams/${examId}/schemes`, form, options)
  },

  approveScheme: (versionId: string, reason: string, options?: Opts): Promise<ApiResult<SchemeVersion>> =>
    apiPost<SchemeVersion>(`/api/v1/schemes/${versionId}/approve`, { reason }, options),

  extract: (
    examId: string,
    schemeVersionId: string,
    options?: Opts,
  ): Promise<ApiResult<{ blueprint: Blueprint }>> =>
    apiPost<{ blueprint: Blueprint }>(
      `/api/v1/exams/${examId}/blueprint/extractions`,
      { scheme_version_id: schemeVersionId },
      options,
    ),
}

export const assignmentService = {
  list: (workspaceId: string, options?: Opts): Promise<ApiResult<Assignment[]>> =>
    apiGet<Assignment[]>(`/api/v1/workspaces/${workspaceId}/assignments`, options),

  get: (assignmentId: string, options?: Opts): Promise<ApiResult<Assignment>> =>
    apiGet<Assignment>(`/api/v1/assignments/${assignmentId}`, options),

  create: (
    body: {
      exam_id: string
      blueprint_version_id: string
      scheme_version_id: string
      name: string
      review_mode?: string
      completion_threshold?: number
    },
    options?: Opts,
  ): Promise<ApiResult<Assignment>> => apiPost<Assignment>('/api/v1/assignments', body, options),

  submissions: (assignmentId: string, options?: Opts): Promise<ApiResult<Submission[]>> =>
    apiGet<Submission[]>(`/api/v1/assignments/${assignmentId}/submissions`, options),
}

export const submissionService = {
  get: (submissionId: string, options?: Opts): Promise<ApiResult<Submission>> =>
    apiGet<Submission>(`/api/v1/submissions/${submissionId}`, options),

  register: (
    body: { assignment_id: string; student_ref: string; content_hash: string },
    options?: Opts,
  ): Promise<ApiResult<Submission>> => apiPost<Submission>('/api/v1/submissions', body, options),

  uploadDocument: (
    submissionId: string,
    file: File,
    options?: Opts,
  ): Promise<ApiResult<DocumentMeta>> => {
    const form = new FormData()
    form.set('file', file)
    return apiUpload<DocumentMeta>(`/api/v1/submissions/${submissionId}/documents`, form, options)
  },

  results: (submissionId: string, options?: Opts): Promise<ApiResult<JobResults>> =>
    apiGet<JobResults>(`/api/v1/submissions/${submissionId}/results`, options),

  pages: (submissionId: string, options?: Opts): Promise<ApiResult<PageMeta[]>> =>
    apiGet<PageMeta[]>(`/api/v1/submissions/${submissionId}/pages`, options),

  pageImage: (submissionId: string, pageIndex: number, options?: Opts): Promise<ApiResult<Blob>> =>
    apiBlob(`/api/v1/submissions/${submissionId}/pages/${pageIndex}`, options),

  jobs: (submissionId: string, options?: Opts): Promise<ApiResult<Job[]>> =>
    apiGet<Job[]>(`/api/v1/submissions/${submissionId}/corrections`, options),
}

export const queueService = {
  list: (workspaceId: string, options?: Opts): Promise<ApiResult<Job[]>> =>
    apiGet<Job[]>(`/api/v1/workspaces/${workspaceId}/corrections`, options),

  detail: (jobId: string, options?: Opts): Promise<ApiResult<JobDetail>> =>
    apiGet<JobDetail>(`/api/v1/corrections/${jobId}`, options),

  cancel: (jobId: string, options?: Opts): Promise<ApiResult<Job>> =>
    apiPost<Job>(`/api/v1/corrections/${jobId}/cancel`, {}, options),

  retry: (jobId: string, options?: Opts): Promise<ApiResult<Job>> =>
    apiPost<Job>(`/api/v1/corrections/${jobId}/retry`, {}, options),

  create: (
    body: { assignment_id: string; submission_id: string },
    options?: Opts,
  ): Promise<ApiResult<Job>> => apiPost<Job>('/api/v1/corrections', body, options),
}

export const resultsService = {
  override: (
    questionResultId: string,
    body: { awarded_marks: number; reason: string; expected_record_version?: number },
    options?: Opts,
  ): Promise<ApiResult<JobResults>> =>
    apiPost<JobResults>(`/api/v1/results/${questionResultId}/override`, body, options),

  review: (
    jobId: string,
    questionId: string,
    body: {
      decision: 'UPHOLD' | 'CHANGE' | 'INDEPENDENT'
      awarded_marks?: number
      reason: string
    },
    options?: Opts,
  ): Promise<ApiResult<JobResults>> =>
    apiPost<JobResults>(
      `/api/v1/corrections/${jobId}/reviews/${encodeURIComponent(questionId)}`,
      body,
      options,
    ),

  approve: (
    jobId: string,
    body: { note?: string; expected_record_version?: number },
    options?: Opts,
  ): Promise<ApiResult<JobResults>> =>
    apiPost<JobResults>(`/api/v1/corrections/${jobId}/approve`, body, options),
}

/** The engine's own liveness and readiness answers. */
export type EngineHealth = { status: string; service: string; version: string }

export type EngineReadiness = { status: string; database: string }

export const healthService = {
  live: (options?: Opts): Promise<ApiResult<EngineHealth>> => apiGet<EngineHealth>('/health', options),

  ready: (options?: Opts): Promise<ApiResult<EngineReadiness>> =>
    apiGet<EngineReadiness>('/ready', options),
}

/**
 * Every subsystem, observed separately.
 *
 * `unknown` is a real answer: this build has no observation. It is deliberately
 * distinct from `unavailable`, which means the subsystem was seen to be down.
 */
export type SubsystemState = 'ok' | 'degraded' | 'unavailable' | 'unknown' | 'not_implemented'

export type SubsystemStatus = {
  state: SubsystemState
  summary: string
  detail: string | null
}

export type FeatureStatus = {
  name: string
  state: 'available' | 'not_implemented'
  reason: string
}

/**
 * Whether the component exists, what it is doing now, and whether it can do its
 * job — three separate facts the engine reports separately.
 */
export type ComponentDeployment = 'deployed' | 'not_deployed' | 'not_configured' | 'unknown'

export type ComponentOperational =
  | 'available'
  | 'starting'
  | 'degraded'
  | 'unavailable'
  | 'unverified'
  | 'unknown'

export type ComponentReadiness =
  | 'ready'
  | 'not_ready'
  | 'not_applicable'
  | 'unavailable'
  | 'unknown'

export type ComponentHealth = {
  name: string
  deployment: ComponentDeployment
  operational: ComponentOperational
  readiness: ComponentReadiness
  checked_at: string
  last_success_at: string | null
  last_failure_at: string | null
  last_failure: string | null
  diagnostic: string
}

export type SystemStatus = {
  checked_at: string
  service: string
  version: string
  environment: string
  api: SubsystemStatus
  engine: SubsystemStatus
  readiness: SubsystemStatus
  database: SubsystemStatus
  worker: SubsystemStatus
  provider: SubsystemStatus
  /** Absent only if an older engine build answers without component detail. */
  components?: ComponentHealth[]
  features: FeatureStatus[]
}

export const statusService = {
  read: (options?: Opts): Promise<ApiResult<SystemStatus>> =>
    apiGet<SystemStatus>('/status', options),
}

/** SHA-256 of a file, hex encoded — the submission's content identity. */
export async function sha256File(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}
