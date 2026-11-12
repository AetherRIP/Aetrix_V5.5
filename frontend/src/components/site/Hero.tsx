import { useRef } from 'react'
import { Icon } from '../ui/Icons'
import { usePointerTilt } from '../../lib/hooks'
import { HeroMarkSheet } from '../product/HeroMarkSheet'

const FACTS = [
  'Correction runs on the server',
  'A human decides every exception',
  'One workspace, one boundary',
] as const

export function Hero() {
  const stage = useRef<HTMLDivElement>(null)
  usePointerTilt(stage)

  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero__field" aria-hidden="true">
        <div className="hero__grid" />
        <div className="hero__glow hero__glow--a" />
        <div className="hero__glow hero__glow--b" />
        <div className="hero__sweep" />
        <span className="hero__cross hero__cross--tl" />
        <span className="hero__cross hero__cross--tr" />
        <span className="hero__cross hero__cross--bl" />
        <span className="hero__cross hero__cross--br" />
      </div>

      <div className="shell hero__inner">
        <div className="hero__head">
          <p className="hero__kicker">
            <span className="hero__kicker-mark" aria-hidden="true" />
            <span>Edexcel IGCSE 4MA1</span>
            <span className="hero__kicker-rule" aria-hidden="true" />
            <span>Examiner-level marking</span>
          </p>

          <h1 className="hero__title" id="hero-title">
            <span className="hero__line">Mark smarter.</span>
            <span className="hero__line">
              Trust <span className="hero__mark">every mark</span>.
            </span>
          </h1>
        </div>

        <div className="hero__body">
          <div className="hero__copy">
            <p className="hero__lede">
            AI-assisted mathematics marking, built around examiner-level
            consistency, transparent corrections and human oversight.
          </p>

          <div className="hero__actions">
            <a className="btn btn--primary" href="#workflow">
              Explore the workflow
              <Icon name="arrow" size={16} />
            </a>
            <a className="btn btn--outline" href="#platform">
              Discover the platform
            </a>
          </div>

            <ul className="hero__facts">
              {FACTS.map((fact) => (
                <li key={fact}>{fact}</li>
              ))}
            </ul>
          </div>

          <div className="hero__stage" ref={stage}>
            <HeroMarkSheet />
          </div>
        </div>
      </div>
    </section>
  )
}
