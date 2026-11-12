import type { Job, JobDetail, JobState } from '../api/types'

/**
 * How a job's state reads on the desk.
 *
 * Terminality is not the question here: a refused run and a failed run both
 * need a person, so both read as attention, while a cancelled or running job
 * stays quiet.
 */
export function jobTone(state: JobState): 'ok' | 'attention' | 'neutral' {
  if (state === 'COMPLETED') return 'ok'
  if (state === 'FAILED' || state === 'REVIEW_REQUIRED' || state === 'RETRY_SUSPENDED') {
    return 'attention'
  }
  return 'neutral'
}

export function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : 'Not recorded'
}

/** A clock time, for the run history where the date is already established. */
export function formatClock(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** How long passed between two recorded times. Null when either is missing. */
export function elapsed(from: string | null, to: string | null): string | null {
  if (!from || !to) return null
  const ms = new Date(to).getTime() - new Date(from).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  const seconds = Math.round(ms / 1000)
  if (seconds < 1) return `${ms} ms`
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

/**
 * Which correction engine produced this run.
 *
 * The engine is recorded on the job when it runs, so a job that has not been
 * claimed yet has none, and a job created before attribution was captured has
 * none either. Both are said plainly: the screen never guesses an engine from
 * the current configuration.
 */
export function engineProvenance(job: Job | JobDetail): { label: string; recorded: boolean } {
  if (job.engine_name) {
    return {
      label: job.engine_version ? `${job.engine_name} · ${job.engine_version}` : job.engine_name,
      recorded: true,
    }
  }
  if (job.requested_engine_name) {
    return { label: `${job.requested_engine_name} · requested, not yet run`, recorded: false }
  }
  return { label: 'Engine not recorded', recorded: false }
}
