import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from '@tanstack/react-router'
import { NAV_BY_ROLE, type AccountRole, type NavItem } from '../../lib/auth/roles'
import { Icon } from '../ui/Icons'

type Command = NavItem & { group: string }

/**
 * A keyboard-first door into the screens this account may already open.
 *
 * The palette is a shortcut, not a second permission model: every entry comes
 * from the same role navigation the rail renders, so it cannot reveal a route
 * the account is not allowed to visit. Selecting an entry performs the ordinary
 * client-side navigation.
 */
export function CommandPalette({
  open,
  onClose,
  role,
  path,
}: {
  open: boolean
  onClose: () => void
  role: AccountRole | null
  path: string
}) {
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const listId = useId()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  const commands = useMemo<Command[]>(() => {
    if (!role) return []
    const layout = NAV_BY_ROLE[role]
    const seen = new Set<string>()
    const collect = (items: NavItem[], group: string) =>
      items.flatMap((item) => {
        if (seen.has(item.to)) return []
        seen.add(item.to)
        return [{ ...item, group }]
      })
    return [
      ...collect(layout.primary, 'Workspace'),
      ...collect(layout.secondary, layout.groupLabel),
      ...collect(layout.tabs, 'Quick tabs'),
    ]
  }, [role])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return commands
    return commands.filter(
      (command) =>
        command.label.toLowerCase().includes(term) ||
        command.to.toLowerCase().includes(term) ||
        command.group.toLowerCase().includes(term),
    )
  }, [commands, query])

  // The active row is always within the filtered result, including after the
  // query narrows the list under it.
  const activeIndex =
    filtered.length === 0 ? 0 : Math.min(active, filtered.length - 1)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(0)

    const body = document.body
    const previousOverflow = body.style.overflow
    const previousPadding = body.style.paddingRight
    const scrollbar = window.innerWidth - document.documentElement.clientWidth
    body.style.overflow = 'hidden'
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`

    const frame = window.requestAnimationFrame(() => input.current?.focus({ preventScroll: true }))
    return () => {
      window.cancelAnimationFrame(frame)
      body.style.overflow = previousOverflow
      body.style.paddingRight = previousPadding
    }
  }, [open])

  useEffect(() => {
    if (!open) return

    const focusable = () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null && element.tabIndex >= 0)

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        if (filtered.length > 0) {
          setActive((value) => (Math.min(value, filtered.length - 1) + 1) % filtered.length)
        }
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        if (filtered.length > 0) {
          setActive(
            (value) =>
              (Math.min(value, filtered.length - 1) + filtered.length - 1) % filtered.length,
          )
        }
        return
      }
      if (event.key === 'Enter') {
        const command = filtered[activeIndex]
        if (!command) return
        event.preventDefault()
        onClose()
        void navigate({ to: command.to })
        return
      }
      if (event.key !== 'Tab') return

      const items = focusable()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      const current = document.activeElement as HTMLElement | null
      if (event.shiftKey && (current === first || !panel.current?.contains(current))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && current === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [activeIndex, filtered, navigate, onClose, open])

  // Keep the highlighted row visible without moving the page behind the layer.
  useEffect(() => {
    if (!open) return
    panel.current
      ?.querySelector<HTMLElement>('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, open])

  if (!open) return null

  return createPortal(
    <div className="cmd-layer">
      <div className="cmd-scrim" aria-hidden="true" onClick={onClose} />
      <div
        className="cmd-panel"
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cmd-title"
      >
        <div className="cmd-head">
          <span className="cmd-head__icon" aria-hidden="true">
            <Icon name="search" size={17} />
          </span>
          <h2 className="cmd-head__title visually-hidden" id="cmd-title">
            Jump to a page
          </h2>
          <input
            ref={input}
            className="cmd-input"
            type="text"
            role="combobox"
            value={query}
            placeholder="Where do you want to go?"
            aria-label="Search pages"
            aria-autocomplete="list"
            aria-haspopup="listbox"
            aria-controls={listId}
            aria-expanded="true"
            aria-activedescendant={
              filtered.length > 0 ? `${listId}-option-${activeIndex}` : undefined
            }
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setQuery(event.target.value)
              setActive(0)
            }}
          />
          <kbd className="cmd-key">Esc</kbd>
        </div>

        <div className="cmd-body">
          {filtered.length > 0 ? (
            <>
              <p className="cmd-group mono">
                {query.trim()
                  ? `${filtered.length} match${filtered.length === 1 ? '' : 'es'}`
                  : 'Pages'}
              </p>
              <ul className="cmd-list" id={listId} role="listbox" aria-label="Pages">
                {filtered.map((command, index) => {
                  const current = command.to === path
                  return (
                    <li
                      key={command.to}
                      id={`${listId}-option-${index}`}
                      role="option"
                      aria-selected={index === activeIndex}
                    >
                      <button
                        type="button"
                        className="cmd-item"
                        data-active={index === activeIndex ? 'true' : undefined}
                        data-current={current ? 'true' : undefined}
                        tabIndex={-1}
                        onMouseMove={() => setActive(index)}
                        onClick={() => {
                          onClose()
                          void navigate({ to: command.to })
                        }}
                      >
                        <span className="cmd-item__icon" aria-hidden="true">
                          <Icon name={command.icon} size={16} />
                        </span>
                        <span className="cmd-item__copy">
                          <strong>{command.label}</strong>
                          <span className="mono">{current ? 'Current page' : command.to}</span>
                        </span>
                        <Icon
                          name={current ? 'dot' : 'arrow'}
                          size={14}
                          className="cmd-item__end"
                        />
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          ) : (
            <div className="cmd-empty">
              <span className="cmd-empty__icon" aria-hidden="true">
                <Icon name="blueprint" size={18} />
              </span>
              <p>No page matches “{query.trim()}”.</p>
              <span>Try a section name, such as queue, reports or settings.</span>
            </div>
          )}
        </div>

        <div className="cmd-foot">
          <span className="cmd-foot__scope mono">
            {role ? `${NAV_BY_ROLE[role].primary.length + NAV_BY_ROLE[role].secondary.length} destinations` : 'No role'}
          </span>
          <span className="cmd-foot__keys">
            <kbd>↑</kbd>
            <kbd>↓</kbd>
            <span>move</span>
            <kbd>↵</kbd>
            <span>open</span>
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}
