import { expect, test } from '@playwright/test'

import type { QuestionResult } from '../src/lib/api/types'
import { isDecidedState, markLabel, questionState, stateLabel } from '../src/lib/results/presentation'

function result(overrides: Partial<QuestionResult>): QuestionResult {
  return {
    id: '00000000-0000-0000-0000-000000000000',
    question_id: '1a',
    max_marks: 5,
    awarded_marks: 0,
    status: 'AWARDED',
    student_answer: null,
    working_summary: null,
    confidence: null,
    review_required: false,
    processing_state: null,
    raw_awarded_marks: null,
    normalised_awarded_marks: null,
    normalisation_anomaly: null,
    scheme_concerns: [],
    criteria: [],
    evidence: [],
    ...overrides,
  }
}

test.describe('question presentation', () => {
  test('a needs-review question is never shown as 0 / maximum', () => {
    const row = result({
      status: 'REVIEW_REQUIRED',
      processing_state: 'NEEDS_REVIEW',
      awarded_marks: 0,
      max_marks: 5,
      review_required: true,
    })

    const state = questionState(row)
    expect(state).toBe('NEEDS_REVIEW')
    expect(isDecidedState(state)).toBe(false)
    expect(markLabel(row)).toBe('Unconfirmed')
    expect(markLabel(row)).not.toContain('0 /')
    expect(stateLabel(state)).toBe('Needs review')
  })

  test('an unmarked question is never shown as a confirmed zero', () => {
    const row = result({ status: 'UNMARKED', processing_state: 'UNMARKED', awarded_marks: 0 })

    const state = questionState(row)
    expect(state).toBe('UNMARKED')
    expect(isDecidedState(state)).toBe(false)
    expect(markLabel(row)).toBe('Not marked')
    expect(stateLabel(state)).toBe('Not marked')
  })

  test('a confirmed zero is displayed as zero of the maximum', () => {
    const row = result({
      status: 'ZERO',
      processing_state: 'CONFIRMED_ZERO',
      awarded_marks: 0,
      max_marks: 5,
      confidence: 0.97,
    })

    const state = questionState(row)
    expect(state).toBe('CONFIRMED_ZERO')
    expect(isDecidedState(state)).toBe(true)
    expect(markLabel(row)).toBe('0 / 5')
    expect(stateLabel(state)).toBe('Confirmed zero')
  })

  test('a marked question displays its award', () => {
    const row = result({ status: 'AWARDED', processing_state: 'MARKED', awarded_marks: 3 })
    expect(questionState(row)).toBe('MARKED')
    expect(markLabel(row)).toBe('3 / 5')
  })

  test('a row written before the state column is read from its status', () => {
    expect(questionState(result({ status: 'AWARDED', processing_state: null }))).toBe('MARKED')
    expect(
      questionState(result({ status: 'REVIEW_REQUIRED', processing_state: null })),
    ).toBe('NEEDS_REVIEW')
    expect(questionState(result({ status: 'UNMARKED', processing_state: null }))).toBe('UNMARKED')
    // A zero that still needs a person is not a confirmed zero.
    expect(
      questionState(result({ status: 'ZERO', processing_state: null, review_required: true })),
    ).toBe('NEEDS_REVIEW')
    expect(
      questionState(result({ status: 'ZERO', processing_state: null, review_required: false })),
    ).toBe('CONFIRMED_ZERO')
  })
})
