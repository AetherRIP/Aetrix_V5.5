import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import { Link, useRouter } from '@tanstack/react-router'
import { useAuth } from '../../lib/auth/AuthProvider'
import { getSupabase } from '../../lib/supabase'
import { LEGAL_DOCUMENTS } from '../../lib/legal'
import {
  readAcceptances,
  recordAcceptances,
  type RequiredAcceptance,
} from '../../lib/legal/acceptance'

type GateState =
  | { phase: 'checking' }
  | { phase: 'ready' }
  | { phase: 'required'; missing: RequiredAcceptance[] }
  | { phase: 'error'; reason: string }

/**
 * Blocks the authenticated application until the database confirms that the
 * signed-in account has accepted every required document at its current version.
 *
 * The check runs on every authenticated load and reads `public.legal_acceptances`
 * with the user's own token, so signing out, refreshing, clearing storage or
 * moving to another device all resolve to the same answer: the rows are already
 * there, or they are not. Nothing is cached between sessions.
 *
 * If the record cannot be read, access is not granted and the person can retry.
 * A failed read is never treated as consent.
 */
export function LegalAcceptanceGate({ children }: { children: ReactNode }) {
  const { session, signOut } = useAuth()
  const router = useRouter()
  const userId = session?.user.id ?? null
  const client = getSupabase()

  const [state, setState] = useState<GateState>({ phase: 'checking' })
  const [attempt, setAttempt] = useState(0)
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (!userId) return
    if (!client) {
      setState({
        phase: 'error',
        reason: 'Authentication is not configured for this build, so acceptance cannot be checked.',
      })
      return
    }

    let cancelled = false
    setState({ phase: 'checking' })

    void (async () => {
      const result = await readAcceptances(client, userId)
      if (cancelled) return
      if (result.status === 'error') {
        setState({ phase: 'error', reason: result.reason })
        return
      }
      if (result.missing.length > 0) {
        setState({ phase: 'required', missing: result.missing })
        return
      }
      setState({ phase: 'ready' })
    })()

    return () => {
      cancelled = true
    }
  }, [client, userId, attempt])

  const signOutAndLeave = useCallback(() => {
    void (async () => {
      await signOut()
      await router.navigate({ to: '/sign-in', replace: true })
    })()
  }, [router, signOut])

  async function accept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!client || !userId || state.phase !== 'required') return

    setSaving(true)
    setSaveError(null)
    const result = await recordAcceptances(client, userId, state.missing)
    setSaving(false)

    if (result.status === 'error') {
      setSaveError(result.reason)
      return
    }
    setChecked({})
    setState({ phase: 'ready' })
  }

  if (state.phase === 'ready') return <>{children}</>

  return (
    <main className="legal-gate" aria-busy={state.phase === 'checking'}>
      <div className="legal-gate__panel">
        <p className="legal-gate__eyebrow mono">Legal acceptance</p>

        {state.phase === 'checking' ? (
          <>
            <h1 className="legal-gate__title">Checking your legal acceptance</h1>
            <p className="legal-gate__body">
              Confirming the documents this account has already accepted. This is checked
              once per session, against the account record rather than this browser.
            </p>
          </>
        ) : null}

        {state.phase === 'error' ? (
          <>
            <h1 className="legal-gate__title">Your acceptance could not be checked</h1>
            <p className="legal-gate__body">
              The workspace stays closed until the service can confirm which documents this
              account has accepted. No acceptance has been assumed.
            </p>
            <p className="legal-gate__alert" role="alert">
              {state.reason}
            </p>
            <div className="legal-gate__actions">
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => setAttempt((value) => value + 1)}
              >
                Try again
              </button>
              <button type="button" className="btn btn--outline" onClick={signOutAndLeave}>
                Sign out
              </button>
            </div>
          </>
        ) : null}

        {state.phase === 'required' ? (
          <>
            <h1 className="legal-gate__title">Accept the documents to continue</h1>
            <p className="legal-gate__body">
              This account has not accepted the current version of every required document.
              Each acceptance is recorded against your account, so it is asked once — not on
              every sign-in, refresh or device.
            </p>

            <form className="legal-gate__form" onSubmit={accept}>
              <div className="legal-gate__docs">
                {state.missing.map((document) => (
                  <label className="legal-ack__label" key={document.documentType}>
                    <input
                      type="checkbox"
                      name={document.documentType}
                      checked={checked[document.documentType] ?? false}
                      onChange={(event) =>
                        setChecked((current) => ({
                          ...current,
                          [document.documentType]: event.target.checked,
                        }))
                      }
                    />
                    <span>
                      I have read and agree to the{' '}
                      <Link
                        to={LEGAL_DOCUMENTS[document.documentId].path}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {document.title}
                      </Link>{' '}
                      <span className="mono legal-gate__version">
                        version {document.version}
                      </span>
                      .
                    </span>
                  </label>
                ))}
              </div>

              {saveError ? (
                <p className="legal-gate__alert" role="alert">
                  {saveError}
                </p>
              ) : null}

              <div className="legal-gate__actions">
                <button
                  type="submit"
                  className="btn btn--primary"
                  disabled={
                    saving ||
                    state.missing.some(
                      (document) => !checked[document.documentType],
                    )
                  }
                >
                  {saving ? 'Recording acceptance…' : 'Accept and continue'}
                </button>
                <button type="button" className="btn btn--outline" onClick={signOutAndLeave}>
                  Sign out
                </button>
              </div>
            </form>

            <p className="legal-gate__note">
              The acceptance is stored in the Aetrix database against your account id with a
              server-generated timestamp. This browser holds no copy of it.{' '}
              <Link to="/legal">All legal documents</Link>.
            </p>
          </>
        ) : null}
      </div>
    </main>
  )
}
