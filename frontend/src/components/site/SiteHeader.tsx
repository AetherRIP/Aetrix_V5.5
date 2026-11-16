import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useActiveSection, useScrolled, vars } from '../../lib/hooks'
import { Brand } from '../ui/Brand'
import { Icon } from '../ui/Icons'
import { ThemeSwitch } from './ThemeSwitch'

const NAV = [
  { label: 'Scenes', hash: 'chapters' },
  { label: 'Workflow', hash: 'workflow' },
  { label: 'Instrument', hash: 'instrument' },
  { label: 'Platform', hash: 'platform' },
  { label: 'Trust', hash: 'security' },
] as const

const PANEL = [
  { label: 'The problem', hash: 'problem' },
  { label: 'Transformation', hash: 'transformation' },
  ...NAV,
  { label: 'Account types', hash: 'roles' },
  { label: 'Begin', hash: 'start' },
] as const

export function SiteHeader() {
  const scrolled = useScrolled()
  const activeSection = useActiveSection()
  const [open, setOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)

  const close = useCallback((restoreFocus = true) => {
    setOpen(false)
    if (restoreFocus) menuButton.current?.focus()
  }, [])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
      }
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (panel.current?.contains(target) || menuButton.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open, close])

  return (
    <header
      className="site-header"
      data-scrolled={scrolled}
      data-open={open}
      data-overlay={open ? '' : undefined}
    >
      <div className="shell site-header__inner">
        {/* The link's accessible name comes from the brand text itself; an
            aria-label here would have to repeat "Aetrix V5.5" to stay valid. */}
        <Link to="/" className="brand-link">
          <Brand />
        </Link>

        <nav className="site-nav" aria-label="Primary">
          {NAV.map((item) => (
            <Link
              key={item.hash}
              to="/"
              hash={item.hash}
              className="site-nav__link"
              data-active={activeSection === item.hash ? '' : undefined}
            >
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className="site-header__actions">
          <ThemeSwitch />
          <Link to="/sign-in" className="btn btn--small btn--outline header-signin">
            Sign in
          </Link>
          <button
            ref={menuButton}
            type="button"
            className="menu-toggle"
            aria-expanded={open}
            aria-controls="mobile-navigation"
            aria-label={open ? 'Close menu' : 'Open menu'}
            onClick={() => setOpen((value) => !value)}
          >
            <Icon name={open ? 'close' : 'menu'} size={20} />
          </button>
        </div>
      </div>

      <div className="site-header__progress" aria-hidden="true">
        <i />
      </div>

      <div
        className="mobile-panel"
        id="mobile-navigation"
        ref={panel}
        data-open={open}
        inert={!open}
        aria-hidden={!open}
      >
        <nav aria-label="Mobile" className="mobile-panel__nav">
          {PANEL.map((item, index) => (
            <Link
              key={item.hash}
              to="/"
              hash={item.hash}
              className="mobile-panel__link"
              style={vars({ '--i': index })}
              onClick={() => close(false)}
            >
              <span className="mobile-panel__index mono">
                {String(index + 1).padStart(2, '0')}
              </span>
              <span className="mobile-panel__label">{item.label}</span>
              <Icon name="arrow" size={16} />
            </Link>
          ))}
          <Link
            to="/sign-in"
            className="mobile-panel__link mobile-panel__link--cta"
            style={vars({ '--i': PANEL.length })}
            onClick={() => close(false)}
          >
            <span className="mobile-panel__index mono">—</span>
            <span className="mobile-panel__label">Sign in</span>
            <Icon name="arrow" size={16} />
          </Link>
        </nav>
        <p className="mobile-panel__note">
          Aetrix V5.5 pre-release. Every figure shown on this page is synthetic
          demonstration data.
        </p>
      </div>
    </header>
  )
}
