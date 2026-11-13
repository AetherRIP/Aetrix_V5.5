import { useCallback, useId, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { LEGAL_DOCUMENTS } from '../../lib/legal'

/**
 * The acknowledgement that gates every sign-in action.
 *
 * Accounts are provisioned by an invitation or an operator, so there is no
 * registration form to attach consent to; the first thing a person can do is
 * sign in. This component makes that step require an explicit, unpreselected
 * acknowledgement of the legal documents instead of relying on a passing
 * "by continuing" sentence.
 *
 * It is honest about what it is: the acknowledgement is enforced in this
 * browser and is not yet recorded against the account on the server, because
 * the engine has no endpoint for it. The note says so, and the legal review
 * notes record the missing versioned-acceptance record as an outstanding
 * dependency rather than pretending it exists.
 */
export function useLegalAcknowledgement() {
  const [accepted, setAccepted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const checkbox = useRef<HTMLInputElement>(null)
  const errorId = useId()

  const confirmAccepted = useCallback((): boolean => {
    if (accepted) {
      setError(null)
      return true
    }
    setError('You must read and accept the Terms of Service before continuing.')
    checkbox.current?.focus()
    return false
  }, [accepted])

  return { accepted, setAccepted, error, confirmAccepted, checkbox, errorId }
}

export type LegalAcknowledgementState = ReturnType<typeof useLegalAcknowledgement>

export function LegalAcknowledgement({ ack }: { ack: LegalAcknowledgementState }) {
  return (
    <div className="legal-ack">
      <label className="legal-ack__label" htmlFor="legal-ack-checkbox">
        <input
          ref={ack.checkbox}
          id="legal-ack-checkbox"
          type="checkbox"
          name="legal-acknowledgement"
          checked={ack.accepted}
          onChange={(event) => ack.setAccepted(event.target.checked)}
          aria-describedby={`legal-ack-note${ack.error ? ' legal-ack-error' : ''}`}
          aria-invalid={ack.error ? true : undefined}
          required
        />
        <span>
          I have read and agree to the{' '}
          <Link to={LEGAL_DOCUMENTS.terms.path} target="_blank" rel="noreferrer">
            Terms of Service
          </Link>
          , and I acknowledge the{' '}
          <Link to={LEGAL_DOCUMENTS.privacy.path} target="_blank" rel="noreferrer">
            Privacy Policy
          </Link>
          ,{' '}
          <Link to={LEGAL_DOCUMENTS.cookies.path} target="_blank" rel="noreferrer">
            Cookie Policy
          </Link>{' '}
          and{' '}
          <Link to={LEGAL_DOCUMENTS['ai-disclosure'].path} target="_blank" rel="noreferrer">
            AI Use Disclosure
          </Link>
          . I understand that AI marking is provisional and must be reviewed by a human
          before it is relied on.
        </span>
      </label>

      <p className="legal-ack__note" id="legal-ack-note">
        Acknowledging the privacy notice is not consent to optional processing: this build
        sets no advertising or analytics cookies. The pilot does not yet record your
        acceptance against your account on the server, so it is asked each time you sign
        in. <Link to="/legal">All legal documents</Link>.
      </p>

      {ack.error ? (
        <p className="legal-ack__error" id="legal-ack-error" role="alert">
          {ack.error}
        </p>
      ) : null}
    </div>
  )
}
