/**
 * Typed contracts for the correction engine.
 *
 * These mirror the engine's response models (`backend/app/schemas/*`) field for
 * field, in snake_case, so a screen cannot be written against a shape the API
 * does not return. Optional fields are genuinely optional in the API.
 */

export type EngineRole =
  | 'OWNER'
  | 'ADMIN'
  | 'TEACHER'
  | 'REVIEWER'
  | 'VIEWER'
  | 'PLATFORM_OWNER'

export type UiRole = 'owner' | 'supervisor' | 'assistant' | 'viewer' | 'platform_operator'

export type Me = {
  user_id: string
  subject: string
  email: string | null
  display_name: string | null
  tenant_id: string
  workspace_name: string
  workspace_slug: string
  role: EngineRole
  ui_role: UiRole
  capabilities: string[]
  /**
   * Platform authority from the verified claim — a different fact from the
   * workspace role. Only a PLATFORM_OWNER carries the `platform_admin`
   * capability, so a platform administrator is recognisable only here.
   */
  is_platform_admin?: boolean
  is_demo: boolean
}

export type Workspace = {
  id: string
  name: string
  slug: string
  role: string
  is_demo: boolean
}

export type Member = {
  id: string
  subject: string
  email: string | null
  display_name: string | null
  role: EngineRole
  created_at: string
}

export type SchoolClass = {
  id: string
  name: string
  year_group: string | null
  student_count: number
  created_at: string
}

export type Student = {
  id: string
  student_ref: string
  display_name: string | null
  class_id: string | null
  created_at: string
}

export type Invitation = {
  id: string
  email: string
  role: EngineRole
  status: 'PENDING' | 'ACCEPTED' | 'REVOKED'
  expires_at: string
  accepted_at: string | null
  revoked_at: string | null
  note: string | null
  created_at: string
  acceptance_code?: string
}

export type Exam = {
  id: string
  title: string
  board: string | null
  paper_code: string | null
  created_at: string
}

export type Assignment = {
  id: string
  exam_id: string
  blueprint_version_id: string | null
  scheme_version_id: string | null
  name: string
  completion_threshold: number
  review_mode: 'ECONOMY' | 'BALANCED' | 'ACCURACY'
  created_at: string
}

/**
 * How much of the individual-student report to render. `summary` stops after
 * the overview, `standard` adds the question breakdown, `detailed` adds the
 * student's work and the approved scheme for every question.
 */
export type ReportDetail = 'summary' | 'standard' | 'detailed'

export type Submission = {
  id: string
  assignment_id: string
  student_ref: string
  status: 'REGISTERED' | 'PROCESSING' | 'PROCESSED' | 'FAILED'
  content_hash: string
  created_at: string
}

export type JobState =
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
  | 'FAILED'
  | 'CANCELLED'
  | 'RETRY_SUSPENDED'

export type Job = {
  id: string
  assignment_id: string
  submission_id: string
  blueprint_version_id: string
  scheme_version_id: string
  state: JobState
  progress: number
  attempts: number
  max_attempts: number
  cancel_requested: boolean
  error_code: string | null
  error_message: string | null
  retryable: boolean | null
  resume_state: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  record_version: number
  engine_name: string | null
  engine_version: string | null
  /** AUTOMATED_REFUSED means this run is evidence, not the submission's result. */
  result_source: string | null
  recovery_of_job_id: string | null
  requested_engine_name: string | null
}

export type JobEvent = {
  id: string
  event_seq: number
  from_state: string | null
  to_state: string
  detail: Record<string, unknown>
  actor: string
  created_at: string
}

export type JobSubmissionContext = {
  id: string
  assignment_id: string
  student_ref: string
  status: Submission['status']
  content_hash: string
  created_at: string
}

export type JobDocumentContext = {
  id: string
  kind: 'STUDENT' | 'MARK_SCHEME' | 'QUESTION_PAPER'
  original_filename: string
  sha256: string
  mime_type: string
  size_bytes: number
  page_count: number
  status: 'UPLOADED' | 'VALIDATED' | 'REJECTED' | 'PROCESSED'
  ordering_status: 'ORDERED' | 'ORDER_SUSPECT' | 'UNVERIFIED'
  mapping_status: 'UNMAPPED' | 'MAPPED' | 'PARTIAL' | 'UNVERIFIED'
  error_code: string | null
  processed_at: string | null
  created_at: string
}

export type JobProviderCall = {
  provider: string
  model: string
  purpose: string
  success: boolean
  http_status: number | null
  latency_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  error_class: string | null
  provider_message: string | null
  created_at: string
}

export type JobReviewDecision = {
  question_id: string
  requested_reason: string
  mode: string
  outcome: string | null
  decided_by: string | null
  decided_at: string | null
  created_at: string
}

export type JobDetail = Job & {
  events: JobEvent[]
  submission: JobSubmissionContext | null
  assignment_name: string | null
  documents: JobDocumentContext[]
  provider_call: JobProviderCall | null
  review_decisions: JobReviewDecision[]
  review_reasons: string[]
}

export type BlueprintCriterion = {
  code: string
  marks: number
  description: string
  expected_answer: string | null
  award_when: string | null
  withhold_when: string | null
  source_page: number | null
  source_quote: string | null
}

export type BlueprintQuestion = {
  question_id: string
  label: string | null
  question_text: string | null
  max_marks: number
  answer_type: string | null
  excluded: boolean
  exclusion_reason: string | null
  subquestions: BlueprintQuestion[]
  special_instructions: string[]
  criteria_refs: string[]
  criteria: BlueprintCriterion[]
}

export type BlueprintStructure = {
  paper_code: string | null
  questions: BlueprintQuestion[]
  total_marks: number
  notes: string[]
}

export type Blueprint = {
  id: string
  exam_id: string
  version: number
  status: 'DRAFT' | 'APPROVED' | 'SUPERSEDED'
  structure: BlueprintStructure
  total_marks: number
  content_hash: string
  source: string
  extraction_metadata: Record<string, unknown>
  approved_at: string | null
  approval_reason: string | null
  created_at: string
}

export type SchemeVersion = {
  id: string
  mark_scheme_id: string
  version: number
  status: 'DRAFT' | 'APPROVED' | 'SUPERSEDED'
  source: string
  content_hash: string
  approved_at: string | null
  criteria_blueprint_version_id: string | null
  criteria_blueprint_hash: string | null
  criteria_approved_at: string | null
  criteria_approval_reason: string | null
  created_at: string
}

export type SchemeCriterion = {
  id: string
  question_id: string
  code: string
  marks: number
  ordinal: number
  description: string
  question_text: string | null
  expected_answer: string | null
  award_conditions: string | null
  withhold_conditions: string | null
  source_page: number | null
  source_quote: string | null
  blueprint_version_id: string | null
}

export type SchemeCriteriaExtraction = {
  version: SchemeVersion
  criteria: SchemeCriterion[]
  coverage: {
    complete: boolean
    questions: number
    total_expected: number
    total_criteria: number
    problems: string[]
  }
}

export type SchemeUpload = {
  scheme: { id: string; exam_id: string; title: string; created_at: string }
  version: SchemeVersion
}

export type DocumentPage = {
  id: string
  page_index: number
  width: number | null
  height: number | null
  quality_status: string
  quality_reasons: Record<string, unknown>[]
  ordering_reasons: Record<string, unknown>[]
  printed_page_number: number | null
  rotation_degrees: number
  duplicate_of_page_id: string | null
  text_excerpt: string | null
  checksum: string
}

export type DocumentMeta = {
  id: string
  submission_id: string | null
  exam_id: string | null
  kind: string
  original_filename: string
  mime_type: string
  size_bytes: number
  page_count: number
  status: string
  sha256: string
  validation_errors: Record<string, unknown>[]
  ordering_status: string
  ordering_reasons: Record<string, unknown>[]
  mapping_status: string
  mapping_reasons: Record<string, unknown>[]
  error_code: string | null
  created_at: string
  pages: DocumentPage[]
}

export type CriterionResult = {
  id: string
  code: string
  awarded: boolean
  reason: string | null
  evidence: Record<string, unknown>[]
}

export type Evidence = {
  id: string
  kind: string
  quote: string | null
  page_id: string | null
  bbox: Record<string, unknown> | null
}

export type QuestionResult = {
  id: string
  question_id: string
  max_marks: number
  awarded_marks: number
  status: 'AWARDED' | 'ZERO' | 'UNMARKED' | 'REVIEW_REQUIRED' | 'EXCLUDED'
  student_answer: string | null
  working_summary: string | null
  confidence: number | null
  review_required: boolean
  /** The engine's explicit claim. `null` only on rows written before the column. */
  processing_state: 'MARKED' | 'CONFIRMED_ZERO' | 'UNMARKED' | 'NEEDS_REVIEW' | null
  /** The model's own award, kept when normalisation or a teacher changed the stored one. */
  raw_awarded_marks: number | null
  normalised_awarded_marks: number | null
  normalisation_anomaly: string | null
  scheme_concerns: { code?: string; message?: string }[]
  criteria: CriterionResult[]
  evidence: Evidence[]
  /** Which required checks ran for this question, and how they ended. */
  verification: QuestionVerification | null
}

export type VerificationKind =
  | 'MATHEMATICAL'
  | 'INTEGRITY'
  | 'DOUBLE_CHECK'
  | 'TRANSCRIPTION'
  | 'SCHEME_MATHEMATICAL'
  | 'EVIDENCE'
  /** A kind this build does not know yet is still displayed, never relabelled. */
  | (string & {})

export type Verification = {
  question_id: string
  kind: VerificationKind
  status: string
  detail: Record<string, unknown>
}

/** The engine's derived verification state for one question. */
export type QuestionVerification = {
  question_id: string
  status:
    | 'FULLY_VERIFIED'
    | 'PARTIALLY_VERIFIED'
    | 'REVIEW_REQUIRED'
    | 'VERIFICATION_FAILED'
    | 'VERIFICATION_NOT_REQUIRED'
    | string
  required: string[]
  verified: string[]
  contradicted: string[]
  unverifiable: string[]
  missing: string[]
  not_applicable: string[]
  reasons: string[]
}

export type ReviewDecision = {
  question_id: string
  requested_reason: string
  outcome: string | null
  first_award: number | null
  second_award: number | null
  decided_by: string | null
  decided_at: string | null
}

export type JobResults = {
  job_id: string
  submission_id: string
  assignment_id: string
  student_ref: string
  job_state: JobState
  /**
   * Verification completeness, independent of `job_state`: a `COMPLETED` paper
   * is normally only `PARTIALLY_VERIFIED` because the expensive checks are
   * sampled.
   */
  verification_status: string | null
  /** `AUTOMATED_REFUSED` means this run is evidence, not the submission's result. */
  result_source: string | null
  /** A newer run was refused by the result guard and is deliberately not shown. */
  refused_newer_job_id: string | null
  questions: QuestionResult[]
  verifications: Verification[]
  reviews: ReviewDecision[]
  totals: {
    /** Awarded and available marks over decided questions only. */
    awarded: number
    total: number
    questions: number
    decided: number
    undecided: number
    scoreable: number
    complete: boolean
    unanswered: number
    review_required: number
    approved: boolean
    state: string
  }
  approved_at: string | null
  approved_by: string | null
  record_version: number
}

export type PageMeta = {
  page_index: number
  document_id: string
  quality_status: string
  width: number | null
  height: number | null
}

/* ── Correction preview ──────────────────────────────────────────────────
 * The three stored sources behind one correction. Every field is a record the
 * engine already holds; `null` means the record is absent and the preview says
 * so rather than filling it in.
 */

export type PreviewDocument = {
  id: string
  kind: string
  original_filename: string
  sha256: string
  size_bytes: number
  page_count: number
  ordering_status: string
  ordering_reasons: Record<string, unknown>[]
  mapping_status: string
  mapping_reasons: Record<string, unknown>[]
}

export type PreviewSchemeDocument = {
  document_id: string | null
  original_filename: string | null
  page_count: number
  content_hash_matches: boolean
  exam_document_filename: string | null
  exam_document_size_bytes: number | null
  note: string
}

export type PreviewCriterion = {
  code: string
  ordinal: number
  marks: number
  description: string
  expected_answer: string | null
  required_evidence: string | null
  award_conditions: string | null
  withhold_conditions: string | null
  dependencies: string[]
  alternatives: Record<string, unknown>[]
  source_page: number | null
  source_quote: string | null
}

export type PreviewDecision = {
  code: string
  scheme_ordinal: number | null
  scheme_marks: number | null
  awarded: boolean | null
  awarded_marks: number | null
  reason: string | null
  evidence: string[]
  component_description: string | null
  ambiguous: boolean
  note: string | null
}

export type PreviewVerification = {
  kind: string
  status: string
  detail: Record<string, unknown>
}

export type PreviewArchive = {
  provider_response_id: string
  content_sha256: string
  model: string | null
  finish_reason: string | null
  response_source: string
  created_at: string
}

export type PreviewLocation = {
  page_index: number
  confidence: number
  method: string
  quality_status: string
  width: number | null
  height: number | null
}

export type PreviewQuestion = {
  question_id: string
  label: string
  question_text: string | null
  special_instructions: string[]
  max_marks: number
  awarded_marks: number
  raw_awarded_marks: number | null
  status: string
  processing_state: string
  review_required: boolean
  student_answer: string | null
  working_summary: string | null
  confidence: number | null
  answer_check: string | null
  notes: string | null
  response_source: string | null
  response_sequence: number | null
  prompt_version: string | null
  scheme_criteria: PreviewCriterion[]
  criteria: PreviewDecision[]
  scheme_marks: number
  component_total: number | null
  component_consistent: boolean | null
  location: PreviewLocation | null
  mapping_note: string | null
  verifications: PreviewVerification[]
  review_reasons: string[]
  concerns: { code?: string; message?: string }[]
  archive: PreviewArchive | null
}

export type PreviewPaper = {
  exam_id: string
  exam_title: string
  board: string | null
  paper_code: string | null
  assignment_id: string
  assignment_name: string
  blueprint_version_id: string
  scheme_version_id: string
  blueprint_total_marks: number
  marking_mode: string | null
  engine_name: string | null
  engine_version: string | null
  primary_model: string | null
  secondary_model: string | null
  prompt_version: string | null
  job_state: JobState
  result_source: string | null
  guard_decision: string | null
  guard_reason: string | null
  questions_reviewed: number
  attention: number
  paper_awarded: number
  paper_total: number
  decided_awarded: number
  decided_total: number
  decided: number
  scoreable: number
  undecided: number
  review_required: number
  approved: boolean
  approved_at: string | null
  approved_by: string | null
}

export type PreviewStudent = {
  submission_id: string
  job_id: string
  student_ref: string
  awarded_marks: number
  total_marks: number
  review_required: number
  job_state: string
  result_source: string | null
  current: boolean
}

export type PreviewWarning = { code: string; message: string }

export type CorrectionPreview = {
  job_id: string
  submission_id: string
  student_ref: string
  paper: PreviewPaper
  student_document: PreviewDocument | null
  scheme_document: PreviewSchemeDocument
  students: PreviewStudent[]
  questions: PreviewQuestion[]
  warnings: PreviewWarning[]
}

export type Dashboard = {
  assignments: number
  submissions: number
  jobs_active: number
  awaiting_review: number
  failed_jobs: number
  approved_results: number
  recent_jobs: {
    id: string
    submission_id: string
    student_ref: string | null
    state: JobState
    progress: number
    error_code: string | null
    updated_at: string
  }[]
}

export type InboxItem = {
  id: string
  kind: 'REVIEW_REQUIRED' | 'JOB_FAILED'
  title: string
  detail: string
  created_at: string
  job_id: string
  submission_id: string | null
  read: boolean | null
}

export type ReportRow = {
  assignment_id: string
  name: string
  submissions: number
  jobs_completed: number
  awaiting_review: number
  failed: number
  approved: number
  total_marks: number
  mean_percent: number | null
  state: 'OK' | 'INSUFFICIENT_DATA'
}

export type GradebookCell = {
  assignment_id: string
  submission_id: string | null
  job_id: string | null
  job_state: JobState | null
  awarded: number | null
  total: number
  approved: boolean
  review_required: number
}

export type Gradebook = {
  assignments: {
    id: string
    name: string
    total_marks: number
    approved_jobs: number
    provisional_jobs: number
  }[]
  students: {
    student_ref: string
    cells: GradebookCell[]
    approved_awarded: number
    approved_possible: number
  }[]
  approved_jobs: number
  provisional_jobs: number
  mean_percent: number | null
  state: 'OK' | 'INSUFFICIENT_DATA'
}

export type AuditEvent = {
  id: string
  created_at: string
  action: string
  entity_type: string
  entity_id: string
  actor_type: string
  actor_id: string | null
  actor_label: string | null
  detail: Record<string, unknown>
}

export type Notification = {
  id: string
  kind:
    | 'REVIEW_REQUIRED'
    | 'JOB_FAILED'
    | 'RESULT_APPROVED'
    | 'INVITATION_PENDING'
  title: string
  detail: string
  created_at: string
  job_id: string | null
  submission_id: string | null
  invitation_id: string | null
  read: boolean | null
}

export type MarkingHistoryRow = {
  job_id: string
  submission_id: string
  assignment_id: string
  assignment_name: string | null
  student_ref: string | null
  state: JobState
  progress: number
  attempts: number
  max_attempts: number
  error_code: string | null
  error_message: string | null
  awarded: number
  total: number
  review_required: number
  approved: boolean
  approved_at: string | null
  approved_by_label: string | null
  updated_at: string
}

export type MarkingHistoryPage = {
  items: MarkingHistoryRow[]
  total: number
  limit: number
  offset: number
}

export type StudentImportIssue = {
  kind: 'SKIPPED' | 'ERROR'
  row: number
  student_ref: string | null
  message: string
}

export type StudentImportResult = {
  total_rows: number
  created: number
  skipped: number
  failed: number
  classes_created: number
  issues: StudentImportIssue[]
  created_refs: string[]
}
