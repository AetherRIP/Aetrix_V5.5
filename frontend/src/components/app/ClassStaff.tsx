import { useCallback, useEffect, useState } from 'react'
import type { ApiResult } from '../../lib/api/client'
import {
  classroomClassAssignments,
  createClassroomClassAssignment,
  removeClassroomClassAssignment,
  type ClassroomClassAssignment,
} from '../../lib/api/classroom'
import type { Allocation, WorkspaceTarget } from '../../lib/api/allocations'
import type { Member } from '../../lib/api/types'
import { identityService } from '../../lib/services'

/**
 * Who is responsible for one allocated class.
 *
 * The three questions an administrator asks are answered here, in one place:
 * which workshop owns the class (the card this row sits in), which teacher is
 * responsible, and which assistants support that teacher. The engine stores the
 * relationship as an explicit row per (allocation, user) with role TEACHER or
 * REVIEWER — workspace membership alone is never class access, so this control
 * only assigns people who are already members of the owning workspace.
 */
export function ClassStaff({
  allocation,
  workspace,
  token,
  notify,
}: {
  allocation: Allocation
  workspace: WorkspaceTarget
  token: string | null
  notify: (tone: 'ok' | 'error', message: string) => void
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable' | 'error'>('loading')
  const [rows, setRows] = useState<ClassroomClassAssignment[]>([])
  const [reason, setReason] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [members, setMembers] = useState<Member[] | null>(null)
  const [membersError, setMembersError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!token) {
      setState('unavailable')
      return
    }
    const result = await classroomClassAssignments(workspace.id, allocation.course_id, {
      token,
    })
    if (result.status === 'ok') {
      setRows(result.data)
      setState('ready')
      setReason(null)
      return
    }
    if (result.status === 'unavailable' || result.code === 404 || result.code === 405) {
      setState('unavailable')
      setReason(null)
      return
    }
    setState('error')
    setReason(result.reason)
  }, [token, workspace.id, allocation.course_id])

  useEffect(() => {
    void load()
  }, [load])

  const openDialog = useCallback(async () => {
    setOpen(true)
    if (members !== null || !token) return
    const result = await identityService.members(workspace.id, { token })
    if (result.status === 'ok') {
      setMembers(result.data)
      setMembersError(null)
    } else {
      setMembers([])
      setMembersError(result.reason)
    }
  }, [members, token, workspace.id])

  const act = useCallback(
    async (label: string, run: () => Promise<ApiResult<unknown>>) => {
      setBusy(label)
      const result = await run()
      setBusy(null)
      if (result.status === 'ok') {
        notify('ok', `${label} succeeded.`)
        await load()
      } else {
        notify('error', `${label} failed: ${result.reason}`)
      }
    },
    [load, notify],
  )

  const teachers = rows.filter((row) => row.user_role === 'TEACHER')
  const assistants = rows.filter((row) => row.user_role === 'REVIEWER')
  const assignable = (members ?? []).filter(
    (member) => member.role === 'TEACHER' || member.role === 'REVIEWER',
  )
  const assignedTo = (member: Member) => rows.find((row) => row.user_id === member.id)

  return (
    <div className="ws-staff">
      <dl className="ws-staff__facts">
        <div>
          <dt>Teacher responsible</dt>
          <dd>
            {state === 'loading'
              ? 'Reading…'
              : state === 'unavailable'
                ? 'Not shown by this engine build'
                : teachers.length === 0
                  ? 'No teacher assigned to this class yet'
                  : teachers.map((row) => row.user_label ?? row.user_email ?? 'unnamed').join(', ')}
          </dd>
        </div>
        <div>
          <dt>Assistants</dt>
          <dd>
            {state === 'loading'
              ? 'Reading…'
              : state === 'unavailable'
                ? 'Not shown by this engine build'
                : assistants.length === 0
                  ? 'None — the teacher works alone on this class'
                  : assistants
                      .map((row) => row.user_label ?? row.user_email ?? 'unnamed')
                      .join(', ')}
          </dd>
        </div>
      </dl>

      {state === 'error' ? (
        <p className="ws-staff__note">Staff could not be read: {reason}</p>
      ) : null}

      {state === 'unavailable' ? (
        <p className="ws-staff__note">
          Staff can only be assigned from the workspace that owns this class. The engine
          answers as if the class did not exist outside it, so nothing is guessed here.
        </p>
      ) : (
        <button
          type="button"
          className="btn btn--small btn--outline"
          onClick={() => void openDialog()}
          disabled={!token}
        >
          Manage staff…
        </button>
      )}

      {open ? (
        <div className="app-modal" role="dialog" aria-modal="true" aria-label={`Staff for ${allocation.class_name}`}>
          <div className="app-modal__panel">
            <div className="app-modal__head">
              <div>
                <p className="ws-kicker mono">Class staff</p>
                <h2 className="app-modal__title">{allocation.class_name}</h2>
              </div>
              <button
                type="button"
                className="btn btn--small btn--outline"
                onClick={() => setOpen(false)}
              >
                Close
              </button>
            </div>

            <p className="ws-dialog__hint">
              This class belongs to {workspace.name}. Its teacher manages the class here; assistants
              support that teacher with permitted work. Neither role can move the class to another
              workshop — only an administrator can do that.
            </p>

            {membersError ? <p className="app-form__error">{membersError}</p> : null}

            {members === null ? (
              <p className="ws-section__loading">Reading workspace members…</p>
            ) : assignable.length === 0 ? (
              <div className="ws-empty">
                <strong>No teacher or assistant is a member of this workshop yet</strong>
                <p>
                  Add them to {workspace.name} under Account management first; then they can be
                  assigned to this class.
                </p>
              </div>
            ) : (
              <ul className="ws-staff__list">
                {assignable.map((member) => {
                  const existing = assignedTo(member)
                  return (
                    <li key={member.id}>
                      <div>
                        <span className="ws-staff__name">
                          {member.display_name ?? member.email ?? member.subject}
                        </span>
                        <span className="ws-key__fp">
                          {member.role === 'TEACHER' ? 'Teacher' : member.role === 'REVIEWER' ? 'Assistant' : member.role}
                          {member.email ? ` · ${member.email}` : ''}
                        </span>
                      </div>
                      {existing ? (
                        <button
                          type="button"
                          className="btn btn--small btn--outline"
                          disabled={busy !== null}
                          onClick={() =>
                            void act('Removing staff', () =>
                              removeClassroomClassAssignment(
                                workspace.id,
                                allocation.course_id,
                                existing.id,
                                { token },
                              ),
                            )
                          }
                        >
                          {busy === 'Removing staff' ? 'Removing…' : 'Remove'}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn btn--small btn--primary"
                          disabled={busy !== null}
                          onClick={() =>
                            void act('Assigning staff', () =>
                              createClassroomClassAssignment(
                                workspace.id,
                                allocation.course_id,
                                member.id,
                                { token },
                              ),
                            )
                          }
                        >
                          {busy === 'Assigning staff' ? 'Assigning…' : 'Assign'}
                        </button>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
