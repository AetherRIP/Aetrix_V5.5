import { Link } from '@tanstack/react-router'
import { Icon } from '../ui/Icons'
import { MaskedLine } from './Copy'
import { SignalCanvas } from './SignalCanvas'

/**
 * The closing scene. Every motif the page has used converges here: the shader
 * field at its quietest, the lattice lines drawn inward, the mark resolving in
 * the centre. It is the same instrument seen from the other end.
 */
export function Invitation() {
  return (
    <section className="mk-invite" id="start" aria-labelledby="cta-title">
      <div className="mk-invite__field" aria-hidden="true">
        <SignalCanvas className="mk-invite__shader" intensity={0.55} />
        <svg className="mk-invite__svg" viewBox="0 0 1200 520" fill="none" focusable="false">
          {[0, 1, 2, 3, 4, 5, 6].map((index) => {
            const y = 120 + index * 46
            return (
              <g key={index}>
                <path
                  className="in-path"
                  d={`M0 ${y} C 300 ${y}, 460 300, 600 300`}
                  strokeWidth="1"
                />
                <path
                  className="in-path"
                  d={`M1200 ${y} C 900 ${y}, 740 300, 600 300`}
                  strokeWidth="1"
                />
              </g>
            )
          })}

          {[0, 1, 2, 3, 4, 5, 6].map((index) => (
            <g key={`n${index}`}>
              <circle className="in-node" cx="600" cy={120 + index * 46} r="2.6" />
            </g>
          ))}

          <circle className="in-path in-ring" cx="600" cy="300" r="58" strokeWidth="1.2" />
          <path className="in-path in-check" d="m576 300 16 16 30-34" strokeWidth="2.4" />
        </svg>
      </div>

      <div className="shell mk-invite__inner">
        <p className="mk-eyebrow mk-invite__eyebrow">
          <span className="mono">09</span>
          <span>Begin</span>
        </p>

        <h2 className="mk-invite__title" id="cta-title">
          <MaskedLine words={[{ text: 'Make' }, { text: 'every' }, { text: 'mark' }]} />{' '}
          <MaskedLine words={[{ text: 'meaningful.', accent: true }]} />
        </h2>

        <p className="mk-invite__text">
          Explore a more transparent approach to mathematical assessment — where
          every mark can name the criterion it came from and the person who
          approved it.
        </p>

        <div className="mk-invite__actions" data-reveal>
          <Link className="btn btn--primary" to="/sign-in">
            Sign in to Aetrix
            <Icon name="arrow" size={16} />
          </Link>
          <a className="btn btn--outline" href="#transformation">
            Walk the transformation again
          </a>
        </div>

        <p className="mk-invite__note">
          Pilot access is by invitation. Sign in with an invited Google account, or
          with the credentials a workspace owner issued.
        </p>
      </div>
    </section>
  )
}
