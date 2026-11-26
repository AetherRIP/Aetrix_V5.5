import { useCallback, useEffect, useState } from 'react'
import { env } from '../../lib/env'
import {
  classroomMonitoringOverview,
  ignoreMonitoredSubmission,
  monitoredSubmissions,
  resolveMonitoredSubmission,
  retryMonitoredSubmission,
  syncClassroomMonitoring,
  updateClassroomMonitoring,
  type MonitorHealth,
  type MonitorOverview,
  type MonitorSubmission,
} from '../../lib/api/classroom'
import { Panel } from './PageBlocks'
import { StatusChip } from './StatePanel'

type Notice = { tone: 'ok' | 'error'; message: string }

function formatMoment(value: string | null): string {
  if (!value) return 'never'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'unknown' : parsed.toLocaleString('en-GB')
}

function healthTone(health: MonitorHealth): 'ok' | 'attention' | 'neutral' {
  if (health === 'HEALTHY') return 'ok'
  if (health === 'BLOCKED' || health === 'DEGRADED') return 'attention'
  return 'neutral'
}

function pipelineTone(state: string): 'ok' | 'attention' | 'neutral' {
  if (state === 'READY') return 'ok'
  if (state === 'FAILED' || state === 'NEEDS_TEACHER') return 'attention'
  return 'neutral'
}

function correctionTone(state: string): 'ok' | 'attention' | 'neutral' {
  if (state === 'COMPLETED' || state === 'REVIEW_REQUIRED') return 'ok'
  if (state === 'FAILED') return 'attention'
  return 'neutral'
}

/**
 * Automatic submission monitoring for one workspace.
 *
 * Reads only what the engine stored and calls only the monitoring routes. The
 * health, counts and states shown here are reported by the backend; nothing on
 * this screen decides eligibility or marks anything.
 */
export function ClassroomMonitoringPanel({
  tenantId,
  token,
}: {
  tenantId: string
  token: string
}) {
  const [overview, setOverview] = useState<MonitorOverview | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [submissions, setSubmissions] = useState<MonitorSubmission[]>([])
  const [submissionsError, setSubmissionsError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [note, setNote] = useState('')

  const loadOverview = useCallback(async () => {
    const result = await classroomMonitoringOverview(tenantId, { token })
    if (result.status === 'ok') {
      setOverview(result.data)
      setLoadError(null)
    } else {
      setOverview(null)
      setLoadError(result.reason)
    }
  }, [tenantId, token])

  const loadSubmissions = useCallback(
    async (linkId: string) => {
      const result = await monitoredSubmissions(tenantId, linkId, { token })
      if (result.status === 'ok') {
        setSubmissions(result.data)
        setSubmissionsError(null)
      } else {
        setSubmissions([])
        setSubmissionsError(result.reason)
      }
    },
    [tenantId, token],
  )

  useEffect(() => {
    void loadOverview()
  }, [loadOverview])

  useEffect(() => {
    if (selected) void loadSubmissions(selected)
  }, [selected, loadSubmissions])

  async function run(key: string, action: () => Promise<Notice>) {
    setBusy(key)
    setNotice(null)
    const result = await action()
    setBusy(null)
    setNotice(result)
  }

  function update(linkId: string, payload: Parameters<typeof updateClassroomMonitoring>[2]) {
    return run(`update:${linkId}`, async () => {
      const result = await updateClassroomMonitoring(tenantId, linkId, payload, { token })
      if (result.status !== 'ok') return { tone: 'error', message: result.reason }
      await loadOverview()
      return { tone: 'ok', message: 'Monitoring updated.' }
    })
  }

  function sync(linkId: string) {
    return run(`sync:${linkId}`, async () => {
      const result = await syncClassroomMonitoring(tenantId, linkId, { token })
      if (result.status !== 'ok') return { tone: 'error', message: result.reason }
      await loadOverview()
      if (selected === linkId) await loadSubmissions(linkId)
      const counts = result.data.counts
      return {
        tone: result.data.status === 'SUCCEEDED' ? 'ok' : 'error',
        message:
          `${counts.listed ?? 0} listed, ${counts.ready ?? 0} ready, ` +
          `${counts.needs_teacher ?? 0} need review, ${counts.ignored ?? 0} ignored, ` +
          `${counts.failed ?? 0} failed.` +
          (result.data.problems.length ? ` ${result.data.problems[0]}` : ''),
      }
    })
  }

  async function openFirstPage(documentId: string) {
    const base = env.apiBaseUrl.replace(/\/$/, '')
    try {
      const response = await fetch(`${base}/api/v1/documents/${documentId}/pages/1`, {
        headers: { authorization: `Bearer ${token}` },
      })
      if (!response.ok) {
        setNotice({ tone: 'error', message: 'The page could not be read from the engine.' })
        return
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch {
      setNotice({ tone: 'error', message: 'The page could not be opened.' })
    }
  }

  const states = overview?.states ?? []

  return (
    <Panel
      title="Automatic submission monitoring"
      note="Off until a teacher enables it"
    >
      <p className="panel-copy">
        Monitoring reads turned-in work, retrieves only supported attachments, inspects them
        locally and queues eligible submissions for the existing correction engine. External
        links are never fetched and inspection never calls a marking provider.
      </p>

      {overview && !overview.monitoring_enabled_on_server ? (
        <p className="panel-copy">
          <StatusChip tone="attention">Scheduler off</StatusChip> The server’s scheduled monitor
          is disabled (<span className="mono">AETRIX_CLASSROOM__MONITORING_ENABLED</span>). Manual
          synchronization works, but no automatic poll will run until an operator enables it.
        </p>
      ) : null}

      {notice ? (
        <p className="panel-copy" role="status">
          <StatusChip tone={notice.tone === 'ok' ? 'ok' : 'attention'}>
            {notice.tone === 'ok' ? 'Done' : 'Failed'}
          </StatusChip>{' '}
          {notice.message}
        </p>
      ) : null}

      {loadError ? (
        <p className="panel-copy">{loadError}</p>
      ) : overview === null ? (
        <p className="panel-copy">Reading monitoring state…</p>
      ) : states.length === 0 ? (
        <p className="panel-copy">
          No coursework is published to Google Classroom yet. Publish an assignment to Classroom
          before monitoring can watch it.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Monitored coursework and its health</caption>
            <thead>
              <tr>
                <th scope="col">Assignment</th>
                <th scope="col">Health</th>
                <th scope="col">Students</th>
                <th scope="col">Queue</th>
                <th scope="col">Last poll</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {states.map((row) => (
                <tr key={row.coursework_link_id}>
                  <td>
                    <span className="data-table__strong">{row.assignment_name}</span>
                    <span className="gem-footnote">
                      course {row.course_id} · every {Math.round(row.interval_seconds / 60)} min
                    </span>
                  </td>
                  <td>
                    <StatusChip tone={healthTone(row.health)}>{row.health}</StatusChip>
                    {row.last_poll_error ? (
                      <span className="gem-footnote">{row.last_poll_error}</span>
                    ) : null}
                  </td>
                  <td>
                    {row.submitted_students} submitted
                    <span className="gem-footnote">
                      {row.expected_students} expected · {row.awaiting_review} to review
                    </span>
                  </td>
                  <td>
                    {row.queued_corrections + row.processing_corrections} active
                    <span className="gem-footnote">
                      {row.completed_corrections} done · {row.failed_corrections} failed
                    </span>
                  </td>
                  <td>
                    {formatMoment(row.last_polled_at)}
                    <span className="gem-footnote">next {formatMoment(row.next_poll_at)}</span>
                  </td>
                  <td>
                    <div className="app-inline-actions">
                      <button
                        type="button"
                        className="btn btn--small"
                        disabled={busy !== null}
                        onClick={() => void update(row.coursework_link_id, { enabled: !row.enabled })}
                      >
                        {row.enabled ? 'Disable' : 'Enable'}
                      </button>
                      <button
                        type="button"
                        className="btn btn--small"
                        disabled={busy !== null || !row.enabled}
                        onClick={() => void update(row.coursework_link_id, { paused: !row.paused })}
                      >
                        {row.paused ? 'Resume' : 'Pause'}
                      </button>
                      <button
                        type="button"
                        className="btn btn--small"
                        disabled={busy !== null}
                        onClick={() => void sync(row.coursework_link_id)}
                      >
                        {busy === `sync:${row.coursework_link_id}` ? 'Syncing…' : 'Sync now'}
                      </button>
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() =>
                          setSelected(
                            selected === row.coursework_link_id ? null : row.coursework_link_id,
                          )
                        }
                      >
                        {selected === row.coursework_link_id ? 'Close' : 'Submissions'}
                      </button>
                    </div>
                    <label className="panel-copy">
                      <input
                        type="checkbox"
                        checked={row.auto_queue}
                        disabled={busy !== null}
                        onChange={(event) =>
                          void update(row.coursework_link_id, {
                            auto_queue: event.target.checked,
                          })
                        }
                      />{' '}
                      Queue eligible work automatically
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected ? (
        <div className="app-stack">
          <h3 className="panel-title">Submission inspection</h3>
          <p className="panel-copy">
            A version is reviewed only when it is readable and plausibly this assignment’s work.
            Blank, corrupt, unsupported or unrelated work never reaches the marking engine.
          </p>
          <label className="app-form__label" htmlFor="monitor-note">
            Note for a decision (at least five characters)
          </label>
          <input
            id="monitor-note"
            className="app-input"
            value={note}
            maxLength={500}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why this submission is accepted, ignored or retried"
          />

          {submissionsError ? (
            <p className="panel-copy">{submissionsError}</p>
          ) : submissions.length === 0 ? (
            <p className="panel-copy">
              No submission has been detected for this coursework yet. Nothing is invented; this
              list is what Classroom reported.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">
                  Detected submissions, inspection findings and correction state
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Student</th>
                    <th scope="col">Version</th>
                    <th scope="col">Pipeline</th>
                    <th scope="col">Correction</th>
                    <th scope="col">Relevance</th>
                    <th scope="col">Attachments</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map((row) => (
                    <tr key={row.submission_link_id}>
                      <td>
                        <span className="data-table__strong">
                          {row.student_name ?? row.student_ref}
                        </span>
                        <span className="gem-footnote">
                          {row.late ? 'Late · ' : ''}
                          {row.google_state ?? 'state unknown'} · detected{' '}
                          {formatMoment(row.detected_at)}
                        </span>
                      </td>
                      <td>
                        v{row.version}
                        <span className="gem-footnote">{row.version_count} version(s)</span>
                      </td>
                      <td>
                        <StatusChip tone={pipelineTone(row.state)}>{row.state}</StatusChip>
                        {row.last_error ? (
                          <span className="gem-footnote">{row.last_error}</span>
                        ) : null}
                      </td>
                      <td>
                        <StatusChip tone={correctionTone(row.correction_state)}>
                          {row.correction_state}
                        </StatusChip>
                      </td>
                      <td>
                        {row.relevance}
                        {row.decision_reasons.length ? (
                          <span className="gem-footnote">
                            {row.decision_reasons
                              .map((reason) => reason.message)
                              .filter(Boolean)
                              .slice(0, 2)
                              .join(' ')}
                          </span>
                        ) : null}
                      </td>
                      <td>
                        {row.attachments.length === 0 ? (
                          'none'
                        ) : (
                          <ul className="panel-copy">
                            {row.attachments.map((attachment) => (
                              <li key={attachment.position}>
                                {attachment.title ?? attachment.kind} · {attachment.status}
                                {attachment.page_count ? ` · ${attachment.page_count}p` : ''}
                                {attachment.reason ? (
                                  <span className="gem-footnote">{attachment.reason}</span>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td>
                        <div className="app-inline-actions">
                          {row.document_id ? (
                            <button
                              type="button"
                              className="btn btn--small"
                              onClick={() => void openFirstPage(row.document_id as string)}
                            >
                              View page 1
                            </button>
                          ) : null}
                          {row.state === 'FAILED' || row.state === 'NEEDS_TEACHER' ? (
                            <button
                              type="button"
                              className="btn btn--small"
                              disabled={busy !== null}
                              onClick={() =>
                                void run(`retry:${row.submission_link_id}`, async () => {
                                  const result = await retryMonitoredSubmission(
                                    tenantId,
                                    row.submission_link_id,
                                    { token },
                                  )
                                  if (result.status !== 'ok') {
                                    return { tone: 'error', message: result.reason }
                                  }
                                  await loadSubmissions(selected)
                                  return { tone: 'ok', message: result.data.message }
                                })
                              }
                            >
                              Retry
                            </button>
                          ) : null}
                          {row.state === 'NEEDS_TEACHER' && note.trim().length >= 5 ? (
                            <button
                              type="button"
                              className="btn btn--small btn--primary"
                              disabled={busy !== null}
                              onClick={() =>
                                void run(`accept:${row.submission_link_id}`, async () => {
                                  const result = await resolveMonitoredSubmission(
                                    tenantId,
                                    row.submission_link_id,
                                    'REQUEUE',
                                    note.trim(),
                                    { token },
                                  )
                                  if (result.status !== 'ok') {
                                    return { tone: 'error', message: result.reason }
                                  }
                                  await loadSubmissions(selected)
                                  await loadOverview()
                                  return {
                                    tone: 'ok',
                                    message: 'The submission was accepted for correction.',
                                  }
                                })
                              }
                            >
                              Accept and queue
                            </button>
                          ) : null}
                          {row.state !== 'IGNORED' &&
                          row.correction_state !== 'QUEUED' &&
                          row.correction_state !== 'PROCESSING' &&
                          note.trim().length >= 5 ? (
                            <button
                              type="button"
                              className="btn btn--small btn--danger"
                              disabled={busy !== null}
                              onClick={() =>
                                void run(`ignore:${row.submission_link_id}`, async () => {
                                  const result = await ignoreMonitoredSubmission(
                                    tenantId,
                                    row.submission_link_id,
                                    note.trim(),
                                    { token },
                                  )
                                  if (result.status !== 'ok') {
                                    return { tone: 'error', message: result.reason }
                                  }
                                  await loadSubmissions(selected)
                                  await loadOverview()
                                  return {
                                    tone: 'ok',
                                    message: 'The submission was marked ignored.',
                                  }
                                })
                              }
                            >
                              Ignore
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {overview && overview.recent_runs.length ? (
            <div>
              <h4 className="panel-title">Recent monitoring runs</h4>
              <ul className="panel-copy">
                {overview.recent_runs.slice(0, 5).map((run) => (
                  <li key={run.id}>
                    {formatMoment(run.started_at)} · {run.trigger} · {run.status}
                    {run.error_message ? ` · ${run.error_message}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </Panel>
  )
}
