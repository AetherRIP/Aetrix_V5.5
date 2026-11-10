import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { EngineRole, Invitation, Member } from '../lib/api/types'
import { identityService } from '../lib/services'

export const Route = createFileRoute('/_app/workspace')({
  component: WorkspaceHub,
})

const INVITABLE_ROLES: EngineRole[] = ['ADMIN', 'TEACHER', 'REVIEWER', 'VIEWER']

function WorkspaceHub() {
  const session = useEngineSession()
  const workspaceId = session.tenantId
  const canManage = session.capabilities.includes('manage_members')

  const [membersState, reloadMembers] = useResource<Member[]>(
    workspaceId ?? 'none',
    workspaceId && session.token
      ? (signal) => identityService.members(workspaceId, { token: session.token, signal })
      : null,
  )
  const [invitationsState, reloadInvitations] = useResource<Invitation[]>(
    workspaceId ?? 'none',
    workspaceId && session.token
      ? (signal) => identityService.invitations({ token: session.token, signal })
      : null,
  )

  const [email, setEmail] = useState('')
  const [role, setRole] = useState<EngineRole>('TEACHER')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [issuedCode, setIssuedCode] = useState<string | null>(null)
  const [revokeReason, setRevokeReason] = useState('')

  const members = membersState.state === 'ok' ? membersState.data : []
  const invitations = invitationsState.state === 'ok' ? invitationsState.data : []

  async function invite(event: React.FormEvent) {
    event.preventDefault()
    if (!workspaceId || !session.token || !email.trim()) return
    setBusy(true)
    setMessage(null)
    setIssuedCode(null)
    const result = await identityService.invite(
      workspaceId,
      { email: email.trim().toLowerCase(), role, note: note.trim() || undefined },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setEmail('')
      setNote('')
      setMessage(`Invitation recorded for ${result.data.email} as ${result.data.role}.`)
      setIssuedCode(result.data.acceptance_code ?? null)
      reloadInvitations()
    } else {
      setMessage(result.reason)
    }
  }

  async function revoke(invitationId: string) {
    if (!session.token || !revokeReason.trim()) return
    setBusy(true)
    setMessage(null)
    const result = await identityService.revoke(invitationId, revokeReason.trim(), {
      token: session.token,
    })
    setBusy(false)
    if (result.status === 'ok') {
      setMessage('Invitation revoked.')
      reloadInvitations()
    } else {
      setMessage(result.reason)
    }
  }

  async function changeRole(member: Member, nextRole: EngineRole) {
    if (!workspaceId || !session.token || nextRole === member.role) return
    setBusy(true)
    setMessage(null)
    const result = await identityService.updateMemberRole(
      workspaceId,
      member.id,
      { role: nextRole },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setMessage(`${member.email ?? member.display_name ?? member.id} is now ${nextRole}.`)
      reloadMembers()
    } else {
      setMessage(result.reason)
    }
  }

  return (
    <div className="app-stack">
      <Panel title="Workspace" note="Served by the engine from your verified token">
        {session.status === 'ready' && session.me ? (
          <dl className="app-definitions">
            <div>
              <dt>Name</dt>
              <dd>{session.me.workspace_name}</dd>
            </div>
            <div>
              <dt>Slug</dt>
              <dd className="mono">{session.me.workspace_slug}</dd>
            </div>
            <div>
              <dt>Your engine role</dt>
              <dd className="mono">
                {session.me.role} ({session.me.ui_role})
              </dd>
            </div>
            <div>
              <dt>Capabilities</dt>
              <dd className="mono">{session.capabilities.join(', ') || 'read'}</dd>
            </div>
          </dl>
        ) : (
          <p className="app-hint mono">Waiting for GET /api/v1/me…</p>
        )}
        {session.status === 'error' && session.reason ? (
          <p className="app-form__error">{session.reason}</p>
        ) : null}
      </Panel>

      {message ? <p className="app-message">{message}</p> : null}
      {issuedCode ? (
        <p className="app-message">
          One-time acceptance code for this address: <code className="mono">{issuedCode}</code>.
          Share it privately; it is shown once.
        </p>
      ) : null}

      <DataState state={membersState} capability="GET /api/v1/workspaces/{id}/members">
        <Panel title="Members" note={`${members.length} account(s)`}>
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Members of this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Account</th>
                  <th scope="col">Role</th>
                  <th scope="col">Joined</th>
                  <th scope="col">Change role</th>
                </tr>
              </thead>
              <tbody>
                {members.length > 0 ? (
                  members.map((member) => {
                    const isSelf = session.me?.user_id === member.id
                    return (
                      <tr key={member.id}>
                        <td>
                          {member.display_name ?? member.email ?? member.subject}
                          {isSelf ? <span className="mono app-hint"> (you)</span> : null}
                        </td>
                        <td className="mono">{member.role}</td>
                        <td className="mono">{new Date(member.created_at).toLocaleDateString()}</td>
                        <td>
                          {canManage && !isSelf ? (
                            <select
                              className="app-input"
                              value={member.role}
                              disabled={busy}
                              aria-label={`Role for ${member.email ?? member.id}`}
                              onChange={(event) => void changeRole(member, event.target.value as EngineRole)}
                            >
                              {(['OWNER', 'ADMIN', 'TEACHER', 'REVIEWER', 'VIEWER'] as EngineRole[]).map(
                                (option) => (
                                  <option key={option} value={option}>
                                    {option}
                                  </option>
                                ),
                              )}
                            </select>
                          ) : (
                            <span className="app-hint">
                              {isSelf ? 'Your own role cannot be changed here' : 'No permission'}
                            </span>
                          )}
                        </td>
                      </tr>
                    )
                  })
                ) : (
                  <tr>
                    <td colSpan={4} className="data-table__empty">
                      No members returned.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </DataState>

      {canManage ? (
        <Panel title="Invite a member" note="Invitation only — accounts are never auto-created">
          <form className="app-form" onSubmit={invite}>
            <div className="app-form__row">
              <label className="app-form__label" htmlFor="invite-email">
                Verified email address
              </label>
              <input
                id="invite-email"
                className="app-input"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div className="app-form__row">
              <label className="app-form__label" htmlFor="invite-role">
                Engine role
              </label>
              <select
                id="invite-role"
                className="app-input"
                value={role}
                onChange={(event) => setRole(event.target.value as EngineRole)}
              >
                {INVITABLE_ROLES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="app-form__row">
              <label className="app-form__label" htmlFor="invite-note">
                Note (optional)
              </label>
              <input
                id="invite-note"
                className="app-input"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={500}
              />
            </div>
            <button
              type="submit"
              className="btn btn--small btn--primary"
              disabled={busy || !email.trim()}
            >
              {busy ? 'Recording…' : 'Record invitation'}
            </button>
          </form>
          <p className="app-hint">
            The address must match the verified email on the account that signs in. There is no
            email transport in this build: the invitation is a row, and an acceptance code is shown
            once for the inviter to deliver out of band.
          </p>
        </Panel>
      ) : (
        <StatePanel tone="empty" title="Only an owner or administrator can invite">
          <p>
            Your engine role does not include <code>manage_members</code>, so membership is
            read-only on this screen. The engine enforces the same rule server-side.
          </p>
        </StatePanel>
      )}

      <DataState state={invitationsState} capability="GET /api/v1/invitations">
        <Panel title="Invitations" note={`${invitations.length} record(s)`}>
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Invitations for this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Email</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col">Expires</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {invitations.length > 0 ? (
                  invitations.map((invitation) => (
                    <tr key={invitation.id}>
                      <td>{invitation.email}</td>
                      <td className="mono">{invitation.role}</td>
                      <td>
                        <span
                          className="chip app-chip"
                          data-tone={invitation.status === 'PENDING' ? 'attention' : 'ok'}
                        >
                          {invitation.status}
                        </span>
                      </td>
                      <td className="mono">{new Date(invitation.expires_at).toLocaleDateString()}</td>
                      <td>
                        {canManage && invitation.status === 'PENDING' ? (
                          <button
                            type="button"
                            className="btn btn--small btn--outline"
                            disabled={busy || !revokeReason.trim()}
                            onClick={() => void revoke(invitation.id)}
                            title="Enter a revocation reason below first"
                          >
                            Revoke
                          </button>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="data-table__empty">
                      No invitations recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="revoke-reason">
              Revocation reason (required)
            </label>
            <input
              id="revoke-reason"
              className="app-input"
              value={revokeReason}
              onChange={(event) => setRevokeReason(event.target.value)}
              maxLength={500}
            />
          </div>
          <div className="app-inline-actions">
            <button type="button" className="btn btn--small btn--outline" onClick={reloadInvitations}>
              Refresh
            </button>
            <button type="button" className="btn btn--small btn--outline" onClick={reloadMembers}>
              Refresh members
            </button>
          </div>
        </Panel>
      </DataState>
    </div>
  )
}
