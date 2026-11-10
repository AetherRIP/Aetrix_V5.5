import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { CapabilityList, Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { EngineRole, Invitation, Member } from '../lib/api/types'
import { identityService } from '../lib/services'

export const Route = createFileRoute('/_app/assistants')({
  component: Assistants,
})

const GRANTABLE: EngineRole[] = ['TEACHER', 'REVIEWER', 'VIEWER']

function Assistants() {
  const session = useEngineSession()
  const workspace = session.tenantId
  const canManage = session.capabilities.includes('manage_members')

  const [members, reloadMembers] = useResource<Member[]>(
    `members:${workspace ?? 'none'}`,
    workspace
      ? (signal) => identityService.members(workspace, { token: session.token, signal })
      : null,
  )
  const [invitations, reloadInvitations] = useResource<Invitation[]>(
    `invitations:${workspace ?? 'none'}:${canManage}`,
    workspace && canManage
      ? (signal) => identityService.invitations({ token: session.token, signal })
      : null,
  )

  const [email, setEmail] = useState('')
  const [role, setRole] = useState<EngineRole>('REVIEWER')
  const [note, setNote] = useState('')
  const [revokeReason, setRevokeReason] = useState('')
  const [created, setCreated] = useState<Invitation | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const memberRows = members.state === 'ok' ? members.data : []
  const invitationRows =
    invitations.state === 'ok'
      ? invitations.data.filter((invitation) => invitation.status === 'PENDING')
      : []

  async function invite(event: React.FormEvent) {
    event.preventDefault()
    if (!workspace || !email.trim()) return
    setBusy(true)
    setMessage(null)
    const result = await identityService.invite(
      workspace,
      { email: email.trim(), role, note: note.trim() || undefined },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setCreated(result.data)
      setEmail('')
      setNote('')
      reloadInvitations()
    } else {
      setMessage(result.reason)
    }
  }

  async function changeRole(member: Member, next: EngineRole) {
    if (!workspace || next === member.role) return
    setBusy(true)
    setMessage(null)
    const result = await identityService.updateMemberRole(
      workspace,
      member.id,
      { role: next, reason: 'Changed from the assistants screen' },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setMessage(`${member.email ?? member.subject} is now ${next}.`)
      reloadMembers()
    } else {
      setMessage(result.reason)
    }
  }

  async function revoke(invitation: Invitation) {
    setBusy(true)
    setMessage(null)
    const result = await identityService.revoke(invitation.id, revokeReason.trim(), {
      token: session.token,
    })
    setBusy(false)
    if (result.status === 'ok') {
      setMessage(`Invitation for ${invitation.email} revoked.`)
      reloadInvitations()
    } else {
      setMessage(result.reason)
    }
  }

  return (
    <div className="app-stack">
      {session.status === 'error' ? (
        <StatePanel tone="error" title="The engine refused this account" capability="/api/v1/me">
          <p>{session.reason}</p>
        </StatePanel>
      ) : null}

      {canManage ? (
        <Panel title="Invite a colleague" note="The engine emails nothing; share the code">
          <form className="app-form" onSubmit={invite}>
            <div className="app-form__row">
              <label className="app-form__label" htmlFor="invite-email">
                Email address
              </label>
              <input
                id="invite-email"
                type="email"
                className="app-input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                maxLength={320}
                required
              />
            </div>
            <div className="app-form__row">
              <label className="app-form__label" htmlFor="invite-role">
                Workspace role
              </label>
              <select
                id="invite-role"
                className="app-input"
                value={role}
                onChange={(event) => setRole(event.target.value as EngineRole)}
              >
                {GRANTABLE.map((value) => (
                  <option key={value} value={value}>
                    {value}
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
                maxLength={300}
              />
            </div>
            <div className="app-inline-actions">
              <button type="submit" className="btn btn--small btn--primary" disabled={busy}>
                Send invitation
              </button>
            </div>
          </form>

          {created?.acceptance_code ? (
            <div className="app-notice" role="status">
              <p className="app-hint">
                Acceptance code for {created.email}. It is shown once and cannot be read again:
              </p>
              <p className="mono" data-testid="acceptance-code">
                {created.acceptance_code}
              </p>
            </div>
          ) : null}
        </Panel>
      ) : (
        <StatePanel
          tone="empty"
          title="Your role cannot manage membership"
          capability="PATCH /api/v1/workspaces/{id}/members/{user_id}"
        >
          <p>
            Only a workspace owner or administrator can invite people, change roles or revoke an
            invitation. You can still see who belongs to this workspace. The engine enforces the
            same rule even if a button were shown.
          </p>
        </StatePanel>
      )}

      <Panel title="What an assistant may do" note="Set by the engine, not this page">
        <CapabilityList
          items={[
            {
              label: 'Review assigned work',
              detail: 'Read and review the submissions the workspace makes visible to them.',
              state: 'available',
              icon: 'pen',
            },
            {
              label: 'See workspace classes and students',
              detail: 'Reading the roster is a workspace capability, not a teaching one.',
              state: 'available',
              icon: 'classroom',
            },
            {
              label: 'Manage the workspace',
              detail: 'Refused: only an owner or administrator may invite, revoke or change roles.',
              state: 'blocked',
              icon: 'lock',
            },
            {
              label: 'Invite or remove assistants',
              detail: 'Available to owners and administrators above; the engine enforces the rule.',
              state: 'available',
              icon: 'eye',
            },
          ]}
        />
      </Panel>

      <Panel title="Members" note={`${memberRows.length} account(s)`}>
        <DataState state={members} capability="GET /api/v1/workspaces/{id}/members">
          {memberRows.length > 0 ? (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Members of this workspace</caption>
                <thead>
                  <tr>
                    <th scope="col">Account</th>
                    <th scope="col">Email</th>
                    <th scope="col">Role</th>
                  </tr>
                </thead>
                <tbody>
                  {memberRows.map((member) => (
                    <tr key={member.id}>
                      <th scope="row">{member.display_name ?? member.subject}</th>
                      <td className="mono">{member.email ?? '—'}</td>
                      <td>
                        {canManage &&
                        member.role !== 'PLATFORM_OWNER' &&
                        member.id !== session.me?.user_id ? (
                          <select
                            className="app-input app-input--inline"
                            value={member.role}
                            aria-label={`Role for ${member.email ?? member.subject}`}
                            disabled={busy}
                            onChange={(event) =>
                              void changeRole(member, event.target.value as EngineRole)
                            }
                          >
                            {GRANTABLE.map((value) => (
                              <option key={value} value={value}>
                                {value}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="mono">{member.role}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="app-hint">No member rows are stored for this workspace.</p>
          )}
        </DataState>
      </Panel>

      {canManage ? (
        <Panel title="Pending invitations" note={`${invitationRows.length} awaiting acceptance`}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="revoke-reason">
              Revocation reason (used for every revoke below)
            </label>
            <input
              id="revoke-reason"
              className="app-input"
              value={revokeReason}
              onChange={(event) => setRevokeReason(event.target.value)}
              maxLength={300}
              placeholder="e.g. invited the wrong address"
            />
          </div>
          <DataState state={invitations} capability="GET /api/v1/invitations">
            {invitationRows.length > 0 ? (
              <div className="table-scroll">
                <table className="data-table">
                  <caption className="visually-hidden">Pending invitations</caption>
                  <thead>
                    <tr>
                      <th scope="col">Email</th>
                      <th scope="col">Role</th>
                      <th scope="col">Expires</th>
                      <th scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invitationRows.map((invitation) => (
                      <tr key={invitation.id}>
                        <th scope="row" className="mono">
                          {invitation.email}
                        </th>
                        <td className="mono">{invitation.role}</td>
                        <td className="mono">
                          {new Date(invitation.expires_at).toLocaleString()}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn--small btn--outline"
                            disabled={busy}
                            onClick={() => void revoke(invitation)}
                          >
                            Revoke
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="app-hint">
                No pending invitations. An invitation appears here until it is accepted, expires or
                is revoked.
              </p>
            )}
          </DataState>
        </Panel>
      ) : null}

      {message ? <p className="app-message">{message}</p> : null}
    </div>
  )
}
