import { DEMO_DISTRIBUTION, DEMO_META } from '../../lib/demo-data'
import { vars } from '../../lib/hooks'

/**
 * A distribution of 29 synthetic scripts out of 30. The visual bars are hidden
 * from assistive technology; the same values are provided as a list.
 */
export function DistributionChart() {
  const total = DEMO_DISTRIBUTION.reduce((sum, band) => sum + band.count, 0)
  const max = Math.max(...DEMO_DISTRIBUTION.map((band) => band.count))
  const peak = DEMO_DISTRIBUTION.find((band) => band.count === max)?.band

  return (
    <figure className="chart">
      <figcaption className="chart__caption">
        <span className="chart__title">Score distribution</span>
        <span className="chart__meta mono">{total} marked</span>
      </figcaption>

      <div className="chart__plot" aria-hidden="true">
        {DEMO_DISTRIBUTION.map((band, index) => (
          <div className="chart__col" key={band.band} data-peak={band.band === peak}>
            <span className="chart__count mono">{band.count}</span>
            <span className="chart__track">
              <span
                className="chart__bar"
                style={vars({
                  '--h': Math.max(band.count / max, 0.04).toFixed(3),
                  '--i': index,
                })}
              />
            </span>
            <span className="chart__band mono">{band.band}</span>
          </div>
        ))}
      </div>

      <p className="sr-only">
        Score distribution out of {DEMO_META.totalMarks} marks across {total} marked
        scripts:{' '}
        {DEMO_DISTRIBUTION.map(
          (band) => `${band.band} marks, ${band.count} scripts`,
        ).join('; ')}
        .
      </p>
    </figure>
  )
}
