import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useRouter, useRouterState } from '@tanstack/react-router'
import { displayName, initials, useAuth } from '../../lib/auth/AuthProvider'
import { ThemeSwitch } from '../site/ThemeSwitch'
import { Brand } from '../ui/Brand'
import { Icon, type IconName } from '../ui/Icons'

type AppPath =
  | '/dashboard'
  | '/workspace'
  | '/inbox'
  | '/queue'
  | '/assignments'
  | '/reports'
  | '/settings'

type NavItem = { to: AppPath; label: string; icon: IconName }

const PRIMARY_NAV: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: 'chart' },
  { to: '/workspace', label: 'Workspaces', icon: 'classroom' },
  { to: '/inbox', label: 'Inbox', icon: 'records' },
  { to: '/queue', label: 'Marking queue', icon: 'pulse' },
  { to: '/assignments', label: 'Assignments', icon: 'assignment' },
  { to: '/reports', label: 'Reports', icon: 'blueprint' },
]

const SECONDARY_NAV: NavItem[] = [{ to: '/settings', label: 'Settings', icon: 'lock' }]

/**
 * The four destinations that are one tap away on a phone. Everything else lives
 * in the "More" sheet, so no route is ever further than two taps from anywhere.
 */
const TABS: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: 'chart' },
  { to: '/assignments', label: 'Assignments', icon: 'assignment' },
  { to: '/queue', label: 'Queue', icon: 'pulse' },
  { to: '/inbox', label: 'Inbox', icon: 'records' },
]

const SHEET_NAV: NavItem[] = [...PRIMARY_NAV, ...SECONDARY_NAV].filter(
  (item) => !TABS.some((tab) => tab.to === item.to),
)

/** Trailing slashes are normal on static hosting, so the comparison strips them. */
function useActivePath() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  return pathname.replace(/\/+$/, '') || '/'
}

function isActive(path: string, item: NavItem) {
  if (item.to === '/dashboard') return path === '/dashboard'
  return path === item.to || path.startsWith(`${item.to}/`)
}

function NavLink({
  item,
  path,
  onNavigate,
}: {
  item: NavItem
  path: string
  onNavigate?: () => void
}) {
  const active = isActive(path, item)
  return (
    <Link
      to={item.to}
      className="app-nav__link"
      data-active={active ? '' : undefined}
      aria-current={active ? 'page' : undefined}
      onClick={onNavigate}
    >
      <Icon name={item.icon} size={17} />
      <span>{item.label}</span>
    </Link>
  )
}

/**
 * The active marker is one rule that slides between links rather than a static
 * inset shadow on each: the rail reads as a single continuous list, and the eye
 * follows the movement instead of searching for a new highlight.
 */
function useNavMarker(path: string) {
  const nav = useRef<HTMLElement>(null)
  const [y, setY] = useState<number | null>(null)

  useEffect(() => {
    const element = nav.current
    if (!element) return

    const measure = () => {
      const active = element.querySelector<HTMLElement>('[data-active]')
      if (!active) {
        setY(null)
        return
      }
      setY(active.offsetTop + (active.offsetHeight - 18) / 2)
    }

    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [path])

  return { nav, y }
}

function ProfileMenu() {
  const { user, signOut } = useAuth()
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setOpen(false)
        button.current?.focus()
      }
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (panel.current?.contains(target) || button.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  const name = displayName(user)

  return (
    <div className="hub-profile">
      <button
        ref={button}
        type="button"
        className="hub-profile__trigger"
        aria-expanded={open}
        aria-controls="hub-profile-menu"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="hub-avatar" aria-hidden="true">
          {initials(name) || 'A'}
        </span>
        <span className="hub-profile__id">
          <span className="hub-profile__name">{name}</span>
          <span className="hub-profile__email">{user?.email ?? 'No email on session'}</span>
        </span>
        <Icon name="chevron" size={14} className="hub-profile__caret" />
      </button>

      <div className="hub-profile__menu" id="hub-profile-menu" ref={panel} hidden={!open}>
        <p className="hub-profile__label mono">Signed in</p>
        <p className="hub-profile__account mono">{user?.email ?? 'No email on session'}</p>
        <p className="hub-profile__note">
          Roles and workspace membership are read from the engine, which is not deployed
          yet. The interface never infers a role from the browser session.
        </p>
        <button
          type="button"
          className="hub-profile__signout"
          onClick={() => {
            void (async () => {
              await signOut()
              setOpen(false)
              await router.navigate({ to: '/sign-in', replace: true })
            })()
          }}
        >
          <Icon name="logout" size={15} />
          Sign out
        </button>
      </div>
    </div>
  )
}

function AccountSheet({
  open,
  onClose,
  path,
}: {
  open: boolean
  onClose: () => void
  path: string
}) {
  const { user, signOut } = useAuth()
  const router = useRouter()
  const panel = useRef<HTMLDivElement>(null)
  const name = displayName(user)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (panel.current?.contains(target)) return
      if ((target as HTMLElement).closest?.('.hub-tab--more')) return
      onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open, onClose])

  return (
    <div className="hub-sheet" id="hub-sheet" ref={panel} hidden={!open}>
      <div className="hub-sheet__identity">
        <span className="hub-avatar" aria-hidden="true">
          {initials(name) || 'A'}
        </span>
        <span>
          <span className="hub-sheet__name">{name}</span>
          <span className="hub-sheet__email mono">{user?.email ?? 'No email on session'}</span>
        </span>
      </div>

      <nav className="hub-sheet__nav" aria-label="More sections">
        {SHEET_NAV.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className="hub-sheet__link"
            data-active={isActive(path, item) ? '' : undefined}
            aria-current={isActive(path, item) ? 'page' : undefined}
            onClick={onClose}
          >
            <Icon name={item.icon} size={16} />
            <span>{item.label}</span>
          </Link>
        ))}
        <Link to="/" className="hub-sheet__link" onClick={onClose}>
          <Icon name="arrow" size={16} />
          <span>Marketing site</span>
        </Link>
      </nav>

      <div className="hub-sheet__row">
        <span>Appearance</span>
        <ThemeSwitch />
      </div>

      <button
        type="button"
        className="hub-sheet__signout"
        onClick={() => {
          void (async () => {
            await signOut()
            onClose()
            await router.navigate({ to: '/sign-in', replace: true })
          })()
        }}
      >
        <Icon name="logout" size={16} />
        Sign out
      </button>

      <p className="hub-sheet__note">
        Roles and workspace membership come from the engine, which is not deployed yet.
      </p>
    </div>
  )
}

/**
 * The authenticated application frame.
 *
 * Marketing pages do not use it. This is the chrome for every signed-in screen:
 * a rail with the workspace and account always visible on a wide screen, and a
 * bottom tab bar with an account sheet on a phone.
 *
 * A route supplies the page heading through `title`. The dashboard passes an
 * empty title because its greeting is the page's own `h1`.
 */
export function AppShell({
  title,
  eyebrow,
  description,
  actions,
  children,
}: {
  title: string
  eyebrow: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}) {
  const path = useActivePath()
  const [sheetOpen, setSheetOpen] = useState(false)
  const { user } = useAuth()
  const { nav, y } = useNavMarker(path)
  const name = displayName(user)

  // A navigation is a complete answer to the sheet, so it closes with the route.
  useEffect(() => {
    setSheetOpen(false)
  }, [path])

  return (
    <div className="app">
      <a className="skip-link" href="#app-content">
        Skip to content
      </a>

      <aside className="app-sidebar" id="app-sidebar">
        <Link to="/dashboard" className="hub-rail__brand" aria-label="Aetrix dashboard">
          <Brand size={26} />
        </Link>

        <div className="hub-workspace" aria-label="Workspace">
          <p className="hub-workspace__label mono">Workspace</p>
          <p className="hub-workspace__row">
            <span className="hub-workspace__name">Not connected</span>
            <span className="hub-chip" data-tone="wip">
              WIP
            </span>
          </p>
          <p className="hub-workspace__note">
            Membership comes from the engine API, which has no public deployment yet.
          </p>
        </div>

        <nav className="app-nav" aria-label="Application" ref={nav}>
          {y !== null ? (
            <span className="app-nav__marker" style={{ transform: `translateY(${y}px)` }} aria-hidden="true" />
          ) : null}

          {PRIMARY_NAV.map((item) => (
            <NavLink key={item.to} item={item} path={path} />
          ))}

          <p className="app-nav__group mono">Account</p>
          {SECONDARY_NAV.map((item) => (
            <NavLink key={item.to} item={item} path={path} />
          ))}
        </nav>

        <div className="app-sidebar__foot">
          <Link to="/" className="hub-rail__site">
            <Icon name="arrow" size={14} />
            <span>Marketing site</span>
          </Link>
          <ProfileMenu />
        </div>
      </aside>

      <div className="app-main">
        <span className="app-ambient" aria-hidden="true" />

        <header className="app-topbar">
          <Link to="/dashboard" className="app-topbar__brand" aria-label="Aetrix dashboard">
            <Brand size={22} />
          </Link>

          <p className="app-topbar__crumb mono">{eyebrow}</p>

          <div className="app-topbar__actions">
            <span className="app-topbar__theme">
              <ThemeSwitch />
            </span>
            <button
              type="button"
              className="app-topbar__avatar"
              aria-expanded={sheetOpen}
              aria-controls="hub-sheet"
              aria-label={sheetOpen ? 'Close account menu' : 'Open account menu'}
              onClick={() => setSheetOpen((value) => !value)}
            >
              <span className="hub-avatar" aria-hidden="true">
                {initials(name) || 'A'}
              </span>
            </button>
          </div>
        </header>

        <main className="app-content" id="app-content" tabIndex={-1}>
          <div className="hub-page" key={path}>
            {title ? (
              <div className="app-page-head">
                <div className="app-page-head__copy">
                  <h1 className="app-page-head__title">{title}</h1>
                  {description ? <p className="app-page-head__lede">{description}</p> : null}
                </div>
                {actions ? <div className="app-page-head__actions">{actions}</div> : null}
              </div>
            ) : null}
            {children}
          </div>
        </main>

        <nav className="hub-tabs" aria-label="Workspace sections">
          {TABS.map((item) => {
            const active = isActive(path, item)
            return (
              <Link
                key={item.to}
                to={item.to}
                className="hub-tab"
                data-active={active ? '' : undefined}
                aria-current={active ? 'page' : undefined}
              >
                <Icon name={item.icon} size={19} />
                <span>{item.label}</span>
              </Link>
            )
          })}
          <button
            type="button"
            className="hub-tab hub-tab--more"
            aria-expanded={sheetOpen}
            aria-controls="hub-sheet"
            onClick={() => setSheetOpen((value) => !value)}
          >
            <Icon name="menu" size={19} />
            <span>More</span>
          </button>
        </nav>

        <AccountSheet open={sheetOpen} onClose={() => setSheetOpen(false)} path={path} />
      </div>
    </div>
  )
}

/**
 * The real loading state while the client reads the stored session. It shows the
 * shape of the workspace that is about to appear, and says what is happening.
 */
export function HubBoot() {
  return (
    <div className="app app--boot" aria-busy="true" aria-live="polite">
      <div className="app-sidebar app-sidebar--skeleton" aria-hidden="true">
        <div className="hub-skel hub-skel--brand" />
        <div className="hub-skel hub-skel--nav" />
        <div className="hub-skel hub-skel--nav" />
        <div className="hub-skel hub-skel--nav" />
      </div>
      <div className="app-main">
        <main className="app-content">
          <div className="hub-boot">
            <p className="hub-boot__date mono">Checking your session</p>
            <div className="hub-skel hub-skel--title" />
            <div className="hub-skel hub-skel--line" />
            <p className="hub-boot__note">Verifying with Supabase.</p>
          </div>
        </main>
      </div>
    </div>
  )
}
