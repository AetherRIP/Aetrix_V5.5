import { useCallback, useEffect, useRef, useState } from 'react'
import { useEngineSession } from '../../lib/api/session'
import type { MessagingNotification } from '../../lib/api/types'
import { messagingService } from '../../lib/services'
import { requestOpenConversation } from '../../lib/messaging/deepLink'
import { subscribeMessagingStream } from '../../lib/messaging/useMessagingStream'
import { Icon } from '../ui/Icons'

function when(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(date)
}

/**
 * The application-wide message bell.
 *
 * It reads the same persisted notifications the messaging panel uses. A short
 * visible-tab refresh keeps the count honest, while opening one hands the
 * conversation to the header panel without leaving the current page.
 */
export function NotificationBell() {
  const session = useEngineSession()
  const token = session.token
  const [items, setItems] = useState<MessagingNotification[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  const load = useCallback(async () => {
    if (!token) return
    setLoading(true)
    const result = await messagingService.notifications(false, { token })
    setLoading(false)
    if (result.status === 'ok') setItems(result.data)
  }, [token])

  // A delivered notification refreshes the list once, without polling. The slow
  // interval below only reconciles a notification that arrived while suspended.
  useEffect(() => {
    if (!token) return
    let timer: number | null = null
    const unsubscribe = subscribeMessagingStream(token, (event) => {
      if (event.type !== 'notification' && event.type !== 'reconnect') return
      if (timer !== null) return
      timer = window.setTimeout(() => {
        timer = null
        void load()
      }, 300)
    })
    return () => {
      if (timer !== null) window.clearTimeout(timer)
      unsubscribe()
    }
  }, [load, token])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load()
    }, 120_000)
    const onFocus = () => void load()
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void load()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [load])

  useEffect(() => {
    if (!open) return
    const close = (restoreFocus = false) => {
      setOpen(false)
      if (restoreFocus) trigger.current?.focus({ preventScroll: true })
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      close(true)
    }
    const onPointerDown = (event: PointerEvent) => {
      if (root.current?.contains(event.target as Node)) return
      close()
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  const unread = items.filter((item) => !item.read_at).length

  async function openNotification(item: MessagingNotification) {
    if (token) await messagingService.readNotification(item.id, { token })
    setItems((current) =>
      current.map((row) =>
        row.id === item.id ? { ...row, read_at: row.read_at ?? new Date().toISOString() } : row,
      ),
    )
    requestOpenConversation(item.conversation_id)
    setOpen(false)
  }

  async function markAllRead() {
    if (!token) return
    const result = await messagingService.readAllNotifications({ token })
    if (result.status === 'ok') {
      const at = new Date().toISOString()
      setItems((current) => current.map((item) => ({ ...item, read_at: item.read_at ?? at })))
    }
  }

  if (!token) return null

  return (
    <div className="hub-bell" ref={root}>
      <button
        ref={trigger}
        type="button"
        className="hub-bell__trigger"
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          const next = !open
          setOpen(next)
          if (next) void load()
        }}
      >
        <Icon name="bell" size={17} />
        {unread > 0 ? (
          <span className="hub-bell__count" aria-hidden="true">
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="hub-bell__panel" role="dialog" aria-label="Message notifications">
          <div className="hub-bell__head">
            <div>
              <p className="mono hub-bell__eyebrow">Notifications</p>
              <h3>{unread} unread</h3>
            </div>
            <button
              type="button"
              className="hub-bell__close"
              aria-label="Close notifications"
              onClick={() => setOpen(false)}
            >
              <Icon name="close" size={14} />
            </button>
          </div>

          {loading && items.length === 0 ? (
            <p className="hub-bell__empty">Loading notifications…</p>
          ) : items.length === 0 ? (
            <p className="hub-bell__empty">No message notifications yet.</p>
          ) : (
            <ul className="hub-bell__list">
              {items.map((item) => (
                <li key={item.id} data-unread={item.read_at ? undefined : ''}>
                  <button type="button" onClick={() => void openNotification(item)}>
                    <span className="hub-bell__kind mono">{item.kind}</span>
                    <strong>{item.conversation_title}</strong>
                    <span className="hub-bell__preview">
                      {item.actor_name}: {item.preview}
                    </span>
                    <small className="mono">{when(item.created_at)}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            className="hub-bell__mark"
            onClick={() => void markAllRead()}
            disabled={unread === 0}
          >
            Mark all read
          </button>
        </div>
      ) : null}
    </div>
  )
}
