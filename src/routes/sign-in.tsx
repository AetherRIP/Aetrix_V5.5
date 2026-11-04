import { createFileRoute, Link } from '@tanstack/react-router'
import { useScrollReveal } from '../lib/hooks'
import { Icon } from '../components/ui/Icons'

export const Route = createFileRoute('/sign-in')({
  head: () => ({
    meta: [
      { title: 'Sign in — MathChecker V5.5' },
      {
        name: 'description',
        content:
          'Sign-in for MathChecker V5.5 is not enabled in this pre-release build. Pilot access is by invitation.',
      },
    ],
  }),
  component: SignIn,
})

const ACCESS_STATE = [
  { label: 'Sign-in method', value: 'Not configured' },
  { label: 'Session policy', value: 'Awaiting decision' },
  { label: 'Workspace provisioning', value: 'Not enabled' },
  { label: 'Provider credentials', value: 'Server-side only' },
] as const

function SignIn() {
  useScrollReveal()

  return (
    <div className="auth">
      <div className="shell auth__grid">
        <div className="auth__copy" data-reveal>
          <p className="auth__kicker mono">Pilot access</p>
          <h1 className="auth__title">Sign in to MathChecker</h1>
          <p className="auth__lede">
            Authentication is not enabled in this build. The public site you are
            reading is the first shipped surface; the workspace shell follows once
            the identity and session decisions are signed off.
          </p>

          <p className="auth__body">
            There is no self-serve sign-up here, and no account is created by
            anything on this page. Departments join the pilot by invitation, so
            that marking can be compared against a known set of scripts before it
            is offered more widely.
          </p>

          <div className="auth__actions">
            <Link className="btn btn--primary" to="/">
              Back to the landing page
              <Icon name="arrow" size={16} />
            </Link>
            <Link className="btn btn--outline" to="/" hash="security">
              Read the security principles
            </Link>
          </div>
        </div>

        <aside className="auth__panel" aria-labelledby="access-state-title" data-reveal>
          <h2 className="auth__panel-title" id="access-state-title">
            Access status
          </h2>
          <dl className="auth__state">
            {ACCESS_STATE.map((entry) => (
              <div key={entry.label}>
                <dt>{entry.label}</dt>
                <dd>
                  <span className="auth__dot" aria-hidden="true" />
                  {entry.value}
                </dd>
              </div>
            ))}
          </dl>
          <p className="auth__foot">
            Recorded honestly rather than simulated. A working login will be
            published when it exists.
          </p>
        </aside>
      </div>
    </div>
  )
}
