import { useState } from 'react'
import { useRouter, useRouterState } from '@tanstack/react-router'
import { initials, useAuth } from '../../lib/auth/AuthProvider'
import { allowsPath, homeFor, type AccountRole } from '../../lib/auth/roles'
import { Icon } from '../ui/Icons'

/**
 * The accounts signed in on this device, and the way to add or use another one.
 *
 * Switching hands a saved session back to Supabase and lets the rest of the app
 * re-resolve from that token: the shell's role, the engine's `/me` answer and
 * every tenant-scoped query all follow the active account, so nothing is carried
 * across from the account that was left behind.
 */
export function AccountSwitcher({
  onSwitched,
}: {
  /** Called after a switch succeeds, so a menu or sheet can close. */
  onSwitched?: () => void
}) {
  const {
    accounts,
    user,
    status,
    authUnavailableReason,
    switchAccount,
    forgetAccount,
    signInWithGoogle,
    signInWithPassword,
  } = useAuth()
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const router = useRouter()
  const [busyId, setBusyId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [formBusy, setFormBusy] = useState(false)

  const activeId = user?.id ?? null
  const canAuthenticate = status !== 'unconfigured'
  const otherAccounts = accounts.filter((account) => account.id !== activeId)

  /**
   * A screen opened by the previous account may belong to another account type.
   * The account now in use is sent to a screen its own role can open; a role the
   * claim cannot describe falls back to Settings, which every role may read.
   */
  async function land(role: AccountRole | null | undefined) {
    if (role === undefined) return
    const next = role ?? null
    if (allowsPath(next, pathname)) return
    await router.navigate({ to: homeFor(next) })
  }

  async function choose(id: string) {
    setBusyId(id)
    setMessage(null)
    const result = await switchAccount(id)
    setBusyId(null)
    if (result.ok) {
      await land(result.role)
      onSwitched?.()
    } else {
      setMessage(result.message ?? 'That account could not be opened.')
    }
  }

  function remove(id: string) {
    setMessage(null)
    forgetAccount(id)
    setMessage('Removed from this device. Sign in again to use it here.')
  }

  async function add() {
    setMessage(null)
    setBusyId('add')
    // The round-trip returns to this screen, so the page the user was reading
    // is recorded as the destination.
    await signInWithGoogle(pathname)
    setBusyId(null)
  }

  /**
   * A password sign-in adds the account rather than replacing it: the account in
   * use is already in the vault, and the new session joins it.
   */
  async function addWithPassword(event: React.FormEvent) {
    event.preventDefault()
    setMessage(null)
    if (!email.trim() || password.length === 0) {
      setMessage('Enter both an email address and a password.')
      return
    }
    setFormBusy(true)
    const result = await signInWithPassword(email.trim(), password)
    setFormBusy(false)
    if (!result.ok) {
      setMessage(result.message ?? 'That account could not sign in.')
      return
    }
    setEmail('')
    setPassword('')
    await land(result.role)
    onSwitched?.()
  }

  return (
    <div className="account-switch" role="group" aria-label="Accounts on this device">
      <p className="account-switch__label mono">Accounts on this device</p>

      {accounts.length > 0 ? (
        <ul className="account-switch__list">
          {accounts.map((account) => {
            const current = account.id === activeId
            const busy = busyId === account.id
            return (
              <li key={account.id} className="account-switch__item">
                <button
                  type="button"
                  className="account-switch__row"
                  data-active={current ? '' : undefined}
                  aria-current={current ? 'true' : undefined}
                  disabled={current || busyId !== null}
                  title={current ? 'This account is in use' : `Use ${account.email || account.name}`}
                  onClick={() => void choose(account.id)}
                >
                  <span className="hub-avatar" aria-hidden="true">
                    {initials(account.name || account.email) || 'A'}
                  </span>
                  <span className="account-switch__id">
                    <span className="account-switch__name">{account.name || account.email}</span>
                    <span className="account-switch__email">{account.email || 'No email on session'}</span>
                  </span>
                  <span className="account-switch__flag mono">
                    {current ? 'In use' : busy ? 'Opening…' : 'Use'}
                  </span>
                </button>
                {current ? null : (
                  <button
                    type="button"
                    className="account-switch__forget"
                    aria-label={`Remove ${account.email || account.name} from this device`}
                    title="Remove from this device"
                    disabled={busyId !== null}
                    onClick={() => remove(account.id)}
                  >
                    <Icon name="close" size={13} />
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="account-switch__note">
          Only <strong>{user?.email ?? 'this account'}</strong> is signed in here.
        </p>
      )}

      <button
        type="button"
        className="account-switch__add"
        disabled={!canAuthenticate || busyId !== null}
        onClick={() => void add()}
      >
        <Icon name="records" size={15} />
        {busyId === 'add' ? 'Opening Google…' : 'Add another account'}
      </button>

      <details className="account-switch__more">
        <summary>Add an account with a password</summary>
        <form className="account-switch__form" onSubmit={addWithPassword} method="post" noValidate>
          <label>
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
          <label>
            <span>Password</span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={!canAuthenticate || formBusy}
              required
            />
          </label>
          <button type="submit" className="btn btn--outline btn--small" disabled={!canAuthenticate || formBusy}>
            {formBusy ? 'Signing in…' : 'Add account'}
          </button>
        </form>
      </details>

      <p className="account-switch__note">
        {authUnavailableReason ??
          (otherAccounts.length > 0
            ? 'Switching reopens that account’s own session. Workspace and role come from the engine for whichever account is in use.'
            : 'A second account stays signed in on this device until you sign out of it or remove it here.')}
      </p>

      {message ? (
        <p className="account-switch__message" role="status">
          {message}
        </p>
      ) : null}
    </div>
  )
}
