import { DEMO_DISTRIBUTION, DEMO_META } from '../../lib/demo-data'
import { vars } from '../../lib/hooks'

const WIDTH = 640
const TOP = 26
const BASELINE = 220
const AXIS_MAX = 10
const COLUMNS = DEMO_DISTRIBUTION.length

/**
 * The curve is a smooth reading of the same synthetic class set the console
 * shows. It is plotted from the demonstration distribution — no live workspace
 * is queried, and the reports surface it describes is not built yet.
 */

function pointX(index: number) {
  return ((index + 0.5) / COLUMNS) * WIDTH
}

function pointY(value: number) {
  return BASELINE - (value / AXIS_MAX) * (BASELINE - TOP)
}

const POINTS = DEMO_DISTRIBUTION.map((band, index) => ({
  band: band.band,
  count: band.count,
  x: pointX(index),
  y: pointY(band.count),
}))

const PEAK = Math.max(...POINTS.map((point) => point.count))

const LINE = POINTS.reduce((path, point, index) => {
  if (index === 0) return `M${point.x.toFixed(1)},${point.y.toFixed(1)}`
  const previous = POINTS[index - 1]
  const handle = (point.x - previous.x) / 3
  return `${path} C${(previous.x + handle).toFixed(1)},${previous.y.toFixed(1)} ${(point.x - handle).toFixed(1)},${point.y.toFixed(1)} ${point.x.toFixed(1)},${point.y.toFixed(1)}`
}, '')

const AREA = `${LINE} L${WIDTH},${BASELINE} L0,${BASELINE} Z`
const TOTAL = POINTS.reduce((sum, point) => sum + point.count, 0)

export function ScoreSignal() {
  return (
    <section className="section section--signal" id="signal" aria-labelledby="signal-title">
      <div className="shell signal">
        <div className="signal__copy" data-reveal>
          <p className="signal__kicker mono">Class reading · synthetic</p>
          <h2 className="signal__title" id="signal-title">
            One curve, every script accounted for.
          </h2>
          <p className="signal__note">
            The distribution is plotted band by band from approved question marks,
            so a teacher can see where a class is sitting before opening a single
            script. This card is drawn from the same invented class set as the
            console above; the live reports surface is not built yet.
          </p>

          <dl className="signal__readout">
            <div>
              <dt>Scripts scored</dt>
              <dd className="mono">
                {DEMO_META.marked} <span>/ {DEMO_META.submissions}</span>
              </dd>
            </div>
            <div>
              <dt>Median score</dt>
              <dd className="mono">{DEMO_META.median}%</dd>
            </div>
            <div>
              <dt>Parked for review</dt>
              <dd className="mono">{DEMO_META.needsReview}</dd>
            </div>
          </dl>
        </div>

        <figure className="signal__figure" data-reveal>
          <ScoreCurve />
          <figcaption>
            Synthetic demonstration data · {TOTAL} scored scripts from an invented
            class set of {DEMO_META.submissions}, each out of {DEMO_META.totalMarks}{' '}
            marks.
          </figcaption>
        </figure>
      </div>
    </section>
  )
}

function ScoreCurve() {
  return (
    <div className="curve">
      <svg
        viewBox={`0 0 ${WIDTH} 240`}
        role="img"
        aria-label={`Score distribution across ${TOTAL} synthetic scripts: ${POINTS.map(
          (point) => `${point.band} marks, ${point.count} scripts`,
        ).join('; ')}.`}
      >
        <defs>
          <linearGradient id="curve-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.24" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>

        </defs>

        {[0, 5, 10].map((value) => (
          <line
            key={value}
            className="curve__grid"
            data-zero={value === 0}
            x1="0"
            x2={WIDTH}
            y1={pointY(value)}
            y2={pointY(value)}
          />
        ))}

        <path className="curve__area" d={AREA} fill="url(#curve-fill)" />
        <path className="curve__glow" d={LINE} />
        <path className="curve__line" d={LINE} pathLength={1} />

        <g className="curve__scan" aria-hidden="true">
          <line
            className="curve__scan-glow"
            x1="0"
            x2="0"
            y1={TOP - 12}
            y2={BASELINE + 6}
          />
          <line
            className="curve__scan-line"
            x1="0"
            x2="0"
            y1={TOP - 12}
            y2={BASELINE + 6}
          />
        </g>

        {POINTS.map((point, index) => (
          <g key={point.band}>
            {point.count === PEAK ? (
              <circle className="curve__ring" cx={point.x} cy={point.y} r="9" />
            ) : null}
            <circle
              className="curve__dot"
              cx={point.x}
              cy={point.y}
              r="4.5"
              style={vars({ '--i': index })}
            />
          </g>
        ))}
      </svg>

      <ol className="curve__bands">
        {POINTS.map((point) => (
          <li key={point.band} className="curve__band">
            <strong className="mono">{point.count}</strong>
            <span>{point.band}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
