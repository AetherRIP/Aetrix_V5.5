import { useEffect } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { takeNextPath, useAuth } from '../lib/auth/AuthProvider'
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
  const { status, error } = useAuth()

  useEffect(() => {
    if (status === 'authenticated') {
      window.location.replace(takeNextPath())
    }
  }, [status])

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
              Verifying the session with Supabase. This takes a moment.
            </p>
          </>
        )}
      </div>
    </main>
  )
}
