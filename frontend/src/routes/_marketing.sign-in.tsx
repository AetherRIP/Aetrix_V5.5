import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { peekNextPath, useAuth } from '../lib/auth/AuthProvider'
import { isOpenAccessBuild } from '../lib/env'
import { useScrollReveal } from '../lib/hooks'
import { AmbientField } from '../components/site/AmbientField'
import { HandshakeTrace } from '../components/site/HandshakeTrace'
import { Icon } from '../components/ui/Icons'
import { LEGAL_DOCUMENTS } from '../lib/legal'

export const Route = createFileRoute('/_marketing/sign-in')({
  head: () => ({
    meta: [
      { title: 'Sign in — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'Sign in to the Aetrix marking workspace with your Google account. Accounts are provisioned by invitation.',
      },
    ],
  }),
  component: SignIn,
})

function GoogleGlyph() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M12 11v2.8h4a4 4 0 0 1-1.7 2.6v2.1h2.7c1.6-1.5 2.5-3.6 2.5-6.2 0-.6 0-1.1-.1-1.6H12Z"
        opacity="0.9"
      />
      <path
        fill="currentColor"
        d="M12 20c2.2 0 4-.7 5.4-2l-2.7-2.1c-.7.5-1.7.8-2.7.8-2.1 0-3.9-1.4-4.5-3.4H4.7v2.2A8 8 0 0 0 12 20Z"
        opacity="0.62"
      />
      <path
        fill="currentColor"
        d="M7.5 13.3a5 5 0 0 1 0-3.1V8H4.7a8 8 0 0 0 0 7.4l2.8-2.1Z"
        opacity="0.45"
      />
      <path
        fill="currentColor"
        d="M12 7.3c1.2 0 2.3.4 3.1 1.2l2.3-2.3A8 8 0 0 0 4.7 8l2.8 2.2c.6-2 2.4-3.4 4.5-3.4Z"
        opacity="0.78"
      />
    </svg>
  )
}

function SignIn() {
  const {
    status,
    error,
    authUnavailableReason,
    signInWithGoogle,
    signInWithPassword,
    dismissError,
  } = useAuth()
  // The destination a protected route recorded before redirecting here. It is
  // only cleared once the callback has actually forwarded the user.
  const [next] = useState(() => peekNextPath())
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [formBusy, setFormBusy] = useState(false)
  const passwordInput = useRef<HTMLInputElement>(null)
  useScrollReveal()

  useEffect(() => {
    if (status === 'authenticated' && typeof window !== 'undefined') {
      window.location.replace(next)
    }
  }, [status, next])

  const canAuthenticate = status !== 'unconfigured'

  async function startGoogle() {
    setBusy(true)
    setFormError(null)
    await signInWithGoogle(next)
    // The browser navigates to Google when the request succeeds.
    setBusy(false)
  }

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    if (!email.trim() || password.length === 0) {
      setFormError('Enter both an email address and a password.')
      return
    }
    setFormBusy(true)
    const result = await signInWithPassword(email.trim(), password)
    setFormBusy(false)
    if (!result.ok) {
      setFormError(result.message ?? 'Sign-in failed.')
      passwordInput.current?.focus()
    }
  }

  return (
    <div className="landscape">
      <AmbientField />

      <div className="auth">
        <div className="shell auth__inner">
          <div className="auth__head">
            <div className="auth__copy">
              <p className="auth__kicker mono">
                {isOpenAccessBuild ? 'Pilot access · open sign-in' : 'Pilot access · by invitation'}
              </p>
              <h1 className="auth__title">Sign in to Aetrix</h1>
              <p className="auth__lede">
                Authentication is live. Sign in with a Google account. Sessions
                persist across refreshes and refresh themselves while you work.
              </p>

              {authUnavailableReason ? (
                <p className="auth__alert" role="alert">
                  <Icon name="review" size={16} />
                  <span>{authUnavailableReason}</span>
                </p>
              ) : null}

              {error ? (
                <div className="auth__alert" role="alert">
                  <Icon name="review" size={16} />
                  <span>{error}</span>
                  <button
                    type="button"
                    className="auth__dismiss"
                    onClick={dismissError}
                  >
                    Dismiss
                  </button>
                </div>
              ) : null}

              {status === 'authenticated' ? (
                <p className="auth__alert" data-tone="ok" role="status">
                  <Icon name="check" size={16} />
                  <span>Signed in. Opening your workspace…</span>
                </p>
              ) : null}

              <p className="auth__legal-notice">
                By signing in you agree to the{' '}
                <Link to={LEGAL_DOCUMENTS.terms.path}>Terms of Service</Link> and
                acknowledge the <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link>,{' '}
                <Link to={LEGAL_DOCUMENTS.cookies.path}>Cookie Policy</Link> and{' '}
                <Link to={LEGAL_DOCUMENTS['ai-disclosure'].path}>AI Use Disclosure</Link>. If
                this account has not accepted their current versions, you will be asked once
                after signing in, and the acceptance is stored against your account.
              </p>

              <div className="auth__actions">
                <button
                  type="button"
                  className="btn btn--primary auth__google"
                  onClick={() => void startGoogle()}
                  disabled={!canAuthenticate || busy || status === 'authenticated'}
                >
                  <GoogleGlyph />
                  {busy ? 'Opening Google…' : 'Continue with Google'}
                </button>
                <Link className="btn btn--outline" to="/" hash="security">
                  Read the security principles
                </Link>
              </div>

              <details className="auth__alt">
                <summary>Use an email and password instead</summary>
                <form
                  className="auth__form"
                  onSubmit={submitPassword}
                  method="post"
                  action="/sign-in"
                  noValidate
                >
                  <label className="auth__field">
                    <span>Email address</span>
                    <input
                      type="email"
                      name="email"
                      autoComplete="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      disabled={!canAuthenticate || formBusy}
                      required
                    />
                  </label>
                  <label className="auth__field">
                    <span>Password</span>
                    <input
                      ref={passwordInput}
                      type="password"
                      name="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      disabled={!canAuthenticate || formBusy}
                      required
                    />
                  </label>
                  {formError ? (
                    <p className="auth__field-error" role="alert">
                      {formError}
                    </p>
                  ) : null}
                  <button
                    type="submit"
                    className="btn btn--outline btn--small"
                    disabled={!canAuthenticate || formBusy}
                  >
                    {formBusy ? 'Signing in…' : 'Sign in'}
                  </button>
                  <p className="auth__hint">
                    Email accounts must be confirmed before their first sign-in; new
                    accounts are still created by an administrator.
                  </p>
                </form>
              </details>
            </div>

            <aside
              id="access"
              className="auth__panel"
              aria-labelledby="access-state-title"
            >
              <h2 className="auth__panel-title" id="access-state-title">
                Access status
              </h2>
              <dl className="auth__state">
                <div>
                  <dt>Sign-in method</dt>
                  <dd>
                    <span className="auth__dot" aria-hidden="true" />
                    Google OAuth · enabled
                  </dd>
                </div>
                <div>
                  <dt>Email and password</dt>
                  <dd>
                    <span className="auth__dot" aria-hidden="true" />
                    Enabled · confirmed accounts
                  </dd>
                </div>
                <div>
                  <dt>Session policy</dt>
                  <dd>
                    <span className="auth__dot" aria-hidden="true" />
                    PKCE · persistent · auto-refresh
                  </dd>
                </div>
                <div>
                  <dt>Workspace provisioning</dt>
                  <dd>
                    <span className="auth__dot" aria-hidden="true" />
                    {isOpenAccessBuild
                      ? 'Automatic · shared pilot workspace'
                      : 'Invitation required'}
                  </dd>
                </div>
                <div>
                  <dt>Provider credentials</dt>
                  <dd>
                    <span className="auth__dot" aria-hidden="true" />
                    Browser publishable key only
                  </dd>
                </div>
              </dl>
            </aside>
          </div>

          <HandshakeTrace />

          <div className="auth__lower" data-reveal>
            <div>
              <h2 className="auth__notes-title">Entry rules</h2>
              <p>
                There is no separate sign-up form: the engine, not this page, decides
                workspace access.{' '}
                {isOpenAccessBuild
                  ? 'This deployment admits any account Google has authenticated to one shared pilot workspace, and records the membership on the first request.'
                  : 'This deployment admits an address only through an invitation, or through the one-time acceptance code issued with it.'}
              </p>
            </div>
            <div>
              <h2 className="auth__notes-title">Where authority lives</h2>
              <p>
                Roles and workspace membership are enforced by the engine, never by
                this page. Session state is read from Supabase; nothing here is
                simulated.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
