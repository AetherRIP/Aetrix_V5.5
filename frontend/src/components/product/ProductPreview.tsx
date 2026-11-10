import { useRef, useState } from 'react'
import {
  DEMO_ACTIVITY,
  DEMO_JOBS,
  DEMO_META,
  DEMO_QUESTIONS,
  DEMO_REVIEWS,
} from '../../lib/demo-data'
import { vars } from '../../lib/hooks'
import { Icon } from '../ui/Icons'
import { DistributionChart } from './DistributionChart'
import { Skeleton, StatusChip } from './StatusChip'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'marking', label: 'Marking' },
  { id: 'results', label: 'Results' },
] as const

type TabId = (typeof TABS)[number]['id']

/**
 * The marketing preview of the marking console. It is a designed
 * representation driven by synthetic data — not a screenshot of a running
 * backend, and not a claim that the pipeline is live.
 */
export function ProductPreview() {
  const [tab, setTab] = useState<TabId>('overview')
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const current = TABS.findIndex((entry) => entry.id === tab)
    let next = current
    if (event.key === 'ArrowRight') next = (current + 1) % TABS.length
    else if (event.key === 'ArrowLeft') next = (current - 1 + TABS.length) % TABS.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = TABS.length - 1
    else return
    event.preventDefault()
    setTab(TABS[next].id)
    tabRefs.current[next]?.focus()
  }

  return (
    <div className="console" data-reveal>
      <div className="console__chrome">
        <p className="console__crumb mono">
          <span className="console__dot" aria-hidden="true" />
          workspace / assignments / homework 6
        </p>
        <span className="demo-tag" title="Every figure in this preview is invented for illustration">
          Synthetic demonstration data
        </span>
      </div>

      <div className="console__head">
        <div className="console__identity">
          <h3 className="console__title">
            {DEMO_META.assignment} — {DEMO_META.paper}
          </h3>
          <p className="console__sub mono">
            {DEMO_META.submissions} submissions · {DEMO_META.className} ·{' '}
            {DEMO_META.scheme}
          </p>
        </div>
        <div className="console__states">
          <StatusChip status="marking" />
          <StatusChip status="review" />
        </div>
      </div>

      <div
        className="console__tabs"
        role="tablist"
        aria-label="Product preview views"
        onKeyDown={onKeyDown}
      >
        {TABS.map((entry, index) => (
          <button
            key={entry.id}
            ref={(node) => {
              tabRefs.current[index] = node
            }}
            type="button"
            role="tab"
            id={`preview-tab-${entry.id}`}
            aria-selected={tab === entry.id}
            aria-controls={`preview-panel-${entry.id}`}
            tabIndex={tab === entry.id ? 0 : -1}
            className="console__tab"
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="console__body">
        {TABS.map((entry) => (
          <div
            key={entry.id}
            id={`preview-panel-${entry.id}`}
            role="tabpanel"
            aria-labelledby={`preview-tab-${entry.id}`}
            hidden={tab !== entry.id}
            tabIndex={0}
            className="console__panel"
          >
            {entry.id === 'overview' ? <OverviewPanel /> : null}
            {entry.id === 'marking' ? <MarkingPanel /> : null}
            {entry.id === 'results' ? <ResultsPanel /> : null}
          </div>
        ))}
      </div>

      <p className="console__foot mono">
        <Icon name="eye" size={12} />
        Synthetic demonstration data. No live workspace is shown.
      </p>
    </div>
  )
}

function Stat({
  label,
  value,
  of,
  suffix,
  note,
  meter,
}: {
  label: string
  value: number
  of?: number
  suffix?: string
  note?: string
  meter?: number
}) {
  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <p className="stat__value mono">
        {value}
        {of === undefined ? null : <span className="stat__of">/{of}</span>}
        {suffix === undefined ? null : <span className="stat__of">{suffix}</span>}
      </p>
      {meter === undefined ? (
        <span className="stat__note">{note}</span>
      ) : (
        <span className="stat__meter" aria-hidden="true">
          <i style={vars({ '--w': meter })} />
        </span>
      )}
    </div>
  )
}

function OverviewPanel() {
  return (
    <>
      <div className="stat-grid">
        <Stat
          label="Submitted"
          value={DEMO_META.submitted}
          of={DEMO_META.submissions}
          meter={DEMO_META.submitted / DEMO_META.submissions}
        />
        <Stat
          label="Marked"
          value={DEMO_META.marked}
          of={DEMO_META.submitted}
          meter={DEMO_META.marked / DEMO_META.submitted}
        />
        <Stat label="Needs review" value={DEMO_META.needsReview} note="2 assigned to you" />
        <Stat label="Median score" value={DEMO_META.median} suffix="%" meter={0.78} />
      </div>

      <div className="overview-grid">
        <div className="panel-block panel-block--chart">
          <DistributionChart />
        </div>

        <div className="panel-block">
          <h4 className="panel-label">Review queue</h4>
          <ul className="review-list">
            {DEMO_REVIEWS.map((review) => (
              <li key={review.id}>
                <span className="review-list__q mono">{review.question}</span>
                <span className="review-list__who">{review.student}</span>
                <span className="review-list__note">{review.note}</span>
                <StatusChip status="review" size="sm" />
              </li>
            ))}
          </ul>
        </div>

        <div className="panel-block panel-block--wide">
          <h4 className="panel-label">Marking activity</h4>
          <ul className="activity-list">
            {DEMO_ACTIVITY.map((item) => (
              <li key={`${item.time}-${item.text}`}>
                <span className="mono activity-list__time">{item.time}</span>
                <span className="activity-list__text">{item.text}</span>
                <span className="activity-list__state">
                  <StatusChip status={item.state} size="sm" />
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  )
}

function MarkingPanel() {
  return (
    <>
      <div className="panel-block">
        <div className="panel-label-row">
          <h4 className="panel-label">Correction jobs</h4>
          <span className="mono panel-hint">staged progress · polling</span>
        </div>
        <ul className="job-list">
          {DEMO_JOBS.map((job) => (
            <li key={job.id} className="job" data-state={job.state}>
              <span className="job__id mono">{job.id}</span>
              <span className="job__student">{job.student}</span>
              <span className="job__progress">
                {job.state === 'queued' ? (
                  <Skeleton width="100%" />
                ) : (
                  <span className="meter" aria-hidden="true">
                    <i style={vars({ '--w': job.progress })} />
                  </span>
                )}
              </span>
              <span className="job__detail mono">{job.detail}</span>
              <StatusChip status={job.state} size="sm" />
            </li>
          ))}
        </ul>
      </div>

      <p className="panel-note">
        Queued scripts show a skeleton until the server has something to report.
        A missing question becomes <strong>Needs review</strong> — never a silent
        zero.
      </p>
    </>
  )
}

function ResultsPanel() {
  return (
    <>
      <div className="panel-block">
        <div className="panel-label-row">
          <h4 className="panel-label">Question-level results</h4>
          <span className="mono panel-hint">SUB-0416 · D. Haddad</span>
        </div>

        <div className="table-scroll">
          <table className="results-table">
            <caption className="sr-only">
              Synthetic question-level marks for one submission, with the class
              mean and each question&rsquo;s review state.
            </caption>
            <thead>
              <tr>
                <th scope="col">Q</th>
                <th scope="col" className="col-topic">Topic</th>
                <th scope="col" className="num">Max</th>
                <th scope="col" className="num">Awarded</th>
                <th scope="col" className="num col-mean">Class mean</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {DEMO_QUESTIONS.map((question) => (
                <tr key={question.code} data-state={question.status}>
                  <th scope="row" className="mono">
                    {question.code}
                  </th>
                  <td className="col-topic">{question.topic}</td>
                  <td className="num mono">{question.max}</td>
                  <td className="num mono">
                    {question.awarded === null ? (
                      <Skeleton width="20px" />
                    ) : (
                      question.awarded
                    )}
                  </td>
                  <td className="num mono col-mean">{question.mean.toFixed(1)}</td>
                  <td>
                    <StatusChip status={question.status} size="sm" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="panel-note">
        An override keeps the original mark beside the replacement and records who
        changed it, when, and why. Totals are recomputed from the question set.
      </p>
    </>
  )
}
