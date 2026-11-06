import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useRouter } from '@tanstack/react-router'
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

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  return (
    <Link
      to={item.to}
      className="app-nav__link"
      activeProps={{ className: 'app-nav__link is-active', 'aria-current': 'page' }}
      onClick={onNavigate}
    >
      <Icon name={item.icon} size={17} />
      <span>{item.label}</span>
    </Link>
  )
}

function UserMenu() {
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
    <div className="user-menu">
      <button
        ref={button}
        type="button"
        className="user-menu__button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls="user-menu-panel"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="user-menu__avatar" aria-hidden="true">
          {initials(name) || 'A'}
        </span>
        <span className="user-menu__name">{name}</span>
        <Icon name="arrow" size={14} />
      </button>

      <div
        className="user-menu__panel"
        id="user-menu-panel"
        ref={panel}
        role="menu"
        hidden={!open}
      >
        <div className="user-menu__identity">
          <p className="user-menu__identity-name">{name}</p>
          <p className="user-menu__identity-email mono">{user?.email ?? 'No email on session'}</p>
        </div>
        <p className="user-menu__note">
          Roles and workspace membership are read from the engine, which is not deployed yet.
          The interface never infers a role from the browser session.
        </p>
        <button
          type="button"
          role="menuitem"
          className="user-menu__signout"
          onClick={() => {
            void (async () => {
              await signOut()
              setOpen(false)
              await router.navigate({ to: '/sign-in', replace: true })
            })()
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  )
}

/**
 * The authenticated application frame. Marketing pages do not use it; this is
 * the chrome for every signed-in screen.
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
  const [navOpen, setNavOpen] = useState(false)
  const toggle = useRef<HTMLButtonElement>(null)

  const closeNav = useCallback((restoreFocus = true) => {
    setNavOpen(false)
    if (restoreFocus) toggle.current?.focus()
  }, [])

  useEffect(() => {
    if (!navOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeNav()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [navOpen, closeNav])

  return (
    <div className="app" data-nav-open={navOpen}>
      <a className="skip-link" href="#app-content">
        Skip to content
      </a>

      <aside className="app-sidebar" id="app-sidebar">
        <div className="app-sidebar__head">
          <Link to="/dashboard" className="brand-link" aria-label="Aetrix dashboard">
            <Brand size={26} />
          </Link>
          <button
            type="button"
            className="app-sidebar__close"
            onClick={() => closeNav()}
            aria-label="Close navigation"
          >
            <Icon name="close" size={18} />
          </button>
        </div>

        <div className="workspace-switch" aria-label="Workspace">
          <p className="workspace-switch__label mono">Workspace</p>
          <button type="button" className="workspace-switch__control" disabled>
            <span className="workspace-switch__name">Not connected</span>
            <span className="chip app-chip" data-tone="attention">
              WIP
            </span>
          </button>
          <p className="workspace-switch__note">
            Workspace membership comes from the engine API, which has no public deployment yet.
          </p>
        </div>

        <nav className="app-nav" aria-label="Application">
          {PRIMARY_NAV.map((item) => (
            <NavLink key={item.to} item={item} onNavigate={() => closeNav(false)} />
          ))}
          <p className="app-nav__group mono">Account</p>
          {SECONDARY_NAV.map((item) => (
            <NavLink key={item.to} item={item} onNavigate={() => closeNav(false)} />
          ))}
        </nav>

        <div className="app-sidebar__foot">
          <p className="app-sidebar__note mono">Aetrix V5.5 · pre-release</p>
          <Link to="/" className="app-sidebar__marketing">
            Marketing site
            <Icon name="arrow" size={14} />
          </Link>
        </div>
      </aside>

      {navOpen ? (
        <button
          type="button"
          className="app-scrim"
          aria-label="Close navigation"
          onClick={() => closeNav()}
        />
      ) : null}

      <div className="app-main">
        <header className="app-topbar">
          <button
            ref={toggle}
            type="button"
            className="app-topbar__toggle"
            aria-expanded={navOpen}
            aria-controls="app-sidebar"
            aria-label={navOpen ? 'Close navigation' : 'Open navigation'}
            onClick={() => setNavOpen((value) => !value)}
          >
            <Icon name={navOpen ? 'close' : 'menu'} size={20} />
          </button>

          <p className="app-topbar__crumb mono">{eyebrow}</p>

          <div className="app-topbar__actions">
            <ThemeSwitch />
            <UserMenu />
          </div>
        </header>

        <main className="app-content" id="app-content" tabIndex={-1}>
          <div className="app-page-head">
            <h1 className="app-page-head__title">{title}</h1>
            {description ? <p className="app-page-head__lede">{description}</p> : null}
            {actions ? <div className="app-page-head__actions">{actions}</div> : null}
          </div>
          {children}
        </main>
      </div>
    </div>
  )
}
