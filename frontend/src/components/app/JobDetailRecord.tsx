import type { CSSProperties, ReactNode } from 'react'
import type { JobDetail } from '../../lib/api/types'
import {
  elapsed,
  engineProvenance,
  formatClock,
  formatTime,
  jobTone,
} from '../../lib/jobs/presentation'

/**
 * The correction job as a record sheet.
 *
 * A reviewer opens this to answer one question — can I trust what this run
 * produced — so the sheet opens with the run itself: which engine marked it,
 * how far it got, and how many attempts it took. Failure, refusal and review
 * reasons follow as their own blocks rather than as rows buried in a list,
 * because those are the facts that change what a person does next.
 */
export function JobDetailRecord({ job }: { job: JobDetail }) {
  const provider = job.provider_call
  const engine = engineProvenance(job)
  const percent = Math.round(job.progress * 100)
  const fill = Math.min(1, Math.max(0, job.progress))
  const startDelay = elapsed(job.created_at, job.started_at)
  const runTime = elapsed(job.started_at, job.finished_at)
  const awaitingReview = job.state === 'REVIEW_REQUIRED' || job.review_reasons.length > 0

  return (
    <div className="rd-job">
      <section
        className="rd-job__strip"
        data-attention={jobTone(job.state) === 'attention' ? 'true' : undefined}
        aria-label="Run summary"
      >
        <div className="rd-job__stamp">
          <p className="rd-job__id mono">{job.id.slice(0, 8)}</p>
          <p className="rd-job__sid mono">submission {job.submission_id.slice(0, 8)}</p>
        </div>

        <div className="rd-job__verdict">
          <span className="chip app-chip" data-tone={jobTone(job.state)}>
            {job.state}
          </span>
          <span
            className="rd-job__engine mono"
            data-recorded={engine.recorded ? 'true' : 'false'}
            title={
              engine.recorded
                ? 'The correction engine that produced this run'
                : 'This job carries no recorded engine'
            }
          >
            {engine.label}
          </span>
        </div>

        <div className="rd-job__rail">
          <span className="rd-job__rail-value mono">{percent}%</span>
          <span
            className="rd-job__track"
            role="img"
            aria-label={`${percent}% of the pipeline completed`}
            style={{ '--fill': fill } as CSSProperties}
          >
            <span className="rd-job__track-fill" />
          </span>
          <span className="rd-job__rail-meta mono">
            attempt {job.attempts} of {job.max_attempts}
          </span>
        </div>
      </section>

      {job.error_code ? (
        <section className="rd-job__alert" aria-label="Engine error">
          <p className="rd-job__alert-code mono">{job.error_code}</p>
          <p className="rd-job__alert-text">
            {job.error_message ?? 'The engine recorded no message for this failure.'}
          </p>
          <p className="rd-job__alert-meta mono">
            {job.retryable === null
              ? 'The engine did not state whether a retry is allowed'
              : job.retryable
                ? 'A retry is allowed'
                : 'A retry is not allowed; a new job is required'}
          </p>
        </section>
      ) : null}

      {awaitingReview ? (
        <section className="rd-job__notice" aria-label="Why a person is needed">
          <h3 className="rd-job__notice-title">Why this run stopped for a person</h3>
          {job.review_reasons.length > 0 ? (
            <ul className="rd-job__reasons">
              {job.review_reasons.map((reason) => {
                // The engine writes reasons as "Question <id>: <detail>". The
                // lead is split off only to set it apart; nothing is dropped,
                // and an unrecognised shape is printed whole.
                const split = reason.indexOf(': ')
                const lead = split > 0 ? reason.slice(0, split) : null
                return (
                  <li key={reason}>
                    {lead ? (
                      <>
                        <span className="rd-job__reason-key mono">{lead}</span>
                        <span className="rd-job__reason-text">{reason.slice(split + 2)}</span>
                      </>
                    ) : (
                      <span className="rd-job__reason-text">{reason}</span>
                    )}
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="app-hint">The engine did not record a reason.</p>
          )}
        </section>
      ) : null}

      <div className="rd-job__grid">
        <section className="rd-job__group" aria-labelledby="jd-identity">
          <h3 className="rd-job__group-title" id="jd-identity">
            Identity <span className="rd-job__group-note mono">what was marked</span>
          </h3>
          <dl className="rd-job__facts">
            <Fact label="Job">
              <span className="mono rd-job__identifier">{job.id}</span>
            </Fact>
            <Fact label="Submission">
              <span className="mono rd-job__identifier">{job.submission_id}</span>
            </Fact>
            <Fact label="Assignment">
              {job.assignment_name ?? 'Not reported'}
              <span className="mono rd-job__aside"> · {job.assignment_id}</span>
            </Fact>
            <Fact label="Engine">
              {job.engine_name ? (
                <span className="mono">
                  {job.engine_name}
                  {job.engine_version ? ` · ${job.engine_version}` : ''}
                </span>
              ) : (
                <>
                  <span className="mono">Not recorded</span>
                  <span className="rd-job__aside">
                    {' '}
                    — this run has no engine attribution on record, so the engine that marked
                    it cannot be named from the job.
                  </span>
                </>
              )}
            </Fact>
            {job.requested_engine_name && job.requested_engine_name !== job.engine_name ? (
              <Fact label="Requested engine">
                <span className="mono">{job.requested_engine_name}</span>
              </Fact>
            ) : null}
            {job.recovery_of_job_id ? (
              <Fact label="Re-marks">
                <span className="mono rd-job__identifier">{job.recovery_of_job_id}</span>
              </Fact>
            ) : null}
          </dl>
        </section>

        <section className="rd-job__group" aria-labelledby="jd-run">
          <h3 className="rd-job__group-title" id="jd-run">
            Run <span className="rd-job__group-note mono">where it got to</span>
          </h3>
          <dl className="rd-job__facts">
            <Fact label="Attempts">
              <span className="mono">
                {job.attempts} of {job.max_attempts}
              </span>
            </Fact>
            <Fact label="Stage">
              {job.state}
              {job.resume_state ? ` · resumes at ${job.resume_state}` : ''}
            </Fact>
            <Fact label="Result source">
              <span className="mono">{job.result_source ?? 'Not recorded'}</span>
            </Fact>
            <Fact label="Cancellation">
              {job.cancel_requested ? 'Requested' : 'Not requested'}
            </Fact>
          </dl>
        </section>

        <section className="rd-job__group" aria-labelledby="jd-timing">
          <h3 className="rd-job__group-title" id="jd-timing">
            Timing <span className="rd-job__group-note mono">when, and how long</span>
          </h3>
          <dl className="rd-job__facts">
            <Fact label="Created">
              {formatTime(job.created_at)}
              {startDelay ? (
                <span className="rd-job__delta mono">waiting {startDelay}</span>
              ) : null}
            </Fact>
            <Fact label="Started">{formatTime(job.started_at)}</Fact>
            <Fact label="Finished">
              {formatTime(job.finished_at)}
              {runTime ? <span className="rd-job__delta mono">ran {runTime}</span> : null}
            </Fact>
            <Fact label="Last updated">{formatTime(job.updated_at)}</Fact>
          </dl>
        </section>

        <section className="rd-job__group" aria-labelledby="jd-provider">
          <h3 className="rd-job__group-title" id="jd-provider">
            Provider <span className="rd-job__group-note mono">last recorded call</span>
          </h3>
          <dl className="rd-job__facts">
            <Fact label="Model">
              {provider ? (
                <span className="mono">
                  {provider.provider} / {provider.model}
                </span>
              ) : (
                'No provider call recorded'
              )}
            </Fact>
            <Fact label="Outcome">
              {provider
                ? `${provider.success ? 'Succeeded' : 'Failed'}${
                    provider.http_status ? ` · HTTP ${provider.http_status}` : ''
                  }`
                : 'Not recorded'}
            </Fact>
            <Fact label="Purpose">
              <span className="mono">{provider ? provider.purpose : 'Not recorded'}</span>
            </Fact>
            <Fact label="Latency">
              <span className="mono">
                {provider?.latency_ms != null ? `${provider.latency_ms} ms` : 'Not recorded'}
              </span>
            </Fact>
            <Fact label="Tokens">
              <span className="mono">
                {provider?.input_tokens != null || provider?.output_tokens != null
                  ? `${provider?.input_tokens ?? '—'} in · ${provider?.output_tokens ?? '—'} out`
                  : 'Not recorded'}
              </span>
            </Fact>
            <Fact label="Recorded">
              {provider ? formatTime(provider.created_at) : 'Not recorded'}
            </Fact>
            {provider?.error_class ? (
              <Fact label="Provider error">
                <span className="mono">{provider.error_class}</span>
                {provider.provider_message ? (
                  <span className="rd-job__aside"> {provider.provider_message}</span>
                ) : null}
              </Fact>
            ) : null}
          </dl>
        </section>

        <section
          className="rd-job__group rd-job__group--wide"
          aria-labelledby="jd-submission"
        >
          <h3 className="rd-job__group-title" id="jd-submission">
            Submission record
          </h3>
          {job.submission ? (
            <dl className="rd-job__facts rd-job__facts--row">
              <Fact label="Student reference">{job.submission.student_ref}</Fact>
              <Fact label="Status">
                <span className="mono">{job.submission.status}</span>
              </Fact>
              <div className="rd-job__fact rd-job__fact--wide">
                <dt>Content hash</dt>
                <dd>
                  <span className="mono rd-job__identifier">{job.submission.content_hash}</span>
                </dd>
              </div>
            </dl>
          ) : (
            <p className="app-hint">No authorised submission record was returned for this job.</p>
          )}
        </section>
      </div>

      <section className="rd-job__block" aria-labelledby="jd-documents">
        <h3 className="rd-job__group-title" id="jd-documents">
          Documents <span className="rd-job__group-note mono">{job.documents.length}</span>
        </h3>
        {job.documents.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Documents attached to the submission</caption>
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Pages</th>
                  <th scope="col">Status</th>
                  <th scope="col">Ordering</th>
                  <th scope="col">Mapping</th>
                </tr>
              </thead>
              <tbody>
                {job.documents.map((document) => (
                  <tr key={document.id}>
                    <td className="data-table__strong">
                      {document.original_filename || 'Unnamed document'}
                    </td>
                    <td className="mono">{document.kind}</td>
                    <td className="mono">{document.page_count}</td>
                    <td className="mono">{document.status}</td>
                    <td className="mono">{document.ordering_status}</td>
                    <td className="mono">{document.mapping_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="app-hint">No document is recorded for this submission.</p>
        )}
      </section>

      <section className="rd-job__block" aria-labelledby="jd-decisions">
        <h3 className="rd-job__group-title" id="jd-decisions">
          Review decisions <span className="rd-job__group-note mono">{job.review_decisions.length}</span>
        </h3>
        {job.review_decisions.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Review decisions recorded for this job</caption>
              <thead>
                <tr>
                  <th scope="col">Question</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Decided</th>
                </tr>
              </thead>
              <tbody>
                {job.review_decisions.map((decision) => (
                  <tr key={`${decision.question_id}-${decision.created_at}`}>
                    <td className="mono">{decision.question_id}</td>
                    <td>{decision.requested_reason}</td>
                    <td className="mono">{decision.mode}</td>
                    <td className="mono">{decision.outcome ?? 'Pending'}</td>
                    <td className="mono">
                      {decision.decided_by
                        ? `${decision.decided_by} · ${formatTime(decision.decided_at)}`
                        : 'Not decided'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="app-hint">No review decision has been recorded.</p>
        )}
      </section>

      <section className="rd-job__block" aria-labelledby="jd-history">
        <h3 className="rd-job__group-title" id="jd-history">
          Run history{' '}
          <span className="rd-job__group-note mono">
            {job.events.length} transition{job.events.length === 1 ? '' : 's'}
          </span>
        </h3>
        {job.events.length > 0 ? (
          <ol className="rd-job__events">
            {job.events.map((event, index) => {
              const previous = index > 0 ? job.events[index - 1] : null
              const gap = previous ? elapsed(previous.created_at, event.created_at) : null
              return (
                <li className="rd-job__event" key={event.id}>
                  <span className="rd-job__event-node mono" aria-hidden="true">
                    {event.event_seq}
                  </span>
                  <span className="rd-job__event-body">
                    <span className="rd-job__event-states mono">
                      <span className="rd-job__event-from">{event.from_state ?? '—'}</span>
                      <span aria-hidden="true"> → </span>
                      <span className="rd-job__event-to">{event.to_state}</span>
                    </span>
                    <span className="rd-job__event-meta">
                      <span>{event.actor}</span>
                      {gap ? <span className="mono">+{gap}</span> : null}
                    </span>
                  </span>
                  <time className="rd-job__event-time mono" dateTime={event.created_at}>
                    {formatClock(event.created_at)}
                  </time>
                </li>
              )
            })}
          </ol>
        ) : (
          <p className="app-hint">No transitions recorded for this job.</p>
        )}
      </section>
    </div>
  )
}

function Fact({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="rd-job__fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}
