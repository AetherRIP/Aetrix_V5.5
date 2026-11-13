import { useEffect, useState } from 'react'
import { Link, Outlet, createFileRoute, useRouter, useRouterState } from '@tanstack/react-router'
import { AppShell, HubBoot } from '../components/app/AppShell'
import { storeNextPath, useAuth } from '../lib/auth/AuthProvider'
import {
  allowsPath,
  homeFor,
  readRole,
  resolveRole,
  ROLE_META,
  type AccountRole,
} from '../lib/auth/roles'
import { useEngineSession } from '../lib/api/session'
import { identityService } from '../lib/services'
import { Icon } from '../components/ui/Icons'
import { StatePanel } from '../components/app/StatePanel'
import { LegalAcceptanceGate } from '../components/legal/LegalAcceptanceGate'

export const Route = createFileRoute('/_app')({
  component: AppLayout,
})

type PageMeta = { title: string; eyebrow: string; description?: string }

/**
 * The shell is mounted once for every authenticated screen; each route supplies
 * only its content. Detail routes keep a stable parent title and render their
 * own record heading inside the content area.
 */
function pageMeta(pathname: string): PageMeta {
  if (pathname.startsWith('/assignments/')) {
    return { title: 'Assignment', eyebrow: 'Work · assignment' }
  }
  if (pathname.startsWith('/submissions/')) {
    return { title: 'Submission review', eyebrow: 'Work · submission' }
  }

  // An empty title means the route renders its own `h1`. The dashboards do:
  // their greeting is the page heading, and a second one would compete with it.
  const table: Record<string, PageMeta> = {
    '/dashboard': {
      title: '',
      eyebrow: 'Hub',
      description:
        'The working view of marking throughput and exceptions for the current workspace.',
    },
    '/workspace': {
      title: 'Workspaces',
      eyebrow: 'Workspace hub',
      description: 'Every workspace you belong to, and the role the engine reports for you.',
    },
    '/inbox': {
      title: 'Inbox',
      eyebrow: 'Attention',
      description: 'Exceptions raised by the correction pipeline that need a person.',
    },
    '/queue': {
      title: 'Marking queue',
      eyebrow: 'Correction jobs',
      description: 'Live state of every correction job in this workspace.',
    },
    '/assignments': {
      title: 'Assignments',
      eyebrow: 'Work',
      description: 'Exams, blueprints and the submissions attached to each assignment.',
    },
    '/reports': {
      title: 'Reports',
      eyebrow: 'Outcomes',
      description: 'Cohort and question-level outcomes produced by the engine.',
    },
    '/settings': {
      title: 'Settings',
      eyebrow: 'Account',
      description: 'Your identity, session and workspace preferences.',
    },
    '/students': {
      title: 'Classes & students',
      eyebrow: 'Teaching',
      description: 'The classes allocated to this workspace and the students in them.',
    },
    '/gradebook': {
      title: 'Gradebook',
      eyebrow: 'Outcomes',
      description: 'Marks per student, per assignment, with the review state of each.',
    },
    '/analytics': {
      title: 'Performance analytics',
      eyebrow: 'Insight',
      description: 'Where the cohort is strong and where it needs teaching time.',
    },
    '/assistants': {
      title: 'Assistants',
      eyebrow: 'Team',
      description: 'The assistants working in this workspace and what each may do.',
    },
    '/classroom': {
      title: 'Google Classroom',
      eyebrow: 'Integration',
      description: 'Roster import and class allocation for this workspace.',
    },
    '/platform': {
      title: '',
      eyebrow: 'Platform',
      description: 'The operator view of the platform: workspaces, accounts and health.',
    },
    '/platform/workspaces': {
      title: 'Workspace allocation',
      eyebrow: 'Platform',
      description:
        'Every teacher workspace, the Classroom courses it owns, and the allocation history.',
    },
    '/platform/users': {
      // This screen renders its own page header beside the directory controls.
      title: '',
      eyebrow: 'Platform administration',
      description:
        'Every Supabase account on the platform, its role, status and workspace memberships.',
    },
    '/platform/health': {
      title: 'System health',
      eyebrow: 'Platform',
      description: 'API, worker, database and provider status as the engine reports it.',
    },
    '/platform/audit': {
      title: 'Audit log',
      eyebrow: 'Platform',
      description: 'Append-only record of privileged actions across the platform.',
    },
    '/platform/gemini': {
      title: 'Gemini fleet',
      eyebrow: 'Platform · providers',
      description:
        'Keys grouped by Google Cloud project, the quota each project shares, and the usage Aetrix recorded.',
    },
    '/platform/integrations': {
      title: 'AI providers',
      eyebrow: 'Platform',
      description: 'Provider configuration and, in future, Gemini usage and quota.',
    },
    '/platform/settings': {
      title: 'Platform settings',
      eyebrow: 'Platform',
      description: 'Defaults applied to every workspace on the platform.',
    },
    '/assistant': {
      title: '',
      eyebrow: 'My work',
      description: 'Your assigned classes, queue and the work waiting on you.',
    },
    '/assistant/classes': {
      title: 'Assigned classes',
      eyebrow: 'My work',
      description: 'The classes and students your teacher has assigned to you.',
    },
    '/assistant/work': {
      title: 'Marking workspace',
      eyebrow: 'My work',
      description: 'Review the submissions assigned to you, one script at a time.',
    },
    '/assistant/tasks': {
      title: 'Tasks',
      eyebrow: 'My work',
      description: 'Everything waiting on you, ordered by what is due first.',
    },
    '/assistant/progress': {
      title: 'My progress',
      eyebrow: 'My work',
      description: 'What you have completed and what remains in this marking cycle.',
    },
  }

  return table[pathname] ?? { title: 'Workspace', eyebrow: 'Aetrix' }
}

function SessionGate({ message, detail }: { message: string; detail?: string }) {
  return (
    <main className="app-boot">
      <div className="app-boot__card" role="status" aria-live="polite">
        <p className="app-boot__badge mono">
          <Icon name="lock" size={14} /> Secure area
        </p>
        <h1 className="app-boot__title">{message}</h1>
        {detail ? <p className="app-boot__body">{detail}</p> : null}
      </div>
    </main>
  )
}

/** The engine's presentation role is the fallback when the browser claim is absent. */
function roleFromEngine(uiRole: string | null | undefined): AccountRole | null {
  switch (uiRole) {
    case 'owner':
    case 'platform_operator':
    case 'supervisor':
    case 'assistant':
    case 'viewer':
      return uiRole
    default:
      return null
  }
}

/**
 * A verified identity with no engine membership. The owner can invite the exact
 * address and the invitee can redeem the one-time code here; the engine decides
 * the workspace and role, never this screen.
 */
function AccessGate({
  email,
  reason,
  errorCode,
  token,
  onAccepted,
  onSignOut,
}: {
  email: string | null
  reason: string | null
  errorCode: string | null
  token: string | null
  onAccepted: () => void
  onSignOut: () => void
}) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const canRedeem = errorCode === 'PROVISIONING_REQUIRED'

  async function accept(event: React.FormEvent) {
    event.preventDefault()
    if (!token || !code.trim()) return
    setBusy(true)
    setMessage(null)
    const result = await identityService.accept(code.trim(), { token })
    setBusy(false)
    if (result.status === 'ok') {
      onAccepted()
    } else {
      setMessage(result.reason)
    }
  }

  return (
    <main className="app-boot">
      <div className="app-boot__card" role="status" aria-live="polite">
        <p className="app-boot__badge mono">
          <Icon name="lock" size={14} /> Workspace access
        </p>
        <h1 className="app-boot__title">{canRedeem ? 'A workspace invitation is required' : 'The engine could not open this account'}</h1>
        {canRedeem ? (
          <>
            <p className="app-boot__body">
              {email ?? 'This account'} is signed in, but this address has no workspace
              membership yet.
            </p>
            <p className="app-boot__body">
              This is not a connection or outage problem. The engine answered this account’s
              request and found no membership for this address. This deployment admits an
              address only through an invitation, or through the one-time acceptance code
              issued with it.
            </p>
          </>
        ) : (
          <p className="app-boot__body">
            {email ?? 'This account'} is signed in, but no workspace membership has been resolved.
          </p>
        )}
        {reason ? <p className="app-boot__body">{reason}</p> : null}
        {canRedeem ? (
          <form className="app-form" onSubmit={accept}>
            <div className="app-form__row">
              <label className="app-form__label" htmlFor="acceptance-code">
                One-time acceptance code
              </label>
              <input
                id="acceptance-code"
                className="app-input mono"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                minLength={16}
                maxLength={200}
                autoComplete="one-time-code"
                required
              />
            </div>
            <p className="app-hint">
              Ask the workspace owner for the code shown when your invitation was recorded. If
              your verified email was invited directly, sign out and sign in again after the
              owner records it.
            </p>
            {message ? <p className="app-form__error">{message}</p> : null}
            <div className="app-inline-actions">
              <button type="submit" className="btn btn--primary btn--small" disabled={busy || !code.trim()}>
                {busy ? 'Checking…' : 'Redeem invitation'}
              </button>
              <button type="button" className="btn btn--outline btn--small" onClick={onSignOut}>
                Sign out
              </button>
            </div>
          </form>
        ) : (
          <div className="app-inline-actions">
            <button type="button" className="btn btn--outline btn--small" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        )}
      </div>
    </main>
  )
}

/**
 * A verified session without an account role. The interface refuses to guess:
 * no dashboard opens until an operator assigns the role in the identity
 * provider, which is the only place it can be written.
 */
function NoRole({
  email,
  detail,
  onSignOut,
}: {
  email: string | null
  detail?: string | null
  onSignOut: () => void
}) {
  return (
    <main className="app-boot">
      <div className="app-boot__card" role="status" aria-live="polite">
        <p className="app-boot__badge mono">
          <Icon name="lock" size={14} /> Role required
        </p>
        <h1 className="app-boot__title">No account role assigned</h1>
        <p className="app-boot__body">
          {detail ??
            `${email ?? 'This account'} is signed in, but neither its verified claims nor the engine returned a recognised workspace role. This screen cannot grant one.`}
        </p>
        <p className="app-hint">
          Assignable roles are issued by the identity provider: <code>owner</code>,{' '}
          <code>platform_operator</code>, <code>supervisor</code> and <code>assistant</code>.
        </p>
        <button type="button" className="btn btn--outline" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </main>
  )
}

function AppLayout() {
  const { status, user, authUnavailableReason, signOut } = useAuth()
  const router = useRouter()
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  // Static hosting serves directory URLs with a trailing slash; the metadata
  // table is keyed without one, so `/dashboard/` must resolve to the same page.
  const routePath = pathname.replace(/\/+$/, '') || '/'
  const engine = useEngineSession()
  // The engine answers from the verified token and its own membership rows, so
  // its role is final once it has answered. The identity-provider claim is only
  // the provisional hint used while /me is in flight, or when the engine is
  // unreachable: a stale claim must not demote the platform owner to an
  // assistant, and it must not promote an assistant either.
  const engineResolved = engine.status === 'ready'
  const role = resolveRole({
    engineResolved,
    engineRole: engineResolved ? roleFromEngine(engine.me?.ui_role) : null,
    claimRole: readRole(user),
  })

  useEffect(() => {
    if (status !== 'anonymous') return
    // Already on the way out: never record the sign-in page itself as the
    // destination the user was trying to reach.
    if (pathname === '/sign-in') return
    // The requested path is preserved so the user lands where they intended.
    // It travels in sessionStorage rather than the URL, which keeps the OAuth
    // redirect allow-list free of query parameters.
    storeNextPath(pathname)
    void router.navigate({ to: '/sign-in', replace: true })
  }, [status, pathname, router])

  // A role may only reach its own area. A platform operator who lands on a
  // workspace route is moved to the platform home rather than shown a broken
  // shell, and a teacher who types /platform is moved back to the workspace.
  useEffect(() => {
    if (status !== 'authenticated' || !role) return
    if (allowsPath(role, routePath)) return
    const home = homeFor(role)
    if (routePath === home) return
    if (role === 'platform_operator' || routePath.startsWith('/platform')) {
      void router.navigate({ to: home, replace: true })
    }
  }, [status, role, routePath, router])

  if (status === 'unconfigured') {
    return (
      <SessionGate
        message="Authentication is not configured"
        detail={authUnavailableReason ?? undefined}
      />
    )
  }

  if (status === 'loading') {
    // The workspace is about to appear: show its shape and say what is happening.
    return <HubBoot />
  }

  if (status === 'anonymous') {
    return (
      <SessionGate message="Sign-in required" detail="Redirecting you to the sign-in page." />
    )
  }

  if (!role) {
    if (engine.status === 'loading') {
      return <HubBoot label="Resolving workspace access" />
    }
    const signOutAndLeave = () => {
      void (async () => {
        // A second account saved on this device takes over, so only a sign-out
        // with nothing left to open ends at the sign-in page.
        const stillSignedIn = await signOut()
        if (!stillSignedIn) await router.navigate({ to: '/sign-in', replace: true })
      })()
    }
    if (engine.status === 'error' && engine.errorCode === 'PROVISIONING_REQUIRED') {
      return (
        <AccessGate
          email={user?.email ?? null}
          reason={engine.reason}
          errorCode={engine.errorCode}
          token={engine.token}
          onAccepted={engine.reload}
          onSignOut={signOutAndLeave}
        />
      )
    }
    return (
      <NoRole
        email={user?.email ?? null}
        detail={engine.reason}
        onSignOut={signOutAndLeave}
      />
    )
  }

  const meta = pageMeta(routePath)
  const permitted = allowsPath(role, routePath)

  // Every authenticated route sits behind the legal acceptance gate, which
  // reads the account's recorded acceptance from the database on each load.
  return (
    <LegalAcceptanceGate>
      <AppShell
        title={meta.title}
      eyebrow={meta.eyebrow}
                description={meta.description}
        role={role}
      >
      {permitted ? (
        <Outlet />
      ) : (
        <div className="app-stack">
          <StatePanel
            tone="error"
            title="This screen belongs to another account type"
            capability="role-scoped route"
          >
            <p>
              You are signed in as <strong>{ROLE_META[role].label}</strong>, whose scope is{' '}
              {ROLE_META[role].scope.toLowerCase()}. <code>{routePath}</code> is outside it,
              so nothing is loaded here.
            </p>
            <p>
              <Link className="btn btn--outline" to={homeFor(role)}>
                Go to my dashboard
              </Link>
            </p>
          </StatePanel>
        </div>
      )}
      </AppShell>
    </LegalAcceptanceGate>
  )
}
