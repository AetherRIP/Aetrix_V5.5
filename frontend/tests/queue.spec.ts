import { expect, test } from './support/fixtures'
import type { Page, Route } from '@playwright/test'

/**
 * Correction-job actions.
 *
 * The reported defect: Detail, Cancel and Retry looked present but did nothing.
 * Cancel and Retry were disabled by the screen's own terminal-state list, and
 * Detail rendered a sparse panel below the table.  The engine is intercepted
 * here so each test states exactly what the API returned and can prove that a
 * request was or was not sent.
 */

const TENANT_ID = '00000000-0000-4000-8000-000000000010'
const REVIEW_ID = 'c936dedf-1111-4111-8111-111111111111'
const FAILED_ID = '6fca5be5-2222-4222-8222-222222222222'
const REVIEW_SUBMISSION = '47690c8e-3333-4333-8333-333333333333'
const FAILED_SUBMISSION = '1089248c-4444-4444-8444-444444444444'
const ASSIGNMENT_ID = '55555555-5555-4555-8555-555555555555'

const CREATED = '2026-11-10T09:00:00Z'
const UPDATED = '2026-11-10T09:15:00Z'

type MockJob = {
  id: string
  assignment_id: string
  submission_id: string
  blueprint_version_id: string
  scheme_version_id: string
  state: string
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
}

function makeJobs(): { review: MockJob; failed: MockJob } {
  return {
    review: {
      id: REVIEW_ID,
      assignment_id: ASSIGNMENT_ID,
      submission_id: REVIEW_SUBMISSION,
      blueprint_version_id: '66666666-6666-4666-8666-666666666666',
      scheme_version_id: '77777777-7777-4777-8777-777777777777',
      state: 'REVIEW_REQUIRED',
      progress: 0.95,
      attempts: 1,
      max_attempts: 3,
      cancel_requested: false,
      error_code: null,
      error_message: null,
      retryable: null,
      resume_state: null,
      created_at: CREATED,
      updated_at: UPDATED,
      started_at: CREATED,
      finished_at: null,
      record_version: 4,
    },
    failed: {
      id: FAILED_ID,
      assignment_id: ASSIGNMENT_ID,
      submission_id: FAILED_SUBMISSION,
      blueprint_version_id: '88888888-8888-4888-8888-888888888888',
      scheme_version_id: '99999999-9999-4999-8999-999999999999',
      state: 'FAILED',
      progress: 1,
      attempts: 2,
      max_attempts: 3,
      cancel_requested: false,
      error_code: 'PIPELINE_UNAVAILABLE',
      error_message: 'The correction pipeline is not implemented.',
      retryable: true,
      resume_state: null,
      created_at: CREATED,
      updated_at: UPDATED,
      started_at: CREATED,
      finished_at: UPDATED,
      record_version: 5,
    },
  }
}

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

function detailFor(job: MockJob) {
  const isReview = job.id === REVIEW_ID
  return {
    ...job,
    events: [
      {
        id: `${job.id}-event-1`,
        event_seq: 1,
        from_state: null,
        to_state: 'CREATED',
        detail: {},
        actor: 'user:owner',
        created_at: CREATED,
      },
      {
        id: `${job.id}-event-2`,
        event_seq: 2,
        from_state: 'VALIDATING',
        to_state: job.state,
        detail: isReview
          ? { review_reasons: ['Question 1a: the model response was not usable.'] }
          : { code: 'PIPELINE_UNAVAILABLE', retryable: true },
        actor: 'system',
        created_at: UPDATED,
      },
    ],
    submission: {
      id: job.submission_id,
      assignment_id: ASSIGNMENT_ID,
      student_ref: isReview ? 'student-1' : 'student-2',
      status: 'REGISTERED',
      content_hash: (isReview ? 'a' : 'b').repeat(64),
      created_at: CREATED,
    },
    assignment_name: 'Fixture assignment',
    documents: isReview
      ? [
          {
            id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            kind: 'STUDENT',
            original_filename: 'student-1.pdf',
            sha256: 'c'.repeat(64),
            mime_type: 'application/pdf',
            size_bytes: 12000,
            page_count: 2,
            status: 'PROCESSED',
            ordering_status: 'ORDERED',
            mapping_status: 'MAPPED',
            error_code: null,
            processed_at: UPDATED,
            created_at: CREATED,
          },
        ]
      : [],
    provider_call: isReview
      ? {
          provider: 'google',
          model: 'gemini-2.5-pro',
          purpose: 'MARKING',
          success: true,
          http_status: 200,
          latency_ms: 1840,
          input_tokens: 1200,
          output_tokens: 220,
          error_class: null,
          provider_message: null,
          created_at: UPDATED,
        }
      : null,
    review_decisions: isReview
      ? [
          {
            question_id: '1a',
            requested_reason: 'The model response was not usable.',
            mode: 'BALANCED',
            outcome: null,
            decided_by: null,
            decided_at: null,
            created_at: UPDATED,
          },
        ]
      : [],
    review_reasons: isReview
      ? ['Question 1a: the model response was not usable.']
      : [],
  }
}

async function openQueue(page: Page, options: { failCancel?: boolean } = {}) {
  const calls = { cancel: 0, retry: 0 }
  const jobs = makeJobs()

  await signIn(page)
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()

    if (path === '/api/v1/me') {
      return json(route, {
        user_id: '00000000-0000-4000-8000-000000000001',
        subject: 'ana-subject',
        email: 'ana@aetrix.test',
        display_name: 'Ana Ruiz',
        tenant_id: TENANT_ID,
        workspace_name: 'Alpha workspace',
        workspace_slug: 'alpha',
        role: 'OWNER',
        ui_role: 'supervisor',
        capabilities: ['read', 'manage_exams', 'review', 'approve'],
        is_demo: false,
      })
    }

    if (path === `/api/v1/workspaces/${TENANT_ID}/corrections` && method === 'GET') {
      return json(route, [jobs.review, jobs.failed])
    }

    const action = path.match(/\/api\/v1\/corrections\/([^/]+)\/(cancel|retry)$/)
    if (action && method === 'POST') {
      const id = action[1]
      const kind = action[2] as 'cancel' | 'retry'
      const job = id === REVIEW_ID ? jobs.review : id === FAILED_ID ? jobs.failed : null
      if (!job) return json(route, { error: { code: 'NOT_FOUND', message: 'Job not found.' } }, 404)

      if (kind === 'cancel') {
        calls.cancel += 1
        if (options.failCancel) {
          return json(
            route,
            {
              error: {
                code: 'JOB_NOT_CANCELLABLE',
                message: 'The job changed state before cancellation.',
              },
            },
            409,
          )
        }
        const cancelled: MockJob = {
          ...job,
          state: 'CANCELLED',
          progress: 1,
          cancel_requested: true,
          finished_at: UPDATED,
          record_version: job.record_version + 1,
        }
        if (id === REVIEW_ID) jobs.review = cancelled
        else jobs.failed = cancelled
        return json(route, cancelled, 202)
      }

      calls.retry += 1
      const retried: MockJob = {
        ...job,
        state: 'VALIDATING',
        progress: 0.05,
        attempts: 0,
        cancel_requested: false,
        error_code: null,
        error_message: null,
        retryable: null,
        finished_at: null,
        record_version: job.record_version + 1,
      }
      if (id === REVIEW_ID) jobs.review = retried
      else jobs.failed = retried
      return json(route, retried, 202)
    }

    const detail = path.match(/\/api\/v1\/corrections\/([^/]+)$/)
    if (detail && method === 'GET') {
      const id = detail[1]
      const job = id === REVIEW_ID ? jobs.review : id === FAILED_ID ? jobs.failed : null
      if (!job) return json(route, { error: { code: 'NOT_FOUND', message: 'Job not found.' } }, 404)
      return json(route, detailFor(job))
    }

    return json(route, { error: { code: 'NOT_FOUND', message: 'No mock route.' } }, 404)
  })

  const response = await page.goto('/queue', { waitUntil: 'load' })
  expect(response?.status()).toBe(200)
  await expect(page.getByRole('region', { name: 'Correction jobs' })).toBeVisible({
    timeout: 30_000,
  })
  return { calls, jobs }
}

function jobRow(page: Page, id: string) {
  // The queue is a list of job rows, not a table; select the row itself so the
  // actions inside it are reachable.
  return page.locator('.rd-queue__row').filter({ hasText: id.slice(0, 8) })
}

test.describe('correction job actions', () => {
  test('Detail opens both displayed jobs with real engine context', async ({ page }) => {
    await openQueue(page)

    await jobRow(page, REVIEW_ID).getByRole('button', { name: 'Detail' }).click()
    const detail = page.getByRole('dialog', { name: 'Job detail' })
    await expect(detail).toBeVisible()
    await expect(detail.getByText(REVIEW_ID, { exact: true })).toBeVisible()
    await expect(detail.getByText(REVIEW_SUBMISSION, { exact: true })).toBeVisible()
    await expect(detail.getByText('Fixture assignment', { exact: false })).toBeVisible()
    await expect(detail.getByText('google / gemini-2.5-pro')).toBeVisible()
    // The reason is printed as a question lead plus its engine detail, so both
    // halves are asserted rather than one contiguous string.
    await expect(detail.getByText('Question 1a', { exact: true })).toBeVisible()
    await expect(
      detail
        .locator('.rd-job__reasons')
        .getByText('the model response was not usable.', { exact: false }),
    ).toBeVisible()
    await expect(detail.getByText('student-1', { exact: true })).toBeVisible()
    await expect(detail.getByText('student-1.pdf', { exact: true })).toBeVisible()
    await detail.getByRole('button', { name: 'Close' }).click()

    await jobRow(page, FAILED_ID).getByRole('button', { name: 'Detail' }).click()
    const second = page.getByRole('dialog', { name: 'Job detail' })
    await expect(second.getByText(FAILED_ID, { exact: true })).toBeVisible()
    await expect(second.getByText(FAILED_SUBMISSION, { exact: true })).toBeVisible()
    await expect(second.getByText(/PIPELINE_UNAVAILABLE/)).toBeVisible()
    await expect(second.getByText('No provider call recorded')).toBeVisible()
  })

  test('Cancel performs the engine operation and refreshes the row', async ({ page }) => {
    const { calls } = await openQueue(page)

    const row = jobRow(page, REVIEW_ID)
    await expect(row.getByRole('button', { name: 'Cancel' })).toBeEnabled()
    await row.getByRole('button', { name: 'Cancel' }).click()

    const confirm = page.getByRole('alertdialog', { name: 'Cancel this job?' })
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: 'Confirm cancel' }).click()

    await expect(page.locator('.app-message[data-tone="ok"]')).toContainText(
      `Job ${REVIEW_ID.slice(0, 8)} is CANCELLED`,
    )
    await expect.poll(() => calls.cancel).toBe(1)
    await expect(jobRow(page, REVIEW_ID).getByText('CANCELLED', { exact: true })).toBeVisible()
    await expect(jobRow(page, REVIEW_ID).getByRole('button', { name: 'Cancel' })).toBeDisabled()

    // The action does not replace the list with frontend-only state: Detail
    // still reads the job from the engine after the refresh.
    await jobRow(page, REVIEW_ID).getByRole('button', { name: 'Detail' }).click()
    await expect(
      page
        .getByRole('dialog', { name: 'Job detail' })
        .locator('.app-chip')
        .filter({ hasText: 'CANCELLED' }),
    ).toBeVisible()
  })

  test('Retry is enabled only for failed or suspended jobs and explains the refusal', async ({
    page,
  }) => {
    const { calls } = await openQueue(page)

    const reviewRow = jobRow(page, REVIEW_ID)
    await expect(reviewRow.getByRole('button', { name: 'Retry' })).toBeDisabled()
    await expect(reviewRow).toContainText('Teacher review is required first')
    await expect(reviewRow.getByRole('button', { name: 'Cancel' })).toBeEnabled()

    const failedRow = jobRow(page, FAILED_ID)
    await expect(failedRow.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    await expect(failedRow).toContainText('Failed jobs cannot be cancelled; retry instead.')
    await failedRow.getByRole('button', { name: 'Retry' }).click()

    await expect(page.locator('.app-message[data-tone="ok"]')).toContainText(
      `Job ${FAILED_ID.slice(0, 8)} is VALIDATING`,
    )
    await expect.poll(() => calls.retry).toBe(1)
    await expect(jobRow(page, FAILED_ID).getByText('VALIDATING', { exact: true })).toBeVisible()
  })

  test('an engine refusal is shown as an error and leaves the state unchanged', async ({ page }) => {
    await openQueue(page, { failCancel: true })

    const row = jobRow(page, REVIEW_ID)
    await row.getByRole('button', { name: 'Cancel' }).click()
    await page
      .getByRole('alertdialog', { name: 'Cancel this job?' })
      .getByRole('button', { name: 'Confirm cancel' })
      .click()

    const alert = page.getByRole('alert')
    await expect(alert).toContainText('The job changed state before cancellation.')
    await expect(alert).toContainText('JOB_NOT_CANCELLABLE')
    await expect(page.locator('.app-message[data-tone="ok"]')).toHaveCount(0)
    await expect(jobRow(page, REVIEW_ID).getByText('REVIEW_REQUIRED', { exact: true })).toBeVisible()
  })
})
