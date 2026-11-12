import { vars } from '../../lib/hooks'
import { Icon } from '../ui/Icons'

const PRINCIPLES = [
  {
    title: 'Workspace isolation',
    text: 'The workspace is read from the verified token claim, never from a request body, and every query is scoped to it in the data layer. Cross-tenant reads are enforced in application code today; a database-level constraint is still outstanding and is tracked publicly rather than claimed here.',
  },
  {
    title: 'Correction stays on the server',
    text: 'Prompts, mark schemes and provider calls never reach client JavaScript. The browser asks for a result; it never performs the marking.',
  },
  {
    title: 'No provider credentials in the browser',
    text: 'Provider keys are encrypted at rest in the Python engine and decrypted only for the duration of one outbound call. The browser never receives a key.',
  },
  {
    title: 'Overrides are auditable',
    text: 'A changed mark records the reviewer, the time, the previous value and the stated reason. Approvals are version-checked, so a second save cannot silently overwrite the first.',
  },
  {
    title: 'Questionable results are reviewed explicitly',
    text: 'A question the engine cannot mark with confidence becomes Needs review, never zero. A stored mark cannot exceed its question maximum: a database CHECK constraint enforces it as well as the handler.',
  },
] as const

const NON_CLAIMS = [
  'No SOC 2, ISO 27001 or GDPR certification is claimed. None has been obtained.',
  'No pricing is published, because plans are not finalised.',
  'No self-serve signup exists: accounts are created by invitation.',
  'No marking accuracy is certified: the benchmark holdout contains no certified paper, so no accuracy figure is claimed.',
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
