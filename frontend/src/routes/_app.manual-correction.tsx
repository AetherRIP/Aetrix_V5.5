import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import type { Job, JobProgress, ProgressQuestion } from '../lib/api/types'
import { manualCorrectionService, queueService } from '../lib/services'

export const Route = createFileRoute('/_app/manual-correction')({
  component: ManualCorrection,
})

const TERMINAL: Job['state'][] = ['COMPLETED', 'FAILED', 'CANCELLED']
const RESUME_KEY = 'aetrix:manual-correction:job'

const STAGE_LABELS: Record<string, string> = {
  MARKING: 'Question-level marking',
  TRANSCRIPTION: 'Independent transcription',
  DOUBLE_CHECK: 'Second marking',
  INTEGRITY: 'Integrity check',
  GUARD: 'Result guard',
  RECOVERY: 'Recovery',
}

const STATE_LABELS: Record<string, string> = {
  CREATED: 'Queued',
  VALIDATING: 'Validating files',
  PROCESSING_DOCUMENTS: 'Preparing document pages',
  BUILDING_BLUEPRINT: 'Preparing the question structure',
  CORRECTING: 'Marking questions',
  VERIFYING: 'Verifying decisions',
  COHORT_PENDING: 'Waiting for cohort finalisation',
  REVIEW_REQUIRED: 'Needs a person',
  FINALIZING: 'Finalising results',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
  RETRY_SUSPENDED: 'Paused',
}

function toneForState(state: string): 'ok' | 'attention' | 'neutral' {
  if (state === 'COMPLETED') return 'ok'
  if (state === 'FAILED' || state === 'REVIEW_REQUIRED' || state === 'RETRY_SUSPENDED') {
    return 'attention'
  }
  return 'neutral'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatClock(seconds: number | null): string {
  if (seconds === null) return 'Not reported'
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function formatWhen(iso: string | null): string {
  if (!iso) return 'Not recorded'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString()
}

function questionTone(question: ProgressQuestion): 'ok' | 'attention' | 'neutral' {
  if (question.review_required || question.status === 'REVIEW_REQUIRED') return 'attention'
  if (question.status === 'PENDING') return 'neutral'
  if (question.awarded_marks !== null) return 'ok'
  return 'neutral'
}

function questionLabel(question: ProgressQuestion): string {
  if (question.status === 'PENDING') return 'Pending'
  return question.processing_state ?? question.status
}

type UploadSlotProps = {
  title: string
  note: string
  required: boolean
  file: File | null
  accept: string
  onChange: (file: File | null) => void
  inputId: string
}

function UploadSlot({ title, note, required, file, accept, onChange, inputId }: UploadSlotProps) {
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  return (
    <section className="mc-slot" data-filled={file ? 'true' : undefined}>
      <div className="mc-slot__head">
        <h3 className="mc-slot__title">
          {title}
          <span className="mc-slot__required mono">{required ? 'Required' : 'Optional'}</span>
        </h3>
        <p className="mc-slot__note">{note}</p>
      </div>
      {file ? (
        <div className="mc-file">
          <div className="mc-file__meta">
            <p className="mc-file__name">{file.name}</p>
            <p className="mc-file__facts mono">
              {formatBytes(file.size)} · {file.type || 'type supplied by the browser'} ·{' '}
              {file.type.startsWith('image/') ? '1 page' : 'page count checked by the engine'}
            </p>
          </div>
          <div className="mc-file__actions">
            {previewUrl ? (
              <a className="btn btn--small btn--outline" href={previewUrl} target="_blank" rel="noreferrer">
                Preview
              </a>
            ) : null}
            <label className="btn btn--small btn--outline" htmlFor={inputId}>
              Replace
            </label>
            <button type="button" className="btn btn--small btn--outline" onClick={() => onChange(null)}>
              Remove
            </button>
          </div>
        </div>
      ) : (
        <label className="mc-drop" htmlFor={inputId}>
          <span className="mc-drop__icon" aria-hidden="true">
            ↑
          </span>
          <span className="mc-drop__title">Choose a file</span>
          <span className="mc-drop__hint">PDF, PNG or JPEG. The engine checks the signature and size.</span>
        </label>
      )}
      <input
        id={inputId}
        type="file"
        accept={accept}
        className="visually-hidden"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
    </section>
  )
}

function ManualCorrection() {
  const session = useEngineSession()
  const [studentFile, setStudentFile] = useState<File | null>(null)
  const [schemeFile, setSchemeFile] = useState<File | null>(null)
  const [questionPaper, setQuestionPaper] = useState<File | null>(null)
  const [studentRef, setStudentRef] = useState('')
  const [board, setBoard] = useState('')
  const [subject, setSubject] = useState('')
  const [qualification, setQualification] = useState('')
  const [paperCode, setPaperCode] = useState('')
  const [markingMode, setMarkingMode] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'error' | 'ok'; text: string } | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [progress, setProgress] = useState<JobProgress | null>(null)
  const [progressError, setProgressError] = useState<string | null>(null)
  const [history, setHistory] = useState<Job[]>([])
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [lastPoll, setLastPoll] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const stateRef = useRef<string | null>(null)

  const token = session.token
  const canReview = session.capabilities.includes('review')

  useEffect(() => {
    if (!token) return
    const saved = window.localStorage.getItem(RESUME_KEY)
    if (saved) setJobId(saved)
  }, [token])

  const loadHistory = useCallback(async () => {
    if (!token) return
    const result = await manualCorrectionService.list({ token })
    if (result.status === 'ok') {
      setHistory(result.data)
      setHistoryError(null)
    } else {
      setHistoryError(result.reason)
    }
  }, [token])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  useEffect(() => {
    stateRef.current = progress?.state ?? null
  }, [progress])

  const poll = useCallback(async () => {
    if (!token || !jobId) return
    const result = await manualCorrectionService.progress(jobId, { token })
    if (result.status === 'ok') {
      setProgress(result.data)
      setProgressError(null)
      setLastPoll(new Date().toISOString())
      if (TERMINAL.includes(result.data.state)) {
        void loadHistory()
      }
    } else {
      setProgressError(result.reason)
    }
  }, [jobId, loadHistory, token])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void poll()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [poll])

  useEffect(() => {
    if (!jobId || !token) return
    let cancelled = false
    const tick = async () => {
      if (cancelled) return
      if (document.visibilityState === 'visible') await poll()
      if (!cancelled) {
        const stopped =
          stateRef.current !== null &&
          (TERMINAL.includes(stateRef.current as Job['state']) ||
            stateRef.current === 'REVIEW_REQUIRED')
        timer.current = window.setTimeout(tick, stopped ? 15000 : 3000)
      }
    }
    void tick()
    return () => {
      cancelled = true
      if (timer.current !== null) window.clearTimeout(timer.current)
    }
    // The loop reads the latest state through a ref, so a poll response does
    // not restart the timer and double the request rate.
  }, [jobId, token, poll])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!token || busy) return
    if (!studentFile || !schemeFile) {
      setNotice({ tone: 'error', text: 'Student work and the mark scheme are both required.' })
      return
    }
    setBusy(true)
    setNotice(null)
    setProgress(null)
    setProgressError(null)
    const result = await manualCorrectionService.create(
      {
        studentFile,
        schemeFile,
        questionPaper,
        studentRef,
        board,
        subject,
        qualification,
        paperCode,
        markingMode,
      },
      { token },
    )
    setBusy(false)
    if (result.status !== 'ok') {
      setNotice({ tone: 'error', text: result.reason })
      return
    }
    const job = result.data
    window.localStorage.setItem(RESUME_KEY, job.id)
    setJobId(job.id)
    setNotice({
      tone: 'ok',
      text: `Correction job ${job.id.slice(0, 8)} is stored. Progress below is read from the engine.`,
    })
    await loadHistory()
  }

  async function retry() {
    if (!token || !jobId) return
    const result = await queueService.retry(jobId, { token })
    if (result.status === 'ok') {
      setNotice({ tone: 'ok', text: `Job ${jobId.slice(0, 8)} was returned to the worker queue.` })
      await poll()
    } else {
      setNotice({ tone: 'error', text: result.reason })
    }
  }

  function resume(id: string) {
    window.localStorage.setItem(RESUME_KEY, id)
    setJobId(id)
    setProgress(null)
    setProgressError(null)
    setNotice(null)
  }

  const activeStage = progress?.events.at(-1)?.state ?? progress?.state ?? null
  const percent = progress ? Math.round(progress.progress * 100) : 0
  const stageRows = progress?.stages ?? []
  const timeline = progress?.events ?? []

  return (
    <div className="app-stack rd-manual">
      <header className="rd-hero mc-hero">
        <div className="rd-hero__copy">
          <p className="rd-hero__kicker mono">Manual correction</p>
          <p className="rd-hero__ref">
            {progress
              ? `${STATE_LABELS[progress.state] ?? progress.state} · job ${progress.job_id.slice(0, 8)}`
              : 'Upload a script and its scheme to create a real correction job.'}
          </p>
          <p className="rd-hero__sub">
            This is the same correction engine used by assignments. It does not need a
            Classroom class or a student account; the label below is a reference, not a
            verified identity.
          </p>
        </div>
        <div className="rd-hero__actions">
          <button type="button" className="btn btn--small btn--outline" onClick={() => void loadHistory()}>
            Refresh history
          </button>
        </div>
      </header>

      {notice ? (
        <p className="app-message" data-tone={notice.tone} role={notice.tone === 'error' ? 'alert' : 'status'}>
          {notice.text}
        </p>
      ) : null}

      <div className="mc-grid">
        <form className="mc-intake" onSubmit={submit}>
          <Panel title="1 · Files" note="The engine validates signatures, not just extensions.">
            <div className="mc-slots">
              <UploadSlot
                inputId="mc-student"
                title="Student work"
                note="The script being marked. PDF, PNG or JPEG."
                required
                file={studentFile}
                accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                onChange={setStudentFile}
              />
              <UploadSlot
                inputId="mc-scheme"
                title="Mark scheme"
                note="The printed scheme the engine will transcribe and mark against."
                required
                file={schemeFile}
                accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                onChange={setSchemeFile}
              />
              <UploadSlot
                inputId="mc-paper"
                title="Question paper"
                note="Optional. Stored as the paper for this exam; the engine marks the student's script."
                required={false}
                file={questionPaper}
                accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                onChange={setQuestionPaper}
              />
            </div>
          </Panel>

          <Panel title="2 · Paper details" note="Only settings the engine actually uses are shown.">
            <div className="mc-fields">
              <label className="mc-field">
                <span>Student reference</span>
                <input
                  type="text"
                  value={studentRef}
                  maxLength={120}
                  placeholder="e.g. Script A — unverified label"
                  onChange={(event) => setStudentRef(event.target.value)}
                />
                <small>A label for this run only. It is not matched to a student account.</small>
              </label>
              <label className="mc-field">
                <span>Exam board</span>
                <input
                  type="text"
                  value={board}
                  maxLength={80}
                  placeholder="e.g. Pearson Edexcel"
                  onChange={(event) => setBoard(event.target.value)}
                />
              </label>
              <label className="mc-field">
                <span>Subject</span>
                <input
                  type="text"
                  value={subject}
                  maxLength={80}
                  placeholder="e.g. Mathematics"
                  onChange={(event) => setSubject(event.target.value)}
                />
              </label>
              <label className="mc-field">
                <span>Qualification</span>
                <input
                  type="text"
                  value={qualification}
                  maxLength={80}
                  placeholder="e.g. A Level"
                  onChange={(event) => setQualification(event.target.value)}
                />
              </label>
              <label className="mc-field">
                <span>Paper / component</span>
                <input
                  type="text"
                  value={paperCode}
                  maxLength={80}
                  placeholder="e.g. 9MA0/01"
                  onChange={(event) => setPaperCode(event.target.value)}
                />
              </label>
              <label className="mc-field">
                <span>Marking mode</span>
                <select value={markingMode} onChange={(event) => setMarkingMode(event.target.value)}>
                  <option value="">Deployment default</option>
                  <option value="PER_QUESTION">Per question</option>
                  <option value="WHOLE_PAPER">Whole paper</option>
                  <option value="PARALLEL">Parallel</option>
                </select>
                <small>
                  The mode the engine is asked to execute. The deployment default is used when
                  this is left blank.
                </small>
              </label>
            </div>
            <p className="mc-note">
              Maximum marks come from the approved scheme extraction; they are not typed here.
              Examiner reports and free-text marking instructions are not consumed by the engine,
              so this page does not pretend to apply them.
            </p>
          </Panel>

          <div className="mc-submit">
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy || !studentFile || !schemeFile || !token}
            >
              {busy ? 'Preparing scheme and starting…' : 'Start real correction'}
            </button>
            <p className="mc-submit__hint">
              The scheme is transcribed and checked before the job is stored. This can take a
              minute and consumes provider quota; nothing is marked locally.
            </p>
          </div>
        </form>

        <aside className="mc-side">
          <Panel title="Manual job history" note={`${history.length} stored`}>
            {historyError ? <p className="app-message" data-tone="error">{historyError}</p> : null}
            {history.length === 0 ? (
              <p className="app-hint">
                No manual jobs in this workspace yet. Jobs queued from here are listed after the
                engine stores them.
              </p>
            ) : (
              <ul className="mc-history">
                {history.map((job) => (
                  <li key={job.id} className="mc-history__row">
                    <button type="button" className="mc-history__open" onClick={() => resume(job.id)}>
                      <span className="mc-history__id mono">{job.id.slice(0, 8)}</span>
                      <strong>{STATE_LABELS[job.state] ?? job.state}</strong>
                      <span className="mc-history__meta mono">
                        {Math.round(job.progress * 100)}% · {formatWhen(job.created_at)}
                      </span>
                    </button>
                    <Link
                      className="btn btn--small btn--outline"
                      to="/submissions/$submissionId"
                      params={{ submissionId: job.submission_id }}
                    >
                      Report
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </aside>
      </div>

      {progressError ? (
        <p className="app-message" data-tone="error" role="alert">
          {progressError}
        </p>
      ) : null}

      {jobId && !progress ? (
        <StatePanel tone="wip" title="Reading stored progress">
          <p>The page is waiting for the engine's persisted job state. It does not estimate it.</p>
        </StatePanel>
      ) : null}

      {progress ? (
        <section className="mc-progress" aria-label="Correction progress">
          <div className="mc-progress__head">
            <div>
              <p className="mc-progress__eyebrow mono">Stored job state</p>
              <h2 className="mc-progress__title">{STATE_LABELS[progress.state] ?? progress.state}</h2>
              <p className="mc-progress__sub">
                Job <span className="mono">{progress.job_id}</span> · last update{' '}
                {formatWhen(progress.last_updated_at)}
              </p>
            </div>
            <div className="mc-progress__actions">
              <Link
                className="btn btn--small btn--primary"
                to="/submissions/$submissionId"
                params={{ submissionId: progress.submission_id }}
              >
                Open full report
              </Link>
              {canReview && (progress.state === 'FAILED' || progress.state === 'RETRY_SUSPENDED') ? (
                <button type="button" className="btn btn--small btn--outline" onClick={() => void retry()}>
                  Retry eligible job
                </button>
              ) : null}
            </div>
          </div>

          <div className="mc-overall">
            <div className="mc-overall__bar" role="img" aria-label={`${percent}% of the job completed`}>
              <span style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
            </div>
            <div className="mc-overall__numbers">
              <span className="mc-overall__percent mono">{percent}%</span>
              <span className="mono">Stage: {activeStage ? STATE_LABELS[activeStage] ?? activeStage : 'Not reported'}</span>
              <span className="mono">Elapsed: {formatClock(progress.elapsed_seconds)}</span>
              <span className="mono">Last successful update: {lastPoll ? formatWhen(lastPoll) : 'Not yet'}</span>
            </div>
            <div className="mc-stats">
              <div><strong>{progress.total_questions}</strong><span>questions detected</span></div>
              <div><strong>{progress.completed_questions}</strong><span>completed</span></div>
              <div><strong>{progress.processing_questions}</strong><span>currently processing</span></div>
              <div><strong>{progress.review_questions}</strong><span>awaiting review</span></div>
              <div><strong>{progress.failed_questions}</strong><span>failed / blocked</span></div>
              <div><strong>{progress.pending_questions}</strong><span>pending</span></div>
            </div>
          </div>

          {progress.error_code ? (
            <div className="mc-alert" role="alert">
              <p className="mono">{progress.error_code}</p>
              <p>{progress.error_message ?? 'The engine recorded no message for this failure.'}</p>
              <p className="mono">
                {progress.retryable === null
                  ? 'The engine did not state whether a retry is allowed.'
                  : progress.retryable
                    ? 'A retry is allowed.'
                    : 'A retry is not allowed; a new job is required.'}
              </p>
            </div>
          ) : null}

          <div className="mc-columns">
            <Panel title="Pipeline stages" note="One row per stage the engine actually recorded.">
              {stageRows.length === 0 ? (
                <p className="app-hint">
                  No stage has completed yet. The engine writes a stage row when it reaches it.
                </p>
              ) : (
                <ol className="mc-stages">
                  {stageRows.map((stage, index) => (
                    <li key={`${stage.stage}-${stage.at}-${index}`} className="mc-stage" data-outcome={stage.outcome}>
                      <div>
                        <strong>{STAGE_LABELS[stage.stage] ?? stage.stage}</strong>
                        <span className="mono mc-stage__outcome">{stage.outcome}</span>
                      </div>
                      <p className="mono">{formatWhen(stage.at)}</p>
                      {stage.prompt_version ? <p className="mc-stage__prompt mono">prompt {stage.prompt_version}</p> : null}
                    </li>
                  ))}
                </ol>
              )}
            </Panel>

            <Panel title="Job state timeline" note="Persisted transitions, not a frontend timer.">
              <ol className="mc-events">
                {timeline.map((event) => (
                  <li key={event.seq} className="mc-event">
                    <span className="mc-event__dot" data-tone={toneForState(event.state)} aria-hidden="true" />
                    <div>
                      <strong>{STATE_LABELS[event.state] ?? event.state}</strong>
                      <p className="mono">
                        {formatWhen(event.at)} · {event.actor}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </Panel>
          </div>

          <Panel title="Question tracker" note={`${progress.questions.length} detected questions`}>
            {progress.questions.length === 0 ? (
              <p className="app-hint">The engine has not reported any questions yet.</p>
            ) : (
              <div className="table-scroll">
                <table className="data-table mc-questions">
                  <caption className="visually-hidden">Question-level state read from stored results</caption>
                  <thead>
                    <tr>
                      <th scope="col">Question</th>
                      <th scope="col">Status</th>
                      <th scope="col">Marks</th>
                      <th scope="col">Confidence</th>
                      <th scope="col">Verification</th>
                      <th scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {progress.questions.map((question) => (
                      <tr key={question.question_id} data-review={question.review_required ? 'true' : undefined}>
                        <th scope="row">{question.question_id}</th>
                        <td>
                          <span className="chip app-chip" data-tone={questionTone(question)}>
                            {questionLabel(question)}
                          </span>
                        </td>
                        <td className="mono">
                          {question.awarded_marks === null
                            ? '—'
                            : `${question.awarded_marks} / ${question.max_marks}`}
                        </td>
                        <td className="mono">
                          {question.confidence === null ? 'Not reported' : question.confidence.toFixed(2)}
                        </td>
                        <td>{question.verification_status ?? 'Not reported'}</td>
                        <td>
                          <Link
                            className="btn btn--small btn--outline"
                            to="/submissions/$submissionId"
                            params={{ submissionId: progress.submission_id }}
                          >
                            View
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Documents" note="Stored by the engine, not public URLs">
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">File</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Pages</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {progress.documents.map((document) => (
                    <tr key={document.id}>
                      <th scope="row">{document.filename}</th>
                      <td className="mono">{document.kind}</td>
                      <td className="mono">{document.pages}</td>
                      <td>
                        {document.status}
                        {document.error_code ? (
                          <span className="mono app-hint"> · {document.error_code}</span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </section>
      ) : null}
    </div>
  )
}
