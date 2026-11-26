/**
 * Google Classroom integration.
 *
 * Two surfaces: platform administration owns the single central Google account
 * and course allocation; a workspace's teachers read only the courses allocated
 * to them.  No contract here carries a token, a client secret or a raw Google
 * payload — the browser never sees a credential.
 */

import {
  apiGet,
  apiPatch,
  apiPost,
  apiRequest,
  type ApiResult,
  type RequestOptions,
} from './client'

const ADMIN = '/api/v1/admin/classroom'
const WORK = '/api/v1/workspaces'

// -- shared shapes ---------------------------------------------------------

export type ClassroomConnectionStatus =
  | 'NOT_CONNECTED'
  | 'CONNECTED'
  | 'RECONNECT_REQUIRED'

export type ClassroomSyncStatus = 'SUCCEEDED' | 'FAILED' | null
export type Verification = 'UNVERIFIED' | 'VERIFIED'
export type CourseState = 'ACTIVE' | 'ARCHIVED' | 'DELETED'
export type CourseworkState = 'DRAFT' | 'PUBLISHING' | 'PUBLISHED' | 'FAILED'
export type SubmissionState =
  | 'DISCOVERED'
  | 'INGESTED'
  | 'INGEST_FAILED'
  | 'CORRECTING'
  | 'CORRECTED'
  | 'WITHDRAWN'
export type PublicationState = 'SUCCEEDED' | 'FAILED' | 'UNKNOWN' | 'CONFLICT'

export type ClassroomConnection = {
  configured: boolean
  status: ClassroomConnectionStatus
  redirect_uri: string | null
  required_scopes: string[]
  granted_scopes: string[]
  missing_scopes: string[]
  connected_at: string | null
  connected_by_subject: string | null
  connected_account_email: string | null
  connected_account_name: string | null
  last_refresh_at: string | null
  last_synced_at: string | null
  last_sync_status: ClassroomSyncStatus
  last_sync_counts: Record<string, number>
  last_error_code: string | null
  last_error_message: string | null
  recent_runs: ClassroomSyncRun[]
}

export type ClassroomSyncRun = {
  id: string
  kind?: 'COURSES' | 'ROSTER' | 'SUBMISSIONS'
  status: 'RUNNING' | 'SUCCEEDED' | 'PARTIAL' | 'FAILED'
  counts: Record<string, number>
  actor_subject: string
  error_code: string | null
  error_message: string | null
  started_at: string
  finished_at: string | null
}

export type ClassroomAuthorizationStart = {
  authorization_url: string
  expires_at: string
  redirect_uri: string
  scopes: string[]
}

export type ClassroomSyncResult = {
  status: 'SUCCEEDED'
  synced_at: string
  counts: { discovered: number; created: number; updated: number }
  truncated: boolean
  courses: {
    course_id: string
    name: string
    section: string | null
    course_state: CourseState
  }[]
}

export type ClassroomDisconnectResult = {
  status: 'RECONNECT_REQUIRED'
  revoked: boolean
}

export type AdminCourse = {
  id: string
  course_id: string
  name: string
  section: string | null
  room: string | null
  course_state: CourseState
  teacher_name: string | null
  owner_email: string | null
  verification: Verification
  synced_at: string | null
  workspace_id: string | null
  workspace_name: string | null
  allocation_id: string | null
  allocated_at: string | null
}

export type TeacherCourse = {
  allocation_id: string
  classroom_class_id: string
  course_id: string
  name: string
  section: string | null
  course_state: string
  students: number
  coursework: number
}

export type ClassroomClassAssignment = {
  id: string
  allocation_id: string
  classroom_class_id: string
  course_id: string
  class_name: string
  user_id: string
  user_label: string | null
  user_email: string | null
  user_role: string
  assigned_by_label: string | null
  assigned_at: string
}

export type RosterEntry = {
  google_user_id: string
  student_id: string
  student_ref: string
  display_name: string | null
  google_name: string | null
  email: string | null
  status: 'ACTIVE' | 'REMOVED'
  match_source: 'EXTERNAL_ID' | 'CREATED' | 'MANUAL'
  last_seen_at: string
}

export type RosterSyncResult = {
  status: 'SUCCEEDED' | 'PARTIAL'
  course_id: string
  counts: Record<string, number>
  truncated: boolean
  entries: RosterEntry[]
  problems: string[]
}

export type Coursework = {
  id: string
  assignment_id: string
  assignment_name: string
  classroom_class_id: string
  course_id: string
  coursework_id: string | null
  state: CourseworkState
  title: string
  description: string | null
  due_at: string | null
  max_points: string | number | null
  publish_attempts: number
  published_at: string | null
  published_by_subject: string | null
  last_error_code: string | null
  last_error_message: string | null
  submissions: number
  created_at: string
}

export type Submission = {
  id: string
  coursework_link_id: string
  assignment_id: string
  google_submission_id: string
  google_user_id: string
  student_id: string
  student_ref: string
  student_name: string | null
  state: SubmissionState
  submission_state: string | null
  late: boolean
  submission_id: string | null
  document_id: string | null
  attachments: {
    kind?: string
    title?: string | null
    mime_type?: string | null
    drive_file_id?: string | null
  }[]
  content_hash: string | null
  last_synced_at: string | null
  ingest_error: string | null
  correction_job_id: string | null
  correction_state: string | null
  approved_total: string | number | null
  approved_max: string | number | null
  approved_at: string | null
  last_publication_state: PublicationState | null
  created_at: string
}

export type SubmissionSyncResult = {
  status: 'SUCCEEDED' | 'PARTIAL'
  coursework_link_id: string
  counts: Record<string, number>
  truncated: boolean
  submissions: Submission[]
  problems: string[]
}

export type CorrectionStart = {
  submission_link_id: string
  job_id: string
  job_state: string
  created: boolean
}

export type Review = {
  submission_link_id: string
  job_id: string | null
  job_state: string | null
  total: string | number
  maximum: string | number
  uncertain: { question_id: string; status: string; max_marks: number }[]
  approvable: boolean
  reason: string
}

export type GradePublication = {
  id: string
  submission_link_id: string
  state: PublicationState
  draft_grade: string | number | null
  assigned_grade: string | number | null
  approved_by_subject: string
  approved_by_role: string
  authorized_by_subject: string
  reason: string | null
  external_grade_before: string | number | null
  response_detail: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  attempted_at: string
  resolved_at: string | null
}

export type PublicationStatus = {
  submission_link_id: string
  approved_total: string | number | null
  published: boolean
  state: PublicationState | null
  attempts: number
  history: GradePublication[]
}

// -- platform administration ----------------------------------------------

export function classroomConnection(
  options: RequestOptions,
): Promise<ApiResult<ClassroomConnection>> {
  return apiGet<ClassroomConnection>(`${ADMIN}/connection`, options)
}

export function startClassroomOAuth(
  options: RequestOptions,
): Promise<ApiResult<ClassroomAuthorizationStart>> {
  return apiPost<ClassroomAuthorizationStart>(`${ADMIN}/oauth/start`, undefined, options)
}

export function completeClassroomOAuth(
  payload: { code: string; state: string },
  options: RequestOptions,
): Promise<ApiResult<ClassroomConnection>> {
  return apiPost<ClassroomConnection>(`${ADMIN}/oauth/complete`, payload, options)
}

export function syncClassroom(
  options: RequestOptions,
): Promise<ApiResult<ClassroomSyncResult>> {
  return apiPost<ClassroomSyncResult>(`${ADMIN}/sync`, undefined, options)
}

export function disconnectClassroom(
  options: RequestOptions,
): Promise<ApiResult<ClassroomDisconnectResult>> {
  return apiPost<ClassroomDisconnectResult>(`${ADMIN}/disconnect`, undefined, options)
}

export function adminCourses(
  q: string,
  options: RequestOptions,
): Promise<ApiResult<AdminCourse[]>> {
  const query = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''
  return apiGet<AdminCourse[]>(`${ADMIN}/courses${query}`, options)
}

export function adminSyncRuns(options: RequestOptions): Promise<ApiResult<ClassroomSyncRun[]>> {
  return apiGet<ClassroomSyncRun[]>(`${ADMIN}/sync-runs`, options)
}

// -- workspace -------------------------------------------------------------

export function workspaceCourses(
  workspaceId: string,
  options: RequestOptions,
): Promise<ApiResult<TeacherCourse[]>> {
  return apiGet<TeacherCourse[]>(`${WORK}/${workspaceId}/classroom/courses`, options)
}

export function classroomRoster(
  workspaceId: string,
  courseId: string,
  options: RequestOptions,
): Promise<ApiResult<RosterEntry[]>> {
  return apiGet<RosterEntry[]>(
    `${WORK}/${workspaceId}/classroom/courses/${courseId}/roster`,
    options,
  )
}

export function classroomClassAssignments(
  workspaceId: string,
  courseId: string,
  options: RequestOptions,
): Promise<ApiResult<ClassroomClassAssignment[]>> {
  return apiGet<ClassroomClassAssignment[]>(
    `${WORK}/${workspaceId}/classroom/courses/${courseId}/assignments`,
    options,
  )
}

export function createClassroomClassAssignment(
  workspaceId: string,
  courseId: string,
  userId: string,
  options: RequestOptions,
): Promise<ApiResult<ClassroomClassAssignment>> {
  return apiPost<ClassroomClassAssignment>(
    `${WORK}/${workspaceId}/classroom/courses/${courseId}/assignments`,
    { user_id: userId },
    options,
  )
}

export function removeClassroomClassAssignment(
  workspaceId: string,
  courseId: string,
  assignmentId: string,
  options: RequestOptions,
): Promise<ApiResult<null>> {
  return apiRequest<null>(
    `${WORK}/${workspaceId}/classroom/courses/${courseId}/assignments/${assignmentId}`,
    { method: 'DELETE' },
    options,
  )
}

export function syncClassroomRoster(
  workspaceId: string,
  courseId: string,
  options: RequestOptions,
): Promise<ApiResult<RosterSyncResult>> {
  return apiPost<RosterSyncResult>(
    `${WORK}/${workspaceId}/classroom/courses/${courseId}/sync-roster`,
    undefined,
    options,
  )
}

export function listCoursework(
  workspaceId: string,
  options: RequestOptions,
): Promise<ApiResult<Coursework[]>> {
  return apiGet<Coursework[]>(`${WORK}/${workspaceId}/classroom/coursework`, options)
}

export function createCoursework(
  workspaceId: string,
  draft: {
    assignment_id: string
    classroom_class_id: string
    title?: string
    description?: string
    due_at?: string
    max_points?: number
  },
  options: RequestOptions,
): Promise<ApiResult<Coursework>> {
  return apiPost<Coursework>(`${WORK}/${workspaceId}/classroom/coursework`, draft, options)
}

export function publishCoursework(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<Coursework>> {
  return apiPost<Coursework>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}/publish`,
    undefined,
    options,
  )
}

export function updateCoursework(
  workspaceId: string,
  linkId: string,
  draft: { title?: string; description?: string; due_at?: string; max_points?: number },
  options: RequestOptions,
): Promise<ApiResult<Coursework>> {
  return apiPatch<Coursework>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}`,
    draft,
    options,
  )
}

export function courseworkSubmissions(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<Submission[]>> {
  return apiGet<Submission[]>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}/submissions`,
    options,
  )
}

export function syncCourseworkSubmissions(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<SubmissionSyncResult>> {
  return apiPost<SubmissionSyncResult>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}/submissions/sync`,
    { coursework_link_id: linkId, only_turned_in: true },
    options,
  )
}

export function ingestSubmission(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<Submission>> {
  return apiPost<Submission>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/ingest`,
    undefined,
    options,
  )
}

export function startSubmissionCorrection(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<CorrectionStart>> {
  return apiPost<CorrectionStart>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/correct`,
    undefined,
    options,
  )
}

export function submissionReview(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<Review>> {
  return apiGet<Review>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/review`,
    options,
  )
}

export function approveSubmission(
  workspaceId: string,
  linkId: string,
  note: string | undefined,
  options: RequestOptions,
): Promise<ApiResult<Review>> {
  return apiPost<Review>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/approve`,
    { confirm: true, note },
    options,
  )
}

export function submissionPublication(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<PublicationStatus>> {
  return apiGet<PublicationStatus>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/publication`,
    options,
  )
}

export function publishSubmissionGrade(
  workspaceId: string,
  linkId: string,
  payload: {
    confirm: true
    reason: string
    grade_field: 'assignedGrade' | 'draftGrade'
    return_to_student: boolean
    allow_overwrite_external: boolean
  },
  options: RequestOptions,
): Promise<ApiResult<GradePublication>> {
  return apiPost<GradePublication>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/publish-grade`,
    payload,
    options,
  )
}

export type WorkspaceAssignment = {
  id: string
  name: string
  exam_id: string
  blueprint_version_id: string | null
  scheme_version_id: string | null
}

export function workspaceAssignments(
  workspaceId: string,
  options: RequestOptions,
): Promise<ApiResult<WorkspaceAssignment[]>> {
  return apiGet<WorkspaceAssignment[]>(`/api/v1/workspaces/${workspaceId}/assignments`, options)
}

// -- automatic submission monitoring ---------------------------------------

export type MonitorHealth =
  | 'DISABLED'
  | 'PAUSED'
  | 'HEALTHY'
  | 'DEGRADED'
  | 'BLOCKED'
  | 'UNKNOWN'

export type MonitorPipelineState =
  | 'DETECTED'
  | 'DOWNLOADING'
  | 'INSPECTING'
  | 'READY'
  | 'IGNORED'
  | 'NEEDS_TEACHER'
  | 'SUPERSEDED'
  | 'FAILED'

export type MonitorCorrectionState =
  | 'NOT_QUEUED'
  | 'QUEUED'
  | 'PROCESSING'
  | 'REVIEW_REQUIRED'
  | 'COMPLETED'
  | 'FAILED'

export type MonitorRelevance =
  | 'UNASSESSED'
  | 'LIKELY_RELEVANT'
  | 'POSSIBLY_UNRELATED'
  | 'INSUFFICIENT_EVIDENCE'
  | 'CANNOT_DETERMINE'

export type MonitorState = {
  coursework_link_id: string
  assignment_id: string
  assignment_name: string
  course_id: string
  coursework_id: string | null
  enabled: boolean
  paused: boolean
  auto_queue: boolean
  relevance_policy: 'STRUCTURAL_ALLOW' | 'TEXT_REQUIRED'
  interval_seconds: number
  health: MonitorHealth
  next_poll_at: string | null
  last_polled_at: string | null
  last_poll_status: string | null
  last_poll_error: string | null
  last_error_code: string | null
  consecutive_failures: number
  last_counts: Record<string, number>
  monitoring_since: string | null
  enabled_by_subject: string | null
  expected_students: number
  submitted_students: number
  awaiting_review: number
  ready_submissions: number
  queued_corrections: number
  processing_corrections: number
  completed_corrections: number
  failed_corrections: number
}

export type MonitorOverview = {
  workspace_id: string
  monitoring_enabled_on_server: boolean
  states: MonitorState[]
  recent_runs: Array<{
    id: string
    coursework_link_id: string | null
    trigger: string
    status: string
    counts: Record<string, number>
    started_at: string
    finished_at: string | null
    error_message: string | null
  }>
}

export type MonitorAttachment = {
  position: number
  kind: string
  title: string | null
  declared_mime: string | null
  detected_mime: string | null
  size_bytes: number | null
  status: string
  page_count: number | null
  sha256: string | null
  reason: string | null
  issues: Array<{ code: string; message: string; severity?: string }>
}

export type MonitorSubmission = {
  submission_link_id: string
  google_submission_id: string
  google_user_id: string
  student_id: string
  student_ref: string
  student_name: string | null
  google_state: string | null
  late: boolean
  detected_at: string | null
  last_synced_at: string | null
  version: number
  version_count: number
  state: MonitorPipelineState
  correction_state: MonitorCorrectionState
  eligibility: 'PENDING' | 'ELIGIBLE' | 'NEEDS_TEACHER' | 'BLOCKED'
  relevance: MonitorRelevance
  decision_reasons: Array<{ code?: string; message?: string; severity?: string }>
  inspection: Record<string, unknown>
  attachments: MonitorAttachment[]
  correction_job_id: string | null
  document_id: string | null
  last_error: string | null
  last_error_code: string | null
  superseded_at: string | null
  resolution_note: string | null
}

export type MonitorSyncResult = {
  status: 'SUCCEEDED' | 'PARTIAL' | 'FAILED' | 'SKIPPED'
  coursework_link_id: string
  counts: Record<string, number>
  problems: string[]
  state: MonitorState
}

export type MonitorRetryResult = {
  submission_link_id: string
  state: MonitorPipelineState
  correction_state: MonitorCorrectionState
  retried: boolean
  message: string
}

export type MonitorUpdate = {
  enabled?: boolean
  paused?: boolean
  auto_queue?: boolean
  interval_seconds?: number
  relevance_policy?: 'STRUCTURAL_ALLOW' | 'TEXT_REQUIRED'
  reason?: string
}

export function classroomMonitoringOverview(
  workspaceId: string,
  options: RequestOptions,
): Promise<ApiResult<MonitorOverview>> {
  return apiGet<MonitorOverview>(`${WORK}/${workspaceId}/classroom/monitoring`, options)
}

export function classroomMonitorState(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<MonitorState>> {
  return apiGet<MonitorState>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}/monitoring`,
    options,
  )
}

export function updateClassroomMonitoring(
  workspaceId: string,
  linkId: string,
  payload: MonitorUpdate,
  options: RequestOptions,
): Promise<ApiResult<MonitorState>> {
  return apiPatch<MonitorState>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}/monitoring`,
    payload,
    options,
  )
}

export function syncClassroomMonitoring(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<MonitorSyncResult>> {
  return apiPost<MonitorSyncResult>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}/monitoring/sync`,
    undefined,
    options,
  )
}

export function monitoredSubmissions(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<MonitorSubmission[]>> {
  return apiGet<MonitorSubmission[]>(
    `${WORK}/${workspaceId}/classroom/coursework/${linkId}/monitoring/submissions`,
    options,
  )
}

export function retryMonitoredSubmission(
  workspaceId: string,
  linkId: string,
  options: RequestOptions,
): Promise<ApiResult<MonitorRetryResult>> {
  return apiPost<MonitorRetryResult>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/monitoring/retry`,
    undefined,
    options,
  )
}

export function ignoreMonitoredSubmission(
  workspaceId: string,
  linkId: string,
  note: string,
  options: RequestOptions,
): Promise<ApiResult<MonitorSubmission>> {
  return apiPost<MonitorSubmission>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/monitoring/ignore`,
    { note },
    options,
  )
}

export function resolveMonitoredSubmission(
  workspaceId: string,
  linkId: string,
  action: 'ACCEPT' | 'IGNORE' | 'REQUEUE',
  note: string,
  options: RequestOptions,
): Promise<ApiResult<MonitorSubmission>> {
  return apiPost<MonitorSubmission>(
    `${WORK}/${workspaceId}/classroom/submissions/${linkId}/monitoring/resolve`,
    { action, note },
    options,
  )
}
