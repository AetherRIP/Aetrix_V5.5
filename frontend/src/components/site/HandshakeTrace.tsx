import { vars } from '../../lib/hooks'

/**
 * The four steps the sign-in exchange actually performs, in order. Every line
 * describes work the code really does — the PKCE challenge created in
 * `AuthProvider`, the Google consent screen, the one-time code exchanged at
 * `/auth/callback`, and the per-request token check in the engine. Nothing here
 * is a metric and nothing is simulated state.
 */
const STEPS = [
  {
    title: 'Challenge made here',
    note: 'The browser creates the PKCE verifier and its S256 challenge before anything leaves the page.',
  },
  {
    title: 'Google asks who you are',
    note: 'Consent is scoped to the account your department registered for the pilot.',
  },
  {
    title: 'Code becomes a session',
    note: 'The callback swaps a single-use code for a session. The code is spent the moment it arrives.',
  },
  {
    title: 'Every request re-checked',
    note: 'The engine verifies the token and reads the workspace from its claim, not from the request body.',
  },
] as const

export function HandshakeTrace() {
  return (
    <section className="trace" aria-labelledby="trace-title" data-reveal>
      <div className="trace__head">
        <h2 className="trace__title" id="trace-title">
          What happens after you press it
        </h2>
        <p className="trace__meta mono">PKCE · S256 · single-use code</p>
      </div>

      <div className="trace__plot">
        <span className="trace__sweep" aria-hidden="true">
          <i />
        </span>
        <ol className="trace__list">
          {STEPS.map((step, index) => (
            <li
              key={step.title}
              className="trace__node"
              style={vars({ '--i': index })}
            >
              <span className="trace__index mono">
                {String(index + 1).padStart(2, '0')}
              </span>
              <h3 className="trace__term">{step.title}</h3>
              <p className="trace__note">{step.note}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
