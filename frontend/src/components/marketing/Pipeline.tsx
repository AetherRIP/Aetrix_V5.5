import { useState } from 'react'
import { Icon } from '../ui/Icons'

const STEPS = [
  {
    id: 'upload',
    title: 'Upload the class set',
    text: 'Scans are added to the assignment one student at a time. Each file is validated, rendered to pages and bound to that student before anything reads it.',
    produces: 'Stored submission · rendered pages',
    status: 'Implemented',
    tone: 'ok',
  },
  {
    id: 'extract',
    title: 'Extract the questions',
    text: 'The scheme becomes a fixed question list with its official maximum marks; each answer’s working becomes a draft extraction. A teacher approves the blueprint before marking starts.',
    produces: 'Draft extraction · approved blueprint',
    status: 'Implemented',
    tone: 'ok',
  },
  {
    id: 'mark',
    title: 'Evaluate against criteria',
    text: 'A queued job prepares the script, marks it against the locked blueprint and reconciles every question. The browser never performs marking.',
    produces: 'Provisional marks',
    status: 'Implemented',
    tone: 'ok',
  },
  {
    id: 'verify',
    title: 'Verify the mathematics',
    text: 'Steps are checked symbolically where a question allows it. A step that does not verify is flagged rather than accepted.',
    produces: 'Verification flags',
    status: 'Provider unverified',
    tone: 'warn',
  },
  {
    id: 'park',
    title: 'Park what is uncertain',
    text: 'A question the engine cannot settle becomes Needs review. It is never recorded as a zero, and a mark cannot exceed its question maximum.',
    produces: 'Needs review state',
    status: 'Implemented',
    tone: 'ok',
  },
  {
    id: 'review',
    title: 'Hand it to a person',
    text: 'A teacher or assistant reviews the exceptions. An override keeps the previous value, the stated reason and the reviewer, and approvals are version-checked.',
    produces: 'Reviewed, audited marks',
    status: 'Implemented',
    tone: 'ok',
  },
  {
    id: 'report',
    title: 'Report and publish',
    text: 'Approved question marks recompute into a report. Attaching it to Google Classroom and publishing grades are separate steps that are not integrated.',
    produces: 'Structured report',
    status: 'Not integrated',
    tone: 'gap',
  },
] as const

/**
 * The workflow as an instrument panel rather than a list.
 *
 * Selecting a stage moves the signal along the rail, lights the connections up
 * to it and swaps the explanation. The same information is present in the
 * document without interaction — the selected panel is always rendered, and
 * every button carries its own label — so nothing is hidden behind a hover.
 */
export function Pipeline() {
  const [active, setActive] = useState(0)
  const step = STEPS[active]

  return (
    <section className="mk-pipeline mk-section" id="workflow" aria-labelledby="workflow-title">
      <div className="shell">
        <header className="mk-head mk-head--split" data-reveal>
          <div>
            <p className="mk-eyebrow">
              <span className="mono">05</span>
              <span>The workflow</span>
            </p>
            <h2 className="mk-h2" id="workflow-title">
              A pipeline you can inspect.
            </h2>
          </div>
          <p className="mk-note">
            Seven stages, each with a state and an output. Choose a stage to follow
            the signal: the rail shows where it enters, and the panel states what
            that stage produces — including the one that depends on a provider
            whose accuracy is not certified.
          </p>
        </header>

        <div className="pipe" data-active={active}>
          <div className="pipe__rail" role="group" aria-label="Workflow stages">
            {STEPS.map((entry, index) => (
              <button
                key={entry.id}
                type="button"
                className="pipe__stage"
                aria-pressed={index === active}
                data-tone={entry.tone}
                onClick={() => setActive(index)}
              >
                <span className="pipe__stage-index mono">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span className="pipe__stage-title">{entry.title}</span>
              </button>
            ))}
            <span className="pipe__track" aria-hidden="true">
              <i style={{ transform: `scaleX(${(active + 1) / STEPS.length})` }} />
              <span
                className="pipe__signal"
                style={{ left: `${((active + 0.5) / STEPS.length) * 100}%` }}
              />
            </span>
          </div>

          <div className="pipe__body">
            <div className="pipe__diagram" aria-hidden="true">
              <svg viewBox="0 0 560 420" fill="none" focusable="false">
                <g className="pipe__grid">
                  {[0, 1, 2, 3].map((row) => (
                    <line key={row} x1="0" x2="560" y1={60 + row * 100} y2={60 + row * 100} />
                  ))}
                  {[0, 1, 2, 3, 4].map((column) => (
                    <line key={column} y1="0" y2="420" x1={40 + column * 120} x2={40 + column * 120} />
                  ))}
                </g>

                <path className="pipe__spine" d="M60 210H500" />
                {STEPS.map((entry, index) => {
                  const x = 60 + (index / (STEPS.length - 1)) * 440
                  const lit = index <= active
                  return (
                    <g key={entry.id} data-lit={lit ? '' : undefined} data-current={index === active ? '' : undefined}>
                      <path
                        className="pipe__spoke"
                        d={`M${x} 210V${index % 2 === 0 ? 126 : 294}`}
                      />
                      <circle className="pipe__node" cx={x} cy="210" r="5" />
                      <text
                        className="pipe__node-label"
                        x={x}
                        y={index % 2 === 0 ? 110 : 322}
                        textAnchor="middle"
                      >
                        {entry.id.toUpperCase()}
                      </text>
                    </g>
                  )
                })}

                <g className="pipe__readout">
                  <text className="pipe__readout-label" x="60" y="366">output</text>
                  <text className="pipe__readout-value" x="60" y="390">{step.produces}</text>
                </g>
              </svg>
            </div>

            <div className="pipe__panel">
              <p className="pipe__status mono" data-tone={step.tone}>
                <Icon
                  name={step.tone === 'ok' ? 'check' : step.tone === 'warn' ? 'review' : 'triangle'}
                  size={12}
                />
                {step.status}
              </p>
              <h3 className="pipe__title" aria-live="polite">
                {step.title}
              </h3>
              <p className="pipe__text">{step.text}</p>
              <p className="pipe__produces mono">
                <span>Produces</span>
                {step.produces}
              </p>
              <div className="pipe__nav">
                <button
                  type="button"
                  className="pipe__step-btn"
                  onClick={() => setActive((value) => Math.max(0, value - 1))}
                  disabled={active === 0}
                >
                  <Icon name="arrow" size={14} />
                  <span>Previous</span>
                </button>
                <button
                  type="button"
                  className="pipe__step-btn"
                  onClick={() => setActive((value) => Math.min(STEPS.length - 1, value + 1))}
                  disabled={active === STEPS.length - 1}
                >
                  <span>Next</span>
                  <Icon name="arrow" size={14} />
                </button>
              </div>
            </div>
          </div>
        </div>

        <p className="mk-footnote" data-reveal>
          <span className="mono">Status</span>
          Aetrix V5.5 is a pre-release checkpoint. The live provider is unverified,
          the benchmark holdout contains no certified paper, and no
          marking-accuracy figure is claimed anywhere on this page.
        </p>
      </div>
    </section>
  )
}
