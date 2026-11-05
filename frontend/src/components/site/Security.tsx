import { vars } from '../../lib/hooks'
import { Icon } from '../ui/Icons'

const PRINCIPLES = [
  {
    title: 'Workspace isolation',
    text: 'Every query is scoped to a single workspace in the typed data layer, and the database rejects a cross-tenant reference rather than trusting the handler to remember.',
  },
  {
    title: 'Correction stays on the server',
    text: 'Prompts, mark schemes and provider calls never reach client JavaScript. The browser asks for a result; it never performs the marking.',
  },
  {
    title: 'No provider credentials in the browser',
    text: 'Provider keys are encrypted at rest and decrypted only inside the Worker for the duration of one outbound call.',
  },
  {
    title: 'Overrides are auditable',
    text: 'A changed mark records the reviewer, the time, the previous value and the stated reason. Approvals are version-checked, so a second save cannot silently overwrite the first.',
  },
  {
    title: 'Questionable results are reviewed explicitly',
    text: 'A missing question becomes Needs review, never zero. A mark cannot exceed the blueprint maximum, and that limit is enforced by the database as well as the handler.',
  },
] as const

const NON_CLAIMS = [
  'No SOC 2, ISO 27001 or GDPR certification is claimed. None has been obtained.',
  'No pricing is published, because plans are not finalised.',
  'No account can be created from this site yet.',
] as const

export function Security() {
  return (
    <section className="section section--security" id="security" aria-labelledby="security-title">
      <div className="shell security__grid">
        <div className="security__intro" data-reveal>
          <h2 className="section-head__title" id="security-title">
            Trust is a property of the design, not a badge on the page.
          </h2>
          <p className="section-head__note">
            These are the intended principles of the rebuild. They describe
            commitments the architecture is being built to hold — not
            certifications, and not a claim that every control is already
            deployed.
          </p>

          <div className="nonclaims">
            <h3 className="nonclaims__title">
              <Icon name="shield" size={16} />
              What this page does not claim
            </h3>
            <ul className="nonclaims__list">
              {NON_CLAIMS.map((claim) => (
                <li key={claim}>{claim}</li>
              ))}
            </ul>
          </div>
        </div>

        <ol className="principles">
          {PRINCIPLES.map((principle, index) => (
            <li
              key={principle.title}
              className="principle"
              data-reveal
              style={vars({ '--reveal-delay': `${index * 50}ms` })}
            >
              <span className="principle__index mono">
                {String(index + 1).padStart(2, '0')}
              </span>
              <div>
                <h3 className="principle__title">{principle.title}</h3>
                <p className="principle__text">{principle.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
