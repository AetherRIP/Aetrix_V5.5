import { Link } from '@tanstack/react-router'
import { Icon } from '../ui/Icons'

export function FinalCta() {
  return (
    <section className="final-cta" aria-labelledby="cta-title">
      <div className="final-cta__field" aria-hidden="true" />
      <div className="shell final-cta__inner">
        <div data-reveal>
          <h2 className="final-cta__title" id="cta-title">
            Marking that can answer for itself.
          </h2>
          <p className="final-cta__text">
            Every mark traceable to a question, a scheme and a person. That is the
            standard the rebuild is being held to.
          </p>
        </div>

        <div className="final-cta__actions" data-reveal>
          <a className="btn btn--primary" href="#workflow">
            Explore the workflow
            <Icon name="arrow" size={16} />
          </a>
          <Link className="btn btn--outline" to="/sign-in">
            Sign in
          </Link>
          <p className="final-cta__note">
            Pilot access is by invitation. Sign-in is not enabled in this build.
          </p>
        </div>
      </div>
    </section>
  )
}
