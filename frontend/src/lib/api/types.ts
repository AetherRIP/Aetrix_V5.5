/**
 * Typed contracts for the correction engine.
 *
 * These mirror the engine's domain (`backend/app/db/models.py`) rather than the
 * database tables directly, so the interface can be connected to the deployed
 * API without reshaping components. No value here is invented at runtime: every
 * screen that needs one renders an unavailable state until the API exists.
 */

export type Role = 'OWNER' | 'EXAM_MANAGER' | 'MARKER' | 'VIEWER'

export type Workspace = {
  id: string
  name: string
  slug: string
  role: Role
  isDemo: boolean
}

export type AssignmentState = 'DRAFT' | 'OPEN' | 'MARKING' | 'REVIEW' | 'COMPLETE'

export type Assignment = {
  id: string
  workspaceId: string
  title: string
  examCode: string | null
  state: AssignmentState
  submissionCount: number
  blueprintApproved: boolean
  updatedAt: string
}

export type SubmissionStatus = 'RECEIVED' | 'PROCESSING' | 'READY' | 'FAILED'

export type Submission = {
  id: string
  assignmentId: string
  studentRef: string
  status: SubmissionStatus
  pages: number
  receivedAt: string
}

export type CorrectionState =
  | 'CREATED'
  | 'VALIDATING'
  | 'PROCESSING_DOCUMENTS'
  | 'BUILDING_BLUEPRINT'
  | 'CORRECTING'
  | 'VERIFYING'
  | 'COHORT_PENDING'
  | 'REVIEW_REQUIRED'
  | 'FINALIZING'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'FAILED'
  | 'RETRY_SUSPENDED'

export type CorrectionJob = {
  id: string
  submissionId: string
  state: CorrectionState
  errorCode: string | null
  updatedAt: string
}

export type ReportState = 'PENDING' | 'READY' | 'UNAVAILABLE'

export type Report = {
  id: string
  assignmentId: string
  title: string
  state: ReportState
  generatedAt: string | null
}

export type InboxKind = 'REVIEW_REQUIRED' | 'JOB_FAILED' | 'BLUEPRINT_DRAFT' | 'SYSTEM'

export type InboxItem = {
  id: string
  kind: InboxKind
  title: string
  detail: string
  createdAt: string
  read: boolean
}
