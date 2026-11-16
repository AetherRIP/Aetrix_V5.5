import { useState } from 'react'
import { ROLE_META, type AccountRole } from '../../lib/auth/roles'
import { Icon } from '../ui/Icons'

type RoleKey = Extract<AccountRole, 'supervisor' | 'assistant' | 'platform_operator'>

const ROLES: {
  key: RoleKey
  numeral: string
  headline: string
  duties: string[]
  limit: string
  panels: { label: string; state: 'active' | 'read' | 'closed' }[]
}[] = [
  {
    key: 'supervisor',
    numeral: '01',
    headline: 'The teacher owns the marking.',
    duties: [
      'Manages classes, students and their records',
      'Creates assignments and approves the question blueprint',
      'Reviews exceptions, overrides marks and approves results',
      'Connects Google Classroom for the workspace',
    ],
    limit: 'One workspace only. No access to another workspace, or to platform accounts.',
    panels: [
      { label: 'Assignments', state: 'active' },
      { label: 'Marking queue', state: 'active' },
      { label: 'Reports', state: 'active' },
      { label: 'Assistants', state: 'read' },
      { label: 'Platform', state: 'closed' },
    ],
  },
  {
    key: 'assistant',
    numeral: '02',
    headline: 'The assistant works inside that workspace.',
    duties: [
      'Reviews submissions assigned by the teacher',
      'Works the submission queue and records overrides with a reason',
      'Reads results and tracks their own progress',
      'Cannot change workspace settings or manage membership',
    ],
    limit: 'Scoped to assigned classes and submissions — not a student account.',
    panels: [
      { label: 'My overview', state: 'active' },
      { label: 'Submission queue', state: 'active' },
      { label: 'Assigned classes', state: 'read' },
      { label: 'Workspace settings', state: 'closed' },
      { label: 'Platform', state: 'closed' },
    ],
  },
  {
    key: 'platform_operator',
    numeral: '03',
    headline: 'The administrator keeps the platform running.',
    duties: [
      'Operates workspaces, accounts and allocations',
      'Configures AI providers and reads system health',
      'Reads the append-only audit log',
      'Works platform-wide, without opening student records',
    ],
    limit: 'Platform scope. No student marks; the platform owner sits above it.',
    panels: [
      { label: 'Workspaces', state: 'active' },
      { label: 'Accounts', state: 'active' },
      { label: 'Provider fleet', state: 'active' },
      { label: 'Audit log', state: 'read' },
      { label: 'Student records', state: 'closed' },
    ],
  },
]

/**
 * Chapter eight: the three account types, as three workspaces rather than three
 * pricing cards. Selecting a role redraws the interface schematic beside it and
 * states what that account can and cannot reach. Labels, scopes and summaries
 * come from the role table itself so the marketing copy cannot drift from it.
 */
export function RoleStage() {
  const [activeKey, setActiveKey] = useState<RoleKey>('supervisor')
  const role = ROLES.find((entry) => entry.key === activeKey) ?? ROLES[0]
  const meta = ROLE_META[role.key]

  return (
    <section className="mk-roles mk-section" id="roles" aria-labelledby="roles-title">
      <div className="shell">
        <header className="mk-head mk-head--split" data-reveal>
          <div>
            <p className="mk-eyebrow">
              <span className="mono">08</span>
              <span>Account types</span>
            </p>
            <h2 className="mk-h2" id="roles-title">
              Three people, three boundaries.
            </h2>
          </div>
          <p className="mk-note">
            A teacher owns the marking, an assistant works inside that teacher’s
            workspace, and an administrator keeps the platform itself running.
            Choose an account to see what its interface actually opens.
          </p>
        </header>

        <div className="role">
          <div className="role__tabs" role="group" aria-label="Account types">
            {ROLES.map((entry) => (
              <button
                key={entry.key}
                type="button"
                className="role__tab"
                aria-pressed={entry.key === activeKey}
                onClick={() => setActiveKey(entry.key)}
              >
                <span className="mono role__tab-numeral">{entry.numeral}</span>
                <span className="role__tab-label">{ROLE_META[entry.key].label}</span>
              </button>
            ))}
          </div>

          <div className="role__stage">
            <div className="role__sketch" aria-hidden="true" data-role={role.key}>
              <svg viewBox="0 0 520 360" fill="none" focusable="false">
                <rect className="sk-app" x="16" y="16" width="488" height="328" rx="2" />
                <path className="sk-rule" d="M16 58h488M126 58v286" />

                <g className="sk-rail">
                  {[0, 1, 2, 3, 4].map((row) => (
                    <rect
                      key={row}
                      className={`sk-rail-item ${role.panels[row]?.state ?? 'closed'}`}
                      x="30"
                      y={88 + row * 30}
                      width={row === 0 ? 74 : 58 - row * 3}
                      height="9"
                      rx="1"
                    />
                  ))}
                </g>

                <g className="sk-head">
                  <rect x="146" y="82" width="144" height="12" rx="1" />
                  <rect x="146" y="104" width="86" height="7" rx="1" />
                  <rect x="392" y="82" width="90" height="18" rx="1" />
                </g>

                <g className="sk-cards">
                  {[0, 1, 2].map((column) => (
                    <rect
                      key={column}
                      className="sk-card"
                      x={146 + column * 114}
                      y="140"
                      width="100"
                      height="70"
                      rx="1"
                    />
                  ))}
                </g>

                <g className="sk-rows">
                  {[0, 1, 2, 3].map((row) => (
                    <rect
                      key={row}
                      className="sk-row"
                      x="146"
                      y={236 + row * 24}
                      width={row % 2 === 0 ? 336 : 288 - row * 12}
                      height="8"
                      rx="1"
                    />
                  ))}
                </g>

                <g className="sk-lock">
                  <rect x="392" y="82" width="90" height="18" rx="1" />
                </g>
              </svg>
              <p className="role__sketch-note mono">{meta.scope}</p>
            </div>

            <div className="role__panel">
              <p className="role__code mono" aria-live="polite">
                {role.numeral} · {meta.scope}
              </p>
              <h3 className="role__headline">{role.headline}</h3>
              <p className="role__summary">{meta.summary}</p>

              <ul className="role__duties">
                {role.duties.map((duty) => (
                  <li key={duty}>
                    <Icon name="check" size={13} />
                    <span>{duty}</span>
                  </li>
                ))}
              </ul>

              <ul className="role__panels" aria-label={`${meta.label} destinations`}>
                {role.panels.map((panel) => (
                  <li key={panel.label} className="mono" data-state={panel.state}>
                    <span className="role__panel-dot" aria-hidden="true" />
                    {panel.label}
                  </li>
                ))}
              </ul>

              <p className="role__limit">
                <Icon name="lock" size={12} />
                <span>{role.limit}</span>
              </p>
            </div>
          </div>
        </div>

        <p className="mk-footnote" data-reveal>
          <span className="mono">Also</span>
          A read-only viewer account type exists for colleagues who should see the
          workspace without changing a mark, and a platform owner holds both
          platform and workspace capabilities. Front-end route permissions are a
          convenience; the engine’s authorisation is the boundary.
        </p>
      </div>
    </section>
  )
}
