import { HERO_ROWS } from '../../lib/demo-data'
import { vars } from '../../lib/hooks'
import { Icon } from '../ui/Icons'
import { Skeleton, StatusChip } from './StatusChip'
import { Sparkline } from './Sparkline'

/**
 * The hero's product surface: one submission's question ledger, with marks,
 * a review exception and a queued question. Every value is synthetic.
 */
export function HeroMarkSheet() {
  return (
    <div className="stage">
      <div className="stage__sheet">
        <span className="sheet__scan" aria-hidden="true" />
        <header className="sheet__head">
          <div>
            <p className="sheet__kicker mono">igcse 4ma1 · algebra ii</p>
            <h2 className="sheet__title">Homework 6</h2>
          </div>
          <StatusChip status="marking" />
        </header>

        <div className="sheet__progress">
          <span className="meter" aria-hidden="true">
            <i style={vars({ '--w': 34 / 48 })} />
          </span>
          <p className="mono">34 / 48 submitted</p>
        </div>

        <ol className="sheet__rows">
          {HERO_ROWS.map((row, index) => (
            <li
              key={row.code}
              className="sheet__row"
              data-state={row.status}
              style={vars({ '--i': index })}
            >
              <span className="sheet__code mono">{row.code}</span>
              <span className="sheet__stem">{row.topic}</span>
              <span className="sheet__bar" aria-hidden="true">
                <i
                  style={vars({
                    '--w': row.awarded === null ? 0 : row.awarded / row.max,
                  })}
                />
              </span>
              <span className="sheet__marks mono">
                {row.awarded === null ? (
                  <Skeleton width="30px" />
                ) : (
                  <>
                    <strong>{row.awarded}</strong>
                    <span>/{row.max}</span>
                  </>
                )}
              </span>
              <StatusChip status={row.status} size="sm" />
            </li>
          ))}
        </ol>

        <footer className="sheet__foot">
          <p className="mono">14 / 16 awarded</p>
          <p className="sheet__note">1 needs review · 1 queued</p>
        </footer>
      </div>

      <div className="stage__float stage__float--job">
        <p className="float__label">
          <Icon name="pulse" size={12} /> Correction job
        </p>
        <p className="float__value mono">3f2a…c19</p>
        <p className="float__meta">
          <Icon name="check" size={11} /> Verification passed · 4m 12s
        </p>
      </div>

      <div className="stage__float stage__float--score">
        <p className="float__label">Class median</p>
        <div className="float__score-row">
          <p className="float__score mono">78<span>%</span></p>
          <Sparkline
            points={[42, 51, 47, 63, 58, 71, 68, 78]}
            label="Median score trend across the last eight assignments, rising from 42 to 78 percent"
          />
        </div>
        <p className="float__meta">29 of 34 scripts marked</p>
      </div>
    </div>
  )
}
