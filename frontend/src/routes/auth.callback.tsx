import { useEffect, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { takeNextPath, useAuth } from '../lib/auth/AuthProvider'
import { clearAddingAccount } from '../lib/auth/accounts'
import { Icon } from '../components/ui/Icons'

export const Route = createFileRoute('/auth/callback')({
  head: () => ({
    meta: [
      { title: 'Completing sign-in — Aetrix V5.5' },
      { name: 'robots', content: 'noindex' },
    ],
  }),
  component: AuthCallback,
})

/**
 * Landing point for the OAuth round-trip. The Supabase client exchanges the
 * PKCE code and stores the session; this screen waits for that session and then
 * forwards the user to the page they originally asked for.
 */
function AuthCallback() {
  const { status, error, addingAccount } = useAuth()
  const [waited, setWaited] = useState(false)

  // When the round-trip is adding a second account, the previous session is
  // still stored, so the first `authenticated` is not the new account. Wait for
  // the exchange to finish — but never indefinitely: a round-trip that produces
  // no new session returns the user to where they were, and drops the intent so
  // a later landing on this screen is not read as an add still pending.
  useEffect(() => {
    if (status !== 'authenticated' || !addingAccount) return
    const timer = window.setTimeout(() => {
      clearAddingAccount()
      setWaited(true)
    }, 15_000)
    return () => window.clearTimeout(timer)
  }, [status, addingAccount])

  useEffect(() => {
    if (status === 'authenticated' && (!addingAccount || waited)) {
      window.location.replace(takeNextPath())
    }
  }, [status, addingAccount, waited])

  // Nothing pending once the client has finished checking: a callback without a
  // usable code is a failure, not an indefinite spinner.
  const failed = status === 'anonymous'

  return (
    <main className="callback">
      <div className="callback__card" role="status" aria-live="polite">
        {failed ? (
          <>
            <h1 className="callback__title">
              <Icon name="review" size={20} /> Sign-in did not complete
            </h1>
            <p className="callback__body">
              {error ??
                'No session was established. The link may have expired, or the sign-in window was closed before it finished.'}
            </p>
            <Link className="btn btn--primary btn--small" to="/sign-in">
              Return to sign-in
            </Link>
          </>
        ) : (
          <>
            <h1 className="callback__title">
              <Icon name="sparkle" size={20} /> Completing sign-in
            </h1>
            <p className="callback__body">
              {addingAccount && status === 'authenticated'
                ? 'Adding the account you chose. The account already signed in stays saved on this device.'
                : 'Verifying the session with Supabase. This takes a moment.'}
            </p>
          </>
        )}
      </div>
    </main>
  )
}
