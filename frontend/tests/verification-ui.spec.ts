import { expect, test } from './support/fixtures'
import type { Page, Route } from '@playwright/test'
import type {
  CorrectionPreview,
  Evidence,
  JobResults,
  PreviewQuestion,
  QuestionResult,
  QuestionVerification,
  ReviewDecision,
  Verification,
} from '../src/lib/api/types'

/**
 * The verification surface, inspected in a browser.
 *
 * Every response here is a fixture: the engine is intercepted, so this file can
 * state exactly what the API returned and can show a verdict the pipeline only
 * produces on a real paper. Nothing reaches a database or a provider.
 *
 * The screenshots are written to `.tmp/verification-ui` (git-ignored) and are
 * evidence for the audit, not part of the product.
 */

const TENANT_ID = '00000000-0000-4000-8000-000000000010'
const SUBMISSION_ID = '11111111-1111-4111-8111-111111111111'
const JOB_ID = '22222222-2222-4222-8222-222222222222'
const ASSIGNMENT_ID = '33333333-3333-4333-8333-333333333333'
const SHOTS = '../.tmp/verification-ui'

async function signIn(page: Page) {
  const now = Math.floor(Date.now() / 1000)
  const payload = {
    access_token: 'test-access-token',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: 4102444800,
    refresh_token: 'test-refresh-token',
    user: {
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      role: 'authenticated',
      email: 'owner@aetrix.test',
      email_confirmed_at: new Date(now * 1000).toISOString(),
      phone: '',
      confirmed_at: new Date(now * 1000).toISOString(),
      last_sign_in_at: new Date(now * 1000).toISOString(),
      app_metadata: { provider: 'google', aetrix_role: 'owner' },
      user_metadata: { full_name: 'Ana Ruiz', name: 'Ana Ruiz' },
      identities: [],
      created_at: new Date(now * 1000).toISOString(),
      updated_at: new Date(now * 1000).toISOString(),
    },
  }

  await page.addInitScript((value) => {
    window.localStorage.setItem('aetrix:auth', JSON.stringify(value))
  }, payload)
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

/** A 1×1 PNG, so the page viewer resolves instead of showing a broken image. */
const PAGE_PNG =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

function me() {
  return {
    user_id: '00000000-0000-4000-8000-000000000001',
    subject: 'ana-subject',
    email: 'ana@aetrix.test',
    display_name: 'Ana Ruiz',
    tenant_id: TENANT_ID,
    workspace_name: 'Alpha workspace',
    workspace_slug: 'alpha',
    role: 'OWNER',
    ui_role: 'supervisor',
    capabilities: ['read', 'review', 'approve'],
    is_demo: false,
  }
}

function evidence(id: string, quote: string, page = 1): Evidence {
  return {
    id,
    kind: 'QUOTE',
    quote,
    page_id: `page-${page}`,
    bbox: { x: 0.12, y: 0.34, width: 0.42, height: 0.03 },
  }
}

function criterion(id: string, code: string, awarded: boolean, reason: string) {
  return { id, code, awarded, reason, evidence: [] }
}

function verification(
  questionId: string,
  kind: string,
  status: string,
  detail: Record<string, unknown> = {},
): Verification {
  return { question_id: questionId, kind, status, detail }
}

function summary(
  questionId: string,
  status: string,
  fields: Partial<QuestionVerification> = {},
): QuestionVerification {
  return {
    question_id: questionId,
    status,
    required: ['INTEGRITY', 'MATHEMATICAL', 'EVIDENCE'],
    verified: [],
    contradicted: [],
    unverifiable: [],
    missing: [],
    not_applicable: [],
    reasons: [],
    ...fields,
  }
}

function question(
  id: string,
  overrides: Partial<QuestionResult> & { question_id: string },
): QuestionResult {
  return {
    id,
    question_id: overrides.question_id,
    max_marks: 4,
    awarded_marks: 3,
    status: 'AWARDED',
    student_answer: 'x = 4, by completing the square.',
    working_summary: 'Completed the square and solved for x.',
    confidence: 0.93,
    review_required: false,
    processing_state: 'MARKED',
    raw_awarded_marks: null,
    normalised_awarded_marks: null,
    normalisation_anomaly: null,
    scheme_concerns: [],
    criteria: [],
    evidence: [],
    verification: null,
    ...overrides,
  }
}

/** Every supported kind, and every verdict the engine can record. */
function paperQuestions(): QuestionResult[] {
  return [
    question('qr-1a', {
      question_id: '1a',
      awarded_marks: 2,
      max_marks: 2,
      student_answer: 'x = 4',
      confidence: 0.97,
      criteria: [criterion('c-1a', 'M1', true, 'Correct completing the square.')],
      evidence: [evidence('ev-1a', 'x = 4')],
      verification: summary('1a', 'FULLY_VERIFIED', {
        required: ['INTEGRITY', 'MATHEMATICAL', 'EVIDENCE', 'TRANSCRIPTION', 'DOUBLE_CHECK'],
        verified: ['INTEGRITY', 'MATHEMATICAL', 'EVIDENCE', 'TRANSCRIPTION', 'DOUBLE_CHECK'],
      }),
    }),
    question('qr-1b', {
      question_id: '1b',
      awarded_marks: 3,
      max_marks: 4,
      student_answer: 'x = 4 or x = -1',
      verification: summary('1b', 'PARTIALLY_VERIFIED', {
        required: ['INTEGRITY', 'SCHEME_MATHEMATICAL', 'EVIDENCE'],
        verified: ['INTEGRITY', 'SCHEME_MATHEMATICAL'],
        missing: ['EVIDENCE'],
        reasons: ['No independent reading of this question was bought.'],
      }),
    }),
    question('qr-2a', {
      question_id: '2a',
      awarded_marks: 4,
      max_marks: 5,
      student_answer: 'The gradient is 3, so y = 3x + 2.',
      review_required: true,
      processing_state: 'NEEDS_REVIEW',
      verification: summary('2a', 'VERIFICATION_FAILED', {
        required: ['INTEGRITY', 'MATHEMATICAL', 'EVIDENCE'],
        verified: ['INTEGRITY', 'MATHEMATICAL'],
        contradicted: ['EVIDENCE'],
        reasons: ['A quotation the award rests on was not found in the script.'],
      }),
      evidence: [
        evidence('ev-2a-1', 'y = 3x + 2'),
        evidence('ev-2a-2', 'gradient = 5', 2),
      ],
    }),
    question('qr-2b', {
      question_id: '2b',
      awarded_marks: 1,
      max_marks: 3,
      student_answer: 'It increases by 2 each time.',
      review_required: true,
      processing_state: 'NEEDS_REVIEW',
      verification: summary('2b', 'REVIEW_REQUIRED', {
        required: ['INTEGRITY', 'EVIDENCE', 'TRANSCRIPTION'],
        verified: ['INTEGRITY'],
        contradicted: ['TRANSCRIPTION'],
        reasons: ['The independent reading of the page differs from the marking pass.'],
      }),
    }),
    question('qr-3a', {
      question_id: '3a',
      awarded_marks: 2,
      max_marks: 4,
      student_answer: 'x = 5',
      verification: summary('3a', 'VERIFICATION_FAILED', {
        required: ['INTEGRITY', 'MATHEMATICAL'],
        verified: ['INTEGRITY'],
        contradicted: ['MATHEMATICAL'],
        reasons: ['The final answer differs from the expected expression.'],
      }),
    }),
    question('qr-3b', {
      question_id: '3b',
      awarded_marks: 2,
      max_marks: 6,
      student_answer: 'Area = 24 cm²',
      review_required: true,
      processing_state: 'NEEDS_REVIEW',
      verification: summary('3b', 'REVIEW_REQUIRED', {
        required: ['INTEGRITY', 'EVIDENCE', 'DOUBLE_CHECK'],
        verified: ['INTEGRITY', 'EVIDENCE'],
        contradicted: ['DOUBLE_CHECK'],
        reasons: ['The second examiner disagreed with the first award.'],
      }),
    }),
    question('qr-4a', {
      question_id: '4a',
      awarded_marks: 1,
      max_marks: 2,
      student_answer: 'Mean = 7',
      verification: summary('4a', 'PARTIALLY_VERIFIED', {
        required: ['INTEGRITY', 'MATHEMATICAL', 'EVIDENCE', 'TRANSCRIPTION'],
        verified: ['INTEGRITY'],
        missing: ['EVIDENCE', 'TRANSCRIPTION'],
        reasons: ['No evidence check or independent reading was bought.'],
      }),
    }),
    question('qr-4b', {
      question_id: '4b',
      awarded_marks: 3,
      max_marks: 3,
      student_answer: 'n = 12',
      verification: summary('4b', 'PARTIALLY_VERIFIED', {
        required: ['INTEGRITY', 'EVIDENCE'],
        verified: ['INTEGRITY'],
        unverifiable: ['EVIDENCE'],
        reasons: ['The stored quotation is too short to be distinctive.'],
      }),
    }),
    question('qr-5a', {
      question_id: '5a',
      awarded_marks: 2,
      max_marks: 2,
      student_answer: 'k = 9',
      verification: summary('5a', 'PARTIALLY_VERIFIED', {
        required: ['INTEGRITY', 'EVIDENCE'],
        verified: ['INTEGRITY'],
        missing: ['EVIDENCE'],
      }),
    }),
    question('qr-5b', {
      question_id: '5b',
      awarded_marks: 0,
      max_marks: 3,
      student_answer: null,
      confidence: 0.88,
      verification: summary('5b', 'PARTIALLY_VERIFIED', {
        required: ['INTEGRITY', 'EVIDENCE'],
        verified: ['INTEGRITY'],
        missing: ['EVIDENCE'],
      }),
    }),
    question('qr-6a', {
      question_id: '6a',
      awarded_marks: 2,
      max_marks: 4,
      student_answer: 't = 6',
      verification: summary('6a', 'PARTIALLY_VERIFIED', {
        required: ['INTEGRITY', 'EVIDENCE'],
        verified: ['INTEGRITY', 'EVIDENCE'],
      }),
    }),
    question('qr-6b', {
      question_id: '6b',
      awarded_marks: 2,
      max_marks: 4,
      student_answer: 'y = 2x - 1',
      verification: summary('6b', 'PARTIALLY_VERIFIED', {
        required: ['INTEGRITY', 'MATHEMATICAL'],
        verified: ['INTEGRITY'],
        unverifiable: ['MATHEMATICAL'],
      }),
    }),
    question('qr-7a', {
      question_id: '7a',
      awarded_marks: 0,
      max_marks: 2,
      status: 'ZERO',
      processing_state: 'CONFIRMED_ZERO',
      student_answer: null,
      confidence: 0.99,
      verification: summary('7a', 'VERIFICATION_NOT_REQUIRED', {
        required: [],
        not_applicable: ['INTEGRITY', 'MATHEMATICAL', 'EVIDENCE'],
      }),
    }),
    question('qr-7b', {
      question_id: '7b',
      awarded_marks: 1,
      max_marks: 2,
      student_answer: 'p = 4',
      verification: null,
    }),
  ]
}

function paperVerifications(): Verification[] {
  return [
    verification('1a', 'INTEGRITY', 'PASS', {
      component_total: 2,
      awarded_marks: 2,
      max_marks: 2,
    }),
    verification('1a', 'MATHEMATICAL', 'EQUIVALENT', {
      student_expression: 'x = 4',
      expected_expression: 'x = 4',
    }),
    verification('1a', 'EVIDENCE', 'PASS', {
      quotes_checked: 1,
      quotes_found: 1,
      missing_quotes: [],
    }),
    verification('1a', 'TRANSCRIPTION', 'AGREES', { page_index: 1 }),
    verification('1a', 'DOUBLE_CHECK', 'AGREES', {
      first_awarded: 2,
      second_awarded: 2,
      max_marks: 2,
    }),
    verification('1b', 'INTEGRITY', 'PASS', { component_total: 3, awarded_marks: 3 }),
    verification('1b', 'SCHEME_MATHEMATICAL', 'EQUIVALENT', {
      student_expression: 'x = 4 or x = -1',
      expected_expression: 'x = 4, x = -1',
    }),
    verification('2a', 'EVIDENCE', 'FAIL', {
      quotes_checked: 2,
      quotes_found: 1,
      missing_quotes: ['gradient = 5'],
    }),
    verification('2a', 'INTEGRITY', 'PASS', { component_total: 4, awarded_marks: 4 }),
    verification('2b', 'TRANSCRIPTION', 'DIFFERS', {
      marking_answer: 'It increases by 2 each time.',
      independent_answer: 'It doubles each time.',
      page_index: 2,
    }),
    verification('3a', 'MATHEMATICAL', 'DIFFERENT', {
      student_expression: 'x = 5',
      expected_expression: 'x = 3',
    }),
    verification('3b', 'DOUBLE_CHECK', 'DISAGREES', {
      first_awarded: 2,
      second_awarded: 4,
      max_marks: 6,
    }),
    verification('4b', 'EVIDENCE', 'UNVERIFIABLE', { quotes_checked: 1, quotes_found: 0 }),
    verification('5a', 'PROVENANCE', 'VERIFIED', {
      source: 'a check this build does not know',
    }),
    verification('5b', 'MATHEMATICAL_V2', 'CONTRADICTED', {
      student_expression: '0',
      expected_expression: '3',
    }),
    verification('6a', 'EVIDENCE', 'SKIPPED', { reason: 'No reading was bought.' }),
    verification('6b', 'MATHEMATICAL', 'UNKNOWN', { reason: 'Unparseable expression.' }),
    verification('7a', 'INTEGRITY', 'PASS', { component_total: 0, awarded_marks: 0 }),
  ]
}

function reviewDecisions(): ReviewDecision[] {
  return [
    {
      question_id: '2a',
      requested_reason: 'A quotation the award rests on was not found in the script.',
      outcome: null,
      first_award: 4,
      second_award: null,
      decided_by: null,
      decided_at: null,
    },
    {
      question_id: '2b',
      requested_reason: 'The independent reading differs from the marking pass.',
      outcome: null,
      first_award: 1,
      second_award: null,
      decided_by: null,
      decided_at: null,
    },
    {
      question_id: '3b',
      requested_reason: 'The second examiner awarded 4 of 6; the first awarded 2.',
      outcome: null,
      first_award: 2,
      second_award: 4,
      decided_by: null,
      decided_at: null,
    },
  ]
}

function results(overrides: Partial<JobResults> = {}): JobResults {
  const questions = overrides.questions ?? paperQuestions()
  const decided = questions.filter(
    (item) => item.processing_state === 'MARKED' || item.processing_state === 'CONFIRMED_ZERO',
  ).length
  return {
    job_id: JOB_ID,
    submission_id: SUBMISSION_ID,
    assignment_id: ASSIGNMENT_ID,
    student_ref: 'student-1',
    job_state: 'COMPLETED',
    verification_status: 'PARTIALLY_VERIFIED',
    result_source: 'ENGINE',
    refused_newer_job_id: null,
    questions,
    verifications: overrides.verifications ?? paperVerifications(),
    reviews: overrides.reviews ?? reviewDecisions(),
    totals: {
      awarded: 24,
      total: 43,
      questions: questions.length,
      decided,
      undecided: questions.length - decided,
      scoreable: questions.length,
      complete: decided === questions.length,
      unanswered: 1,
      review_required: 3,
      approved: false,
      state: 'PROVISIONAL',
    },
    approved_at: null,
    approved_by: null,
    record_version: 7,
    ...overrides,
  }
}

function previewQuestion(
  overrides: Partial<PreviewQuestion> & { question_id: string },
): PreviewQuestion {
  return {
    question_id: overrides.question_id,
    label: `Question ${overrides.question_id}`,
    question_text: 'Solve the equation.',
    special_instructions: [],
    max_marks: 4,
    awarded_marks: 3,
    raw_awarded_marks: null,
    status: 'AWARDED',
    processing_state: 'MARKED',
    review_required: false,
    student_answer: 'x = 4',
    working_summary: null,
    confidence: 0.93,
    answer_check: null,
    notes: null,
    response_source: 'WHOLE_PAPER',
    response_sequence: 0,
    prompt_version: 'aetrix_v5_5_marking:v4',
    scheme_criteria: [],
    criteria: [
      {
        code: 'M1',
        scheme_ordinal: 1,
        scheme_marks: 2,
        awarded: true,
        awarded_marks: 2,
        reason: 'Correct method.',
        evidence: ['x = 4 by completing the square'],
        component_description: 'Method mark',
        ambiguous: false,
        note: null,
      },
    ],
    scheme_marks: 4,
    component_total: 3,
    component_consistent: true,
    location: null,
    mapping_note: null,
    verifications: [
      { kind: 'EVIDENCE', status: 'PASS', detail: { quotes_checked: 1, quotes_found: 1 } },
      { kind: 'PROVENANCE', status: 'VERIFIED', detail: { source: 'unknown build' } },
    ],
    review_reasons: [],
    concerns: [],
    archive: null,
    ...overrides,
  }
}

function preview(): CorrectionPreview {
  return {
    job_id: JOB_ID,
    submission_id: SUBMISSION_ID,
    student_ref: 'student-1',
    paper: {
      exam_id: '44444444-4444-4444-8444-444444444444',
      exam_title: 'GCSE Mathematics Paper 1',
      board: 'AQA',
      paper_code: '8300/1H',
      assignment_id: ASSIGNMENT_ID,
      assignment_name: 'Autumn mock',
      blueprint_version_id: '55555555-5555-4555-8555-555555555555',
      scheme_version_id: '66666666-6666-4666-8666-666666666666',
      blueprint_total_marks: 43,
      marking_mode: 'WHOLE_PAPER',
      engine_name: 'aetrix_v5_5',
      engine_version: '5.5.0',
      primary_model: 'gemini-3.1-flash-lite',
      secondary_model: null,
      prompt_version: 'aetrix_v5_5_marking:v4',
      job_state: 'COMPLETED',
      result_source: 'ENGINE',
      guard_decision: null,
      guard_reason: null,
      questions_reviewed: 14,
      attention: 3,
      paper_awarded: 24,
      paper_total: 43,
      decided_awarded: 24,
      decided_total: 43,
      decided: 14,
      scoreable: 14,
      undecided: 0,
      review_required: 3,
      approved: false,
      approved_at: null,
      approved_by: null,
    },
    student_document: {
      id: '77777777-7777-4777-8777-777777777777',
      kind: 'STUDENT',
      original_filename: 'student-1.pdf',
      sha256: 'a'.repeat(64),
      size_bytes: 120_000,
      page_count: 2,
      ordering_status: 'ORDERED',
      ordering_reasons: [],
      mapping_status: 'MAPPED',
      mapping_reasons: [],
    },
    scheme_document: {
      document_id: null,
      original_filename: null,
      page_count: 0,
      content_hash_matches: false,
      exam_document_filename: null,
      exam_document_size_bytes: null,
      note: 'No scheme document is stored for this version.',
    },
    students: [
      {
        submission_id: SUBMISSION_ID,
        job_id: JOB_ID,
        student_ref: 'student-1',
        awarded_marks: 24,
        total_marks: 43,
        review_required: 3,
        job_state: 'COMPLETED',
        result_source: 'ENGINE',
        current: true,
      },
    ],
    questions: [
      previewQuestion({ question_id: '1a' }),
      previewQuestion({
        question_id: '2a',
        awarded_marks: 4,
        max_marks: 5,
        review_required: true,
        processing_state: 'NEEDS_REVIEW',
        status: 'REVIEW_REQUIRED',
        verifications: [
          {
            kind: 'EVIDENCE',
            status: 'FAIL',
            detail: { quotes_checked: 2, quotes_found: 1, missing_quotes: ['gradient = 5'] },
          },
          {
            kind: 'TRANSCRIPTION',
            status: 'DIFFERS',
            detail: { page_index: 2 },
          },
          {
            kind: 'DOUBLE_CHECK',
            status: 'DISAGREES',
            detail: { first_awarded: 4, second_awarded: 2, max_marks: 5 },
          },
          {
            kind: 'PROVENANCE',
            status: 'VERIFIED',
            detail: { source: 'unknown build' },
          },
        ],
        review_reasons: ['A quotation the award rests on was not found in the script.'],
      }),
    ],
    warnings: [],
  }
}

type OpenOptions = {
  jobState?: string
  verificationStatus?: string | null
  payload?: JobResults
}

async function openReview(page: Page, options: OpenOptions = {}) {
  const body = options.payload ?? results()
  if (options.jobState) body.job_state = options.jobState
  if (options.verificationStatus !== undefined) {
    body.verification_status = options.verificationStatus
  }

  await signIn(page)
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path === '/api/v1/me') return json(route, me())
    if (path === `/api/v1/submissions/${SUBMISSION_ID}`) {
      return json(route, {
        id: SUBMISSION_ID,
        assignment_id: ASSIGNMENT_ID,
        student_ref: 'student-1',
        status: 'REGISTERED',
        content_hash: 'a'.repeat(64),
        created_at: '2026-11-10T09:00:00Z',
      })
    }
    if (path === `/api/v1/submissions/${SUBMISSION_ID}/results`) return json(route, body)
    if (path === `/api/v1/submissions/${SUBMISSION_ID}/pages`) {
      return json(route, [
        {
          page_index: 1,
          document_id: '77777777-7777-4777-8777-777777777777',
          quality_status: 'READABLE',
          width: 1240,
          height: 1754,
        },
        {
          page_index: 2,
          document_id: '77777777-7777-4777-8777-777777777777',
          quality_status: 'READABLE',
          width: 1240,
          height: 1754,
        },
      ])
    }
    if (path.startsWith(`/api/v1/submissions/${SUBMISSION_ID}/pages/`)) {
      return route.fulfill({
        status: 200,
        contentType: 'image/png',
        body: Buffer.from(PAGE_PNG, 'base64'),
      })
    }
    return json(route, { error: { code: 'NOT_FOUND', message: 'No mock route.' } }, 404)
  })

  const response = await page.goto(`/submissions/${SUBMISSION_ID}`, { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('region', { name: 'Result summary' })).toBeVisible({
    timeout: 30_000,
  })
  return body
}

async function openPreview(page: Page) {
  await signIn(page)
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/me') return json(route, me())
    if (path === `/api/v1/submissions/${SUBMISSION_ID}/preview`) return json(route, preview())
    if (path.startsWith(`/api/v1/submissions/${SUBMISSION_ID}/pages/`)) {
      return route.fulfill({
        status: 200,
        contentType: 'image/png',
        body: Buffer.from(PAGE_PNG, 'base64'),
      })
    }
    if (path.startsWith('/api/v1/documents/') && path.includes('/pages/')) {
      return route.fulfill({
        status: 200,
        contentType: 'image/png',
        body: Buffer.from(PAGE_PNG, 'base64'),
      })
    }
    return json(route, { error: { code: 'NOT_FOUND', message: 'No mock route.' } }, 404)
  })

  const response = await page.goto(`/preview/${SUBMISSION_ID}`, { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  // The record's own heading is the student, not the route's eyebrow.
  await expect(page.getByRole('heading', { name: 'student-1', level: 1 })).toBeVisible({
    timeout: 30_000,
  })
}

function questionRow(page: Page, questionId: string) {
  return page.getByRole('article', { name: `Question ${questionId}` })
}

test.describe('verification UI', () => {
  test('a completed and fully verified paper says both facts', async ({ page }) => {
    const questions = [paperQuestions()[0]]
    await openReview(page, {
      payload: results({
        questions,
        verifications: paperVerifications().filter((item) => item.question_id === '1a'),
        reviews: [],
        verification_status: 'FULLY_VERIFIED',
        totals: {
          awarded: 2,
          total: 2,
          questions: 1,
          decided: 1,
          undecided: 0,
          scoreable: 1,
          complete: true,
          unanswered: 0,
          review_required: 0,
          approved: false,
          state: 'PROVISIONAL',
        },
      }),
    })

    const hero = page.locator('.rd-hero__sub')
    await expect(hero).toContainText('COMPLETED')
    await expect(hero).toContainText('Fully verified')

    const row = questionRow(page, '1a')
    await expect(row.getByText('Fully verified', { exact: true })).toBeVisible()
    await expect(row.getByText('Integrity · PASS', { exact: true })).toBeVisible()
    await expect(row.getByText('Mathematics · EQUIVALENT', { exact: true })).toBeVisible()
    await expect(row.getByText('Evidence in script · PASS', { exact: true })).toBeVisible()
    await expect(row.getByText('Independent reading · AGREES', { exact: true })).toBeVisible()
    await expect(row.getByText('Second examiner · AGREES', { exact: true })).toBeVisible()

    await page.locator('.rd-hero').screenshot({ path: `${SHOTS}/01-hero-fully-verified.png` })
    await page.screenshot({ path: `${SHOTS}/01-page-fully-verified.png` })
  })

  test('every verification kind and verdict renders as itself', async ({ page }) => {
    await openReview(page)

    await expect(page.locator('.rd-hero__sub')).toContainText('Partially verified')

    const expectations: Array<[string, string]> = [
      ['1a', 'Mathematics · EQUIVALENT'],
      ['1a', 'Integrity · PASS'],
      ['1a', 'Independent reading · AGREES'],
      ['1a', 'Second examiner · AGREES'],
      ['1b', 'Scheme mathematics · EQUIVALENT'],
      ['2a', 'Evidence in script · FAIL'],
      ['2b', 'Independent reading · DIFFERS'],
      ['3a', 'Mathematics · DIFFERENT'],
      ['3b', 'Second examiner · DISAGREES'],
      ['4b', 'Evidence in script · UNVERIFIABLE'],
      ['6a', 'Evidence in script · SKIPPED'],
      ['6b', 'Mathematics · UNKNOWN'],
    ]

    for (const [questionId, label] of expectations) {
      await expect(questionRow(page, questionId).getByText(label, { exact: true })).toBeVisible()
    }

    await page.screenshot({ path: `${SHOTS}/02-page-all-kinds.png` })
    await questionRow(page, '1a').screenshot({ path: `${SHOTS}/02-row-full.png` })
    await questionRow(page, '2a').scrollIntoViewIfNeeded()
    await page.screenshot({ path: `${SHOTS}/02-page-failure.png` })
  })

  test('an unknown verification kind is shown by name and never as success', async ({ page }) => {
    await openReview(page)

    const unknown = questionRow(page, '5a').getByText(
      'Unrecognised check (PROVENANCE) · VERIFIED',
      { exact: true },
    )
    await expect(unknown).toBeVisible()
    await expect(unknown).toHaveAttribute('data-tone', 'neutral')
    await expect(
      questionRow(page, '5b').getByText('Unrecognised check (MATHEMATICAL_V2) · CONTRADICTED', {
        exact: true,
      }),
    ).toBeVisible()

    await questionRow(page, '5a').scrollIntoViewIfNeeded()
    await questionRow(page, '5a').screenshot({ path: `${SHOTS}/03-unknown-kind.png` })
  })

  test('a completed paper needing review is not presented as verified', async ({ page }) => {
    await openReview(page, {
      verificationStatus: 'REVIEW_REQUIRED',
      payload: results({ totals: { ...results().totals, review_required: 3 } }),
    })

    const hero = page.locator('.rd-hero__sub')
    await expect(hero).toContainText('COMPLETED')
    await expect(hero).toContainText('Verification needs review')
    await expect(page.getByRole('button', { name: 'Approve results' })).toBeDisabled()

    await page.locator('.rd-hero').screenshot({ path: `${SHOTS}/04-hero-review-required.png` })
  })

  test('a completed paper with a failed verification is labelled as failed', async ({ page }) => {
    await openReview(page, { verificationStatus: 'VERIFICATION_FAILED' })

    const hero = page.locator('.rd-hero__sub')
    await expect(hero).toContainText('COMPLETED')
    await expect(hero).toContainText('Verification failed')

    await page.locator('.rd-hero').screenshot({ path: `${SHOTS}/05-hero-verification-failed.png` })
  })

  test('a completed paper with no independent check says so', async ({ page }) => {
    await openReview(page, { verificationStatus: 'VERIFICATION_NOT_REQUIRED' })

    const hero = page.locator('.rd-hero__sub')
    await expect(hero).toContainText('COMPLETED')
    await expect(hero).toContainText('No independent check required')

    await page.locator('.rd-hero').screenshot({ path: `${SHOTS}/06-hero-not-required.png` })
  })

  test('a missing required check is explained, not shown as a pass', async ({ page }) => {
    await openReview(page)

    const row = questionRow(page, '1b')
    await expect(row.getByText('Partially verified', { exact: true })).toBeVisible()
    await expect(row.getByText('No independent reading of this question was bought.')).toBeVisible()
    await expect(row.getByText('Missing required: Evidence in script')).toBeVisible()

    await row.scrollIntoViewIfNeeded()
    await row.screenshot({ path: `${SHOTS}/07-missing-required-check.png` })
  })

  test('a question shows the evidence and reason behind its checks', async ({ page }) => {
    await openReview(page)

    const row = questionRow(page, '2a')
    await expect(row.getByText('“gradient = 5”')).toBeVisible()
    await expect(row.getByText('“y = 3x + 2”')).toBeVisible()
    await expect(
      row
        .locator('.rd-row__review')
        .getByText('A quotation the award rests on was not found in the script.'),
    ).toBeVisible()

    await row.scrollIntoViewIfNeeded()
    await row.screenshot({ path: `${SHOTS}/08-evidence-and-reason.png` })
  })

  test('the paper-level verification status carries its severity', async ({ page }) => {
    await openReview(page, { verificationStatus: 'VERIFICATION_FAILED' })

    const jobState = page.locator('[data-job-state]')
    await expect(jobState).toHaveText('COMPLETED')
    await expect(jobState).toHaveAttribute('data-tone', 'neutral')

    const status = page.locator('[data-verification-status]')
    await expect(status).toBeVisible()
    await expect(status).toContainText('Verification failed')
    await expect(status).toHaveAttribute('data-tone', 'attention')
  })

  test('a narrow screen keeps the verification records readable', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openReview(page)

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)

    await page.screenshot({ path: `${SHOTS}/09-narrow-top.png` })
    await questionRow(page, '2a').scrollIntoViewIfNeeded()
    await page.screenshot({ path: `${SHOTS}/09-narrow-question.png` })
  })

  test('an unavailable engine withholds verification instead of implying a pass', async ({ page }) => {
    await signIn(page)
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/v1/me') return json(route, me())
      if (path === `/api/v1/submissions/${SUBMISSION_ID}/results`) {
        return json(
          route,
          { error: { code: 'ENGINE_UNAVAILABLE', message: 'The correction engine is offline.' } },
          503,
        )
      }
      if (path.startsWith(`/api/v1/submissions/${SUBMISSION_ID}/pages`)) {
        return json(route, [])
      }
      return json(route, { error: { code: 'NOT_FOUND', message: 'No mock route.' } }, 404)
    })

    const response = await page.goto(`/submissions/${SUBMISSION_ID}`, { waitUntil: 'load' })
    expect(response?.status()).toBe(200)

    await expect(page.getByText('The correction engine is offline.')).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.locator('[data-verification-status]')).toHaveCount(0)
    await expect(page.locator('.rd-hero__sub')).not.toContainText('Fully verified')

    await page.screenshot({ path: `${SHOTS}/11-unavailable.png` })
  })

  test('the correction preview labels each stored verification record', async ({ page }) => {
    await openPreview(page)

    // A question that needs review is selected first, so open the verified one.
    await page.locator('.cp-index__item').filter({ hasText: '1a' }).click()
    await expect(page.getByText('EVIDENCE · PASS', { exact: true })).toBeVisible()
    await expect(page.getByText('PROVENANCE · VERIFIED', { exact: true })).toBeVisible()

    await page.locator('.cp-index__item').filter({ hasText: '2a' }).click()
    // The preview spells a kind the way the stored record reads it.
    await expect(page.getByText('DOUBLE CHECK · DISAGREES', { exact: true })).toBeVisible()
    await expect(page.getByText('TRANSCRIPTION · DIFFERS', { exact: true })).toBeVisible()

    await page.screenshot({ path: `${SHOTS}/10-preview-verifications.png` })
  })
})
