import { useEffect, useState } from 'react'
import { Icon } from '../ui/Icons'

const NODES = [
  {
    id: 'working',
    label: 'Student working',
    detail:
      'The answer as the student wrote it: every line of working is kept as the record the mark was awarded against, not summarised away.',
    tone: 'plain',
  },
  {
    id: 'reasoning',
    label: 'Mathematical reasoning',
    detail:
      'The interpretation of that working — the expressions and the steps between them that the engine reasoned over.',
    tone: 'plain',
  },
  {
    id: 'criteria',
    label: 'Marking criteria',
    detail:
      'The criterion from the locked blueprint that each mark belongs to, with the question maximum that bounds it.',
    tone: 'plain',
  },
  {
    id: 'verification',
    label: 'Verification state',
    detail:
      'Whether the step verified symbolically. Verification is recorded as a result, not assumed: a failed check becomes a flag.',
    tone: 'ok',
  },
  {
    id: 'review',
    label: 'Review state',
    detail:
      'Whether a person has reviewed the question, who they were, and what changed. Overrides keep the previous value beside the new one.',
    tone: 'ok',
  },
  {
    id: 'tenant',
    label: 'Workspace boundary',
    detail:
      'The workspace is read from the verified token claim, never from the request body. A cross-tenant read looks like it does not exist.',
    tone: 'plain',
  },
] as const

const NON_CLAIMS = [
  'No SOC 2, ISO 27001 or GDPR certification is claimed. None has been obtained.',
  'No pricing is published, because plans are not finalised.',
  'No self-serve signup exists: accounts are created by invitation.',
  'No marking accuracy is certified. The benchmark holdout contains no certified paper.',
] as const

/**
 * Chapter seven: the evidence trail.
 *
 * A result sits at the centre and every claim it makes is a node around it.
 * Selecting a node highlights the path it travels into the result and states
 * what that node actually contains. Nothing here is decorative: the six nodes
 * are the six things a mark has to be able to answer for.
 */
export function Evidence() {
  const [active, setActive] = useState<string>('verification')
  const node = NODES.find((entry) => entry.id === active) ?? NODES[0]

  /*
   * While the section is pinned, scroll walks the trail: each sixth of the
   * pinned range selects the next node. Clicking a node still works and simply
   * wins until the next scroll, so the two inputs never fight.
   */
  useEffect(() => {
    const onWalk = (event: Event) => {
      const detail = (event as CustomEvent<{ index: number }>).detail
      if (!detail) return
      const next = NODES[Math.min(NODES.length - 1, Math.max(0, detail.index))]
      if (next) setActive(next.id)
    }
    window.addEventListener('aetrix:evidence-node', onWalk)
    return () => window.removeEventListener('aetrix:evidence-node', onWalk)
  }, [])

  return (
    <section className="mk-evidence mk-section" id="security" aria-labelledby="security-title">
      <div className="shell">
        <header className="mk-head mk-head--split" data-reveal>
          <div>
            <p className="mk-eyebrow">
              <span className="mono">07</span>
              <span>Transparency</span>
            </p>
            <h2 className="mk-h2" id="security-title">
              A result you can take apart.
            </h2>
          </div>
          <p className="mk-note">
            Trust is not a badge on the page; it is what happens when someone asks
            why. Select a node to see what the result is actually attached to, and
            read the claims this build does not make.
          </p>
        </header>

        <div className="ev">
          <div className="ev__map">
            <svg className="ev__svg" viewBox="0 0 680 560" fill="none" aria-hidden="true">
              <g className="ev-grid">
                {[0, 1, 2, 3, 4].map((row) => (
                  <line key={row} x1="0" x2="680" y1={70 + row * 100} y2={70 + row * 100} />
                ))}
                {[0, 1, 2, 3, 4, 5].map((column) => (
                  <line key={column} y1="30" y2="530" x1={60 + column * 112} x2={60 + column * 112} />
                ))}
              </g>

              <circle className="ev__orbit" cx="340" cy="280" r="196" />
              <circle className="ev__orbit ev__orbit--inner" cx="340" cy="280" r="132" />

              {NODES.map((entry, index) => {
                const angle = (-90 + index * 60) * (Math.PI / 180)
                const x = 340 + Math.cos(angle) * 196
                const y = 280 + Math.sin(angle) * 196
                const lit = entry.id === active
                return (
                  <g key={entry.id} className="ev__link" data-active={lit ? '' : undefined}>
                    <path d={`M340 280 L${x.toFixed(1)} ${y.toFixed(1)}`} />
                    <circle className="ev__node" cx={x.toFixed(1)} cy={y.toFixed(1)} r={lit ? 7 : 4.5} />
                  </g>
                )
              })}

              <g className="ev__core">
                <rect x="272" y="248" width="136" height="64" rx="1" />
                <text className="ev__core-label" x="340" y="276" textAnchor="middle">
                  result
                </text>
                <text className="ev__core-value" x="340" y="298" textAnchor="middle">
                  {node.id === 'criteria' ? '14 / 20' : 'traceable'}
                </text>
              </g>
            </svg>

            <ul className="ev__nodes" aria-label="Evidence trail">
              {NODES.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    className="ev__node-btn mono"
                    aria-pressed={entry.id === active}
                    data-tone={entry.tone}
                    onClick={() => setActive(entry.id)}
                  >
                    <span className="ev__node-dot" aria-hidden="true" />
                    {entry.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="ev__panel">
            <p className="ev__panel-code mono" aria-live="polite">
              node {String(NODES.indexOf(node) + 1).padStart(2, '0')} · {node.tone === 'ok' ? 'verified state' : 'record'}
            </p>
            <h3 className="ev__panel-title">{node.label}</h3>
            <p className="ev__panel-text">{node.detail}</p>

            <ul className="ev__principles">
              <li>
                <Icon name="lock" size={13} />
                <span>
                  The workspace is read from the verified token claim in
                  <span className="mono"> deps.py</span>, never from a request body.
                </span>
              </li>
              <li>
                <Icon name="server" size={13} />
                <span>
                  Prompts, schemes and provider calls stay on the server; provider
                  keys are encrypted at rest and never reach the browser.
                </span>
              </li>
              <li>
                <Icon name="review" size={13} />
                <span>
                  A question the engine cannot settle becomes Needs review, never a
                  silent zero, and a mark cannot exceed its question maximum.
                </span>
              </li>
            </ul>

            <div className="ev__nonclaims">
              <h4 className="mono">What this page does not claim</h4>
              <ul>
                {NON_CLAIMS.map((claim) => (
                  <li key={claim}>{claim}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
