import { useEffect, useRef, useState } from 'react'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { Icon } from '../components/ui/Icons'
import { useAuth } from '../lib/auth/AuthProvider'
import { completeClassroomOAuth } from '../lib/api/classroom'

export const Route = createFileRoute('/auth/classroom')({
  head: () => ({
    meta: [
      { title: 'Connecting Google Classroom — Aetrix V5.5' },
      { name: 'robots', content: 'noindex' },
    ],
  }),
  component: ClassroomCallback,
})

type Phase = 'waiting' | 'working' | 'done' | 'failed'

function callbackParams() {
  if (typeof window === 'undefined') return { code: null, state: null, error: null }
  const query = new URLSearchParams(window.location.search)
  return {
    code: query.get('code'),
    state: query.get('state'),
    error: query.get('error_description') ?? query.get('error'),
  }
}

/**
 * Google redirects here after the workspace manager consents. The code is
 * exchanged by the engine, not in the browser: this screen posts the code and
 * the signed state with the Supabase bearer token, and the engine refuses a
 * state issued for another workspace or another user.
 */
function ClassroomCallback() {
  const { status, session } = useAuth()
  const navigate = useNavigate()
  const [phase, setPhase] = useState<Phase>('waiting')
  const [message, setMessage] = useState<string | null>(null)
  const started = useRef(false)
  const token = session?.access_token ?? null

  useEffect(() => {
    if (started.current) return
    const { code, state, error } = callbackParams()

    if (error) {
      started.current = true
      setPhase('failed')
      setMessage(error)
      return
    }
    if (!code || !state) {
      started.current = true
      setPhase('failed')
      setMessage(
        'Google did not return an authorisation code. Start the connection again from the Classroom page.',
      )
      return
    }
    if (status === 'loading') return
    if (!token) {
      started.current = true
      setPhase('failed')
      setMessage('Sign in again, then reconnect Google Classroom from the Classroom page.')
      return
    }

    started.current = true
    setPhase('working')
    void completeClassroomOAuth({ code, state }, { token }).then((result) => {
      if (result.status === 'ok') {
        setPhase('done')
        window.setTimeout(() => {
          void navigate({ to: '/classroom' })
        }, 700)
      } else {
        setPhase('failed')
        setMessage(result.reason)
      }
    })
  }, [navigate, status, token])

  return (
    <main className="callback">
      <div className="callback__card" role="status" aria-live="polite">
        {phase === 'failed' ? (
          <>
            <h1 className="callback__title">
              <Icon name="review" size={20} /> Google Classroom was not connected
            </h1>
            <p className="callback__body">{message}</p>
            <Link className="btn btn--primary btn--small" to="/classroom">
              Return to Google Classroom
            </Link>
          </>
        ) : phase === 'done' ? (
          <>
            <h1 className="callback__title">
              <Icon name="sparkle" size={20} /> Classroom connected
            </h1>
            <p className="callback__body">
              The workspace authorisation was stored encrypted. Returning to the Classroom page.
            </p>
          </>
        ) : (
          <>
            <h1 className="callback__title">
              <Icon name="sparkle" size={20} /> Connecting Google Classroom
            </h1>
            <p className="callback__body">
              The engine is exchanging the authorisation code. This takes a moment.
            </p>
          </>
        )}
      </div>
    </main>
  )
}
