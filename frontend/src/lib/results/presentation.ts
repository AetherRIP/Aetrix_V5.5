import type { QuestionResult } from '../api/types'

/**
 * What the record says about a question, as a decision rather than a status.
 *
 * `processing_state` is authoritative when present; rows written before the
 * column existed are read from `status` the same way the backend reads them.
 */
export type QuestionState = 'MARKED' | 'CONFIRMED_ZERO' | 'UNMARKED' | 'NEEDS_REVIEW'

export function questionState(result: QuestionResult): QuestionState {
  const explicit = result.processing_state
  if (
    explicit === 'MARKED' ||
    explicit === 'CONFIRMED_ZERO' ||
    explicit === 'UNMARKED' ||
    explicit === 'NEEDS_REVIEW'
  ) {
    return explicit
  }
  if (result.status === 'AWARDED') return 'MARKED'
  // A zero that still needs a person is not a confirmed zero.
  if (result.status === 'ZERO') return result.review_required ? 'NEEDS_REVIEW' : 'CONFIRMED_ZERO'
  if (result.status === 'UNMARKED') return 'UNMARKED'
  return 'NEEDS_REVIEW'
}

/** Only these two states carry a decision about the student's work. */
export function isDecidedState(state: QuestionState): boolean {
  return state === 'MARKED' || state === 'CONFIRMED_ZERO'
}

/** The mark to print: an undecided question has none, and zero is not a stand-in. */
export function markLabel(result: QuestionResult): string {
  const state = questionState(result)
  if (isDecidedState(state)) return `${result.awarded_marks} / ${result.max_marks}`
  return state === 'UNMARKED' ? 'Not marked' : 'Unconfirmed'
}

export function stateLabel(state: QuestionState): string {
  if (state === 'MARKED') return 'Marked'
  if (state === 'CONFIRMED_ZERO') return 'Confirmed zero'
  if (state === 'UNMARKED') return 'Not marked'
  return 'Needs review'
}
