import { useEffect } from 'react'
import { Outlet, createFileRoute, useRouter, useRouterState } from '@tanstack/react-router'
import { AppShell } from '../components/app/AppShell'
import { storeNextPath, useAuth } from '../lib/auth/AuthProvider'
import { Icon } from '../components/ui/Icons'

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

  const table: Record<string, PageMeta> = {
    '/dashboard': {
      title: 'Dashboard',
      eyebrow: 'Workspace overview',
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

function AppLayout() {
  const { status, authUnavailableReason } = useAuth()
  const router = useRouter()
  const pathname = useRouterState({ select: (state) => state.location.pathname })

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

  if (status === 'unconfigured') {
    return (
      <SessionGate
        message="Authentication is not configured"
        detail={authUnavailableReason ?? undefined}
      />
    )
  }

  if (status === 'loading') {
    return <SessionGate message="Checking your session" detail="Verifying with Supabase." />
  }

  if (status === 'anonymous') {
    return (
      <SessionGate message="Sign-in required" detail="Redirecting you to the sign-in page." />
    )
  }

  const meta = pageMeta(pathname)

  return (
    <AppShell title={meta.title} eyebrow={meta.eyebrow} description={meta.description}>
      <Outlet />
    </AppShell>
  )
}
