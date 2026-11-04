/**
 * Synthetic demonstration data for the marketing surface.
 *
 * Every figure on this page is invented for presentation. No student, class or
 * mark here comes from a real workspace, and nothing in this file is a claim
 * that the correction pipeline is operational.
 */

export type DemoStatus =
  | 'approved'
  | 'review'
  | 'queued'
  | 'marking'
  | 'override'
  | 'published'

export type QuestionResult = {
  code: string
  topic: string
  max: number
  awarded: number | null
  mean: number
  status: DemoStatus
}

export const DEMO_META = {
  label: 'Demonstration data',
  assignment: 'IGCSE 4MA1 · Algebra II',
  paper: 'Homework 6',
  className: '10B · Set 2',
  scheme: 'Scheme v3 · locked',
  submissions: 48,
  submitted: 34,
  marked: 29,
  needsReview: 2,
  median: 78,
  totalMarks: 30,
} as const

export const DEMO_QUESTIONS: QuestionResult[] = [
  { code: '1a', topic: 'Expand and simplify', max: 2, awarded: 2, mean: 1.8, status: 'approved' },
  { code: '1b', topic: 'Factorise fully', max: 3, awarded: 3, mean: 2.4, status: 'approved' },
  { code: '2', topic: 'Linear inequality', max: 4, awarded: 2, mean: 2.9, status: 'review' },
  { code: '3', topic: 'Rearrange the formula', max: 3, awarded: 3, mean: 2.2, status: 'approved' },
  { code: '4', topic: 'Simultaneous equations', max: 5, awarded: 4, mean: 3.6, status: 'override' },
  { code: '5', topic: 'Quadratic by factorising', max: 4, awarded: 4, mean: 3.1, status: 'approved' },
  { code: '6', topic: 'Algebraic fractions', max: 5, awarded: null, mean: 0, status: 'queued' },
  { code: '7', topic: 'Proof by completing the square', max: 4, awarded: 3, mean: 2.5, status: 'approved' },
]

export const HERO_ROWS: QuestionResult[] = [
  { code: 'Q1', topic: 'Expand and simplify', max: 2, awarded: 2, mean: 1.8, status: 'approved' },
  { code: 'Q2', topic: 'Factorise fully', max: 3, awarded: 3, mean: 2.4, status: 'approved' },
  { code: 'Q3', topic: 'Linear inequality', max: 4, awarded: 2, mean: 2.9, status: 'review' },
  { code: 'Q4', topic: 'Rearrange the formula', max: 3, awarded: 3, mean: 2.2, status: 'approved' },
  { code: 'Q5', topic: 'Simultaneous equations', max: 4, awarded: 4, mean: 3.6, status: 'override' },
  { code: 'Q6', topic: 'Algebraic fractions', max: 5, awarded: null, mean: 0, status: 'queued' },
]

export const DEMO_DISTRIBUTION = [
  { band: '0–4', count: 1 },
  { band: '5–9', count: 2 },
  { band: '10–14', count: 5 },
  { band: '15–19', count: 9 },
  { band: '20–24', count: 8 },
  { band: '25–30', count: 4 },
]

export type DemoJob = {
  id: string
  student: string
  state: DemoStatus
  progress: number
  detail: string
}

export const DEMO_JOBS: DemoJob[] = [
  { id: 'SUB-0418', student: 'A. Okonkwo', state: 'marking', progress: 0.68, detail: 'Q5 of 7 · verifying' },
  { id: 'SUB-0419', student: 'B. Ferreira', state: 'queued', progress: 0, detail: 'Queued · position 2' },
  { id: 'SUB-0420', student: 'C. Nakamura', state: 'queued', progress: 0, detail: 'Queued · position 3' },
  { id: 'SUB-0416', student: 'D. Haddad', state: 'review', progress: 1, detail: 'Q3 · mark below method total' },
  { id: 'SUB-0412', student: 'E. Lindqvist', state: 'approved', progress: 1, detail: 'Approved 09:41 · J. Adeyemi' },
]

export const DEMO_ACTIVITY = [
  { time: '09:47', text: 'Job 3f2a finished · 7 of 7 questions reconciled', state: 'approved' as DemoStatus },
  { time: '09:46', text: 'Q4 override 3 → 4 recorded with a reason', state: 'override' as DemoStatus },
  { time: '09:44', text: 'Q3 parked for review · answer matched two methods', state: 'review' as DemoStatus },
  { time: '09:43', text: 'SUB-0417 queued · scheme v3', state: 'queued' as DemoStatus },
]

export const DEMO_REVIEWS = [
  { id: 'SUB-0416', student: 'D. Haddad', question: 'Q3', note: 'Method marks present, final answer missing' },
  { id: 'SUB-0409', student: 'F. Mbeki', question: 'Q7', note: 'Handwriting unclear on the final line' },
]

export const DEMO_HEALTH = [
  { label: 'Jobs reaching a terminal state', value: '99.2%', note: '24 h window · synthetic' },
  { label: 'Median end-to-end', value: '71 s', note: 'including review · synthetic' },
  { label: 'Unresolved marks', value: '0', note: 'never silently zero · design invariant' },
]
