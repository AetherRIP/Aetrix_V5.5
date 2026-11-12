import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useActiveSection, useScrolled } from '../../lib/hooks'
import { Brand } from '../ui/Brand'
import { Icon } from '../ui/Icons'
import { ThemeSwitch } from './ThemeSwitch'

const NAV = [
  { label: 'Features', hash: 'features' },
  { label: 'Workflow', hash: 'workflow' },
  { label: 'Class reading', hash: 'signal' },
  { label: 'Security', hash: 'security' },
] as const

export function SiteHeader() {
  const scrolled = useScrolled()
  const activeSection = useActiveSection()
  const [open, setOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)

  const close = useCallback(
    (restoreFocus = true) => {
      setOpen(false)
      if (restoreFocus) menuButton.current?.focus()
    },
    [],
  )

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
    <header className="site-header" data-scrolled={scrolled} data-open={open}>
      <div className="shell site-header__inner">
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
              {item.label}
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

      <div className="mobile-panel" id="mobile-navigation" ref={panel} data-open={open} hidden={!open}>
        <nav aria-label="Mobile" className="mobile-panel__nav">
          {NAV.map((item) => (
            <Link
              key={item.hash}
              to="/"
              hash={item.hash}
              className="mobile-panel__link"
              onClick={() => close(false)}
            >
              <span>{item.label}</span>
              <Icon name="arrow" size={16} />
            </Link>
          ))}
          <Link
            to="/sign-in"
            className="mobile-panel__link"
            onClick={() => close(false)}
          >
            <span>Sign in</span>
            <Icon name="arrow" size={16} />
          </Link>
        </nav>
        <p className="mobile-panel__note">
          Pre-release build. Every figure shown is synthetic demonstration data.
        </p>
      </div>
    </header>
  )
}
