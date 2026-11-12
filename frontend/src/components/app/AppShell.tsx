import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useRouterState } from '@tanstack/react-router'
import { displayName, initials, useAuth } from '../../lib/auth/AuthProvider'
import { NAV_BY_ROLE, ROLE_META, type AppPath, type NavItem, type RoleNav } from '../../lib/auth/roles'
import { ThemeSwitch } from '../site/ThemeSwitch'
import { Brand } from '../ui/Brand'
import { Icon } from '../ui/Icons'
import { AccountSwitcher } from './AccountSwitcher'

/** Trailing slashes are normal on static hosting, so the comparison strips them. */
function useActivePath() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  return pathname.replace(/\/+$/, '') || '/'
}

function isActive(path: string, item: NavItem) {
  if (item.to === '/dashboard' || item.to === '/platform' || item.to === '/assistant') {
    return path === item.to
  }
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
      title={item.label}
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
    // Re-measure when the group label or the role changes the list's height.
  }, [path])

  return { nav, y }
}

/** A rail preference is a preference, not state: it survives the session. */
const RAIL_KEY = 'aetrix:rail'

function useRailCollapsed() {
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined') return
    setCollapsed(window.localStorage.getItem(RAIL_KEY) === 'collapsed')
  }, [])

  const toggle = () => {
    setCollapsed((value) => {
      const next = !value
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(RAIL_KEY, next ? 'collapsed' : 'expanded')
      }
      return next
    })
  }

  return { collapsed, toggle }
}

function ProfileMenu({ role }: { role: keyof typeof ROLE_META | null }) {
  const { user, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  // Escape is the one dismissal that owes the user their focus back; a click on
  // the page keeps the focus where the click put it.
  const restoreFocus = useRef(false)
  // Where the panel hangs, in viewport coordinates: just past the rail's outer
  // edge and level with the trigger's foot. Measured rather than fixed, so the
  // expanded (236px) and collapsed (72px) rails place it identically.
  const [anchor, setAnchor] = useState<{ left: number; bottom: number; width: number } | null>(null)

  const place = useCallback(() => {
    const trigger = button.current
    if (!trigger || typeof window === 'undefined') return
    const rail = trigger.closest('.app-sidebar') ?? trigger
    const left = Math.round(rail.getBoundingClientRect().right + 12)
    setAnchor({
      left,
      bottom: Math.max(12, Math.round(window.innerHeight - trigger.getBoundingClientRect().bottom)),
      // Never wider than the room beside the rail, so the panel cannot run off
      // the window on a narrow desktop.
      width: Math.max(240, Math.round(window.innerWidth - left - 16)),
    })
  }, [])

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      restoreFocus.current = true
      close()
    }
    // An open panel must not be left hanging over content that moved beneath it,
    // so a scroll outside the panel dismisses it. The scroll position is
    // compared rather than the event: the router restores scroll on render and
    // emits scroll events without moving the page at all.
    const openedAt = { x: window.scrollX, y: window.scrollY }
    const onScroll = (event: Event) => {
      const target = event.target as Node | null
      if (target && panel.current?.contains(target)) return
      const moved =
        Math.abs(window.scrollY - openedAt.y) >= 2 || Math.abs(window.scrollX - openedAt.x) >= 2
      if (!moved) return
      close()
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (panel.current?.contains(target) || button.current?.contains(target)) return
      close()
    }
    const onResize = () => place()

    // preventScroll: focusing the panel must not scroll the page, which would
    // dismiss the panel that was just opened.
    panel.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus({ preventScroll: true })

    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onResize)
      document.removeEventListener('pointerdown', onPointerDown)
      // After the commit, not in the handler: removing the focused close button
      // sends focus to the body, which would undo an earlier focus() call.
      if (restoreFocus.current) {
        restoreFocus.current = false
        button.current?.focus({ preventScroll: true })
      }
    }
  }, [open, place])

  const name = displayName(user)
  const meta = role ? ROLE_META[role] : null

  function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    place()
    setOpen(true)
  }

  return (
    <div className="hub-profile">
      <button
        ref={button}
        type="button"
        className="hub-profile__trigger"
        aria-expanded={open}
        aria-controls="hub-profile-menu"
        onClick={toggle}
      >
        <span className="hub-avatar" aria-hidden="true">
          {initials(name) || 'A'}
        </span>
        <span className="hub-profile__id">
          <span className="hub-profile__name">{name}</span>
          <span className="hub-profile__email">{meta?.label ?? 'No role assigned'}</span>
        </span>
        <Icon name="chevron" size={14} className="hub-profile__caret" />
      </button>

      {/*
       * Portalled to the body and measured from the rail: inside the sidebar the
       * panel inherits the rail's stacking context, so page content could paint
       * over it, and its 340px width would hang across the reading column. The
       * panel only mounts after a click, so there is no SSR divergence.
       */}
      {open
        ? createPortal(
            <div className="hub-profile__layer">
              <div className="hub-profile__scrim" aria-hidden="true" />
              <div
                className="hub-profile__menu"
                id="hub-profile-menu"
                ref={panel}
                role="group"
                aria-label="Your account"
                style={
                  anchor
                    ? {
                        left: anchor.left,
                        bottom: anchor.bottom,
                        width: Math.min(340, anchor.width),
                        maxHeight: `calc(100dvh - ${anchor.bottom + 16}px)`,
                      }
                    : undefined
                }
              >
                <div className="hub-profile__head">
                  <p className="hub-profile__label mono">Signed in</p>
                  <button
                    type="button"
                    className="hub-profile__close"
                    aria-label="Close account menu"
                    data-autofocus
                    onClick={() => setOpen(false)}
                  >
                    <Icon name="close" size={14} />
                  </button>
                </div>
                <p className="hub-profile__account mono">{user?.email ?? 'No email on session'}</p>
                <p className="hub-profile__note">
                  {meta
                    ? `${meta.label} · ${meta.scope}. The engine, not this screen, decides what the account may read.`
                    : 'This account has no role in its verified claims, so no dashboard is opened for it.'}
                </p>
                <AccountSwitcher onSwitched={() => setOpen(false)} />
                <button
                  type="button"
                  className="hub-profile__signout"
                  onClick={() => {
                    void (async () => {
                      // With another account saved, signing out opens it rather than
                      // ending at the sign-in page; the shell keeps rendering either way.
                      await signOut()
                      setOpen(false)
                    })()
                  }}
                >
                  <Icon name="logout" size={15} />
                  Sign out of this account
                </button>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}

function AccountSheet({
  open,
  onClose,
  path,
  nav,
  role,
}: {
  open: boolean
  onClose: () => void
  path: string
  nav: RoleNav
  role: keyof typeof ROLE_META | null
}) {
  const { user, signOut } = useAuth()
  const panel = useRef<HTMLDivElement>(null)
  const name = displayName(user)
  const meta = role ? ROLE_META[role] : null

  // Every destination except the four one-tap tabs, in rail order.
  const sheetNav = [...nav.primary, ...nav.secondary].filter(
    (item) => !nav.tabs.some((tab) => tab.to === item.to),
  )

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
          <span className="hub-sheet__email mono">{meta?.label ?? 'No role assigned'}</span>
        </span>
      </div>

      <nav className="hub-sheet__nav" aria-label="More sections">
        {meta ? <p className="hub-sheet__group mono">{meta.scope}</p> : null}
        {sheetNav.map((item) => (
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

      <AccountSwitcher onSwitched={onClose} />

      <button
        type="button"
        className="hub-sheet__signout"
        onClick={() => {
          void (async () => {
            // A second saved account takes over, so this must not force the
            // sign-in page for a user who is still signed in elsewhere.
            await signOut()
            onClose()
          })()
        }}
      >
        <Icon name="logout" size={16} />
        Sign out of this account
      </button>

      <p className="hub-sheet__note">
        Membership and permissions are resolved by the engine for the signed-in account.
      </p>
    </div>
  )
}

/**
 * The authenticated application frame.
 *
 * Marketing pages do not use it. This is the chrome for every signed-in screen:
 * a rail with the workspace and account always visible on a wide screen, and a
 * bottom tab bar with an account sheet on a phone. The rail's destinations are
 * supplied per account type, so the same shell reads as three different tools
 * without introducing a second design language.
 *
 * A route supplies the page heading through `title`. The dashboards pass an
 * empty title because their greeting is the page's own `h1`.
 */
export function AppShell({
  title,
  eyebrow,
  description,
  actions,
  role,
  children,
}: {
  title: string
  eyebrow: string
  description?: string
  actions?: ReactNode
  /** The account type driving navigation; `null` renders the base rail. */
  role: keyof typeof ROLE_META | null
  children: ReactNode
}) {
  const path = useActivePath()
  const [sheetOpen, setSheetOpen] = useState(false)
  const { user } = useAuth()
  const { nav, y } = useNavMarker(path)
  const { collapsed, toggle } = useRailCollapsed()
  const name = displayName(user)

  const meta = role ? ROLE_META[role] : null
  const layout = role ? NAV_BY_ROLE[role] : NAV_BY_ROLE.supervisor
  const home: AppPath = meta ? meta.home : '/dashboard'

  // A navigation is a complete answer to the sheet, so it closes with the route.
  useEffect(() => {
    setSheetOpen(false)
  }, [path])

  return (
    <div className={collapsed ? 'app app--rail-collapsed' : 'app'} data-role={role ?? 'none'}>
      <a className="skip-link" href="#app-content">
        Skip to content
      </a>

      <aside className="app-sidebar" id="app-sidebar">
        <div className="hub-rail__head">
          <Link to={home} className="hub-rail__brand" aria-label="Aetrix home">
            <Brand size={26} />
          </Link>
          <button
            type="button"
            className="hub-rail__collapse"
            aria-expanded={!collapsed}
            aria-controls="app-sidebar"
            aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            onClick={toggle}
          >
            <Icon name="menu" size={15} />
          </button>
        </div>

        <div className="hub-workspace" aria-label="Workspace">
          <p className="hub-workspace__label mono">
            {meta ? meta.label : 'Workspace'}
          </p>
          <p className="hub-workspace__row">
            <span className="hub-workspace__name">Signed-in workspace</span>
          </p>
          <p className="hub-workspace__note">
            {meta
              ? meta.scope
              : 'The engine resolves membership and permissions for the verified session.'}
          </p>
        </div>

        <nav className="app-nav" aria-label="Application" ref={nav}>
          {y !== null ? (
            <span className="app-nav__marker" style={{ transform: `translateY(${y}px)` }} aria-hidden="true" />
          ) : null}

          {layout.primary.map((item) => (
            <NavLink key={item.to} item={item} path={path} />
          ))}

          <p className="app-nav__group mono">{layout.groupLabel}</p>
          {layout.secondary.map((item) => (
            <NavLink key={item.to} item={item} path={path} />
          ))}
        </nav>

        <div className="app-sidebar__foot">
          <Link to="/" className="hub-rail__site">
            <Icon name="arrow" size={14} />
            <span>Marketing site</span>
          </Link>
          <ProfileMenu role={role} />
        </div>
      </aside>

      <div className="app-main">
        <span className="app-ambient" aria-hidden="true" />

        <header className="app-topbar">
          <Link to={home} className="app-topbar__brand" aria-label="Aetrix home">
            <Brand size={22} />
          </Link>

          <p className="app-topbar__crumb mono">{eyebrow}</p>

          <div className="app-topbar__actions">
            {meta ? <span className="app-topbar__role mono">{meta.label}</span> : null}
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
          {layout.tabs.map((item) => {
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

        <AccountSheet
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          path={path}
          nav={layout}
          role={role}
        />
      </div>
    </div>
  )
}

/**
 * The real loading state while the client reads the stored session. It shows the
 * shape of the workspace that is about to appear, and says what is happening.
 */
export function HubBoot({ label = 'Workspace' }: { label?: string }) {
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
            <p className="hub-boot__note">Verifying with Supabase · {label}</p>
          </div>
        </main>
      </div>
    </div>
  )
}
