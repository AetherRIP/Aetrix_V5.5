import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useEngineSession } from '../../lib/api/session'
import type {
  MessagingConversation,
  MessagingDirectoryUser,
  MessagingMessage,
} from '../../lib/api/types'
import { messagingService } from '../../lib/services'
import type {
  MessagingStreamEvent,
  MessagingStreamMessageEvent,
} from '../../lib/messaging/stream'
import { subscribeMessagingStream } from '../../lib/messaging/useMessagingStream'
import {
  OPEN_CONVERSATION_EVENT,
  OPEN_MESSAGES_EVENT,
  takeOpenConversationRequest,
  type OpenConversationDetail,
} from '../../lib/messaging/deepLink'
import { Icon } from '../ui/Icons'

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

function shortTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(date)
}

function stamp(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return shortTime(value)
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date)
}

function roleLabel(role: string) {
  return role
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/^\w/, (letter) => letter.toUpperCase())
}

function newClientId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

type Notice = { tone: 'ok' | 'error'; text: string }

/**
 * Messaging as a global header utility.
 *
 * State is deliberately split: panel visibility (`open`), the active
 * conversation id (`activeId`, mirrored in a ref for async guards), the
 * conversation list, the loaded history and the draft. Nothing here derives
 * the active conversation from list order or list refreshes, and background
 * refreshes only replace data — they never select a conversation.
 */
export function MessagingPanel() {
  const session = useEngineSession()
  const token = session.token

  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'list' | 'new'>('list')
  const [conversations, setConversations] = useState<MessagingConversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [listVisible, setListVisible] = useState(true)
  const [messages, setMessages] = useState<MessagingMessage[]>([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingThread, setLoadingThread] = useState(false)
  const [query, setQuery] = useState('')
  const [directory, setDirectory] = useState<MessagingDirectoryUser[]>([])
  const [directoryLoading, setDirectoryLoading] = useState(false)

  const activeIdRef = useRef<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const openRef = useRef(false)
  const readTimer = useRef<number | null>(null)
  const listRefreshTimer = useRef<number | null>(null)
  const threadRefreshTimer = useRef<number | null>(null)
  const streamHandlers = useRef<{ onEvent: (event: MessagingStreamEvent) => void }>({
    onEvent: () => {},
  })
  const myId = session.me?.user_id ?? null

  const active = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? null,
    [activeId, conversations],
  )
  const unread = conversations.reduce((total, item) => total + Math.max(0, item.unread_count), 0)

  /**
   * Replace list data only. The one deliberate exception is a conversation
   * that no longer exists for this account: the selection is cleared with an
   * explanation instead of silently falling back to another conversation.
   */
  const applyConversations = useCallback((rows: MessagingConversation[]) => {
    setConversations(rows)
    const wanted = activeIdRef.current
    if (wanted && !rows.some((row) => row.id === wanted)) {
      activeIdRef.current = null
      setActiveId(null)
      setListVisible(true)
      setNotice({ tone: 'error', text: 'That conversation is no longer available to you.' })
    }
  }, [])

  const refreshConversations = useCallback(async () => {
    if (!token) return
    const result = await messagingService.conversations(undefined, { token })
    if (result.status === 'ok') applyConversations(result.data)
    else setNotice({ tone: 'error', text: result.reason })
    setLoadingList(false)
  }, [applyConversations, token])

  /** Mirror of the list for event handlers that must not depend on render order. */
  const conversationsRef = useRef<MessagingConversation[]>([])
  useEffect(() => {
    conversationsRef.current = conversations
  }, [conversations])

  /**
   * The open thread was read while a message arrived, so acknowledge it a
   * moment later instead of on every keystroke of a burst.
   */
  const scheduleRead = useCallback(
    (conversationId: string) => {
      if (!token) return
      if (readTimer.current) window.clearTimeout(readTimer.current)
      readTimer.current = window.setTimeout(() => {
        readTimer.current = null
        if (activeIdRef.current !== conversationId) return
        void messagingService.markRead(conversationId, { token }).then((result) => {
          if (result.status !== 'ok') return
          setConversations((current) =>
            current.map((row) =>
              row.id === conversationId ? { ...row, unread_count: 0 } : row,
            ),
          )
        })
      }, 400)
    },
    [token],
  )

  /**
   * A message for a conversation this account does not hold yet (a first direct
   * message, or a channel joined elsewhere) needs the list once.
   */
  const refreshListSoon = useCallback(() => {
    if (listRefreshTimer.current) return
    listRefreshTimer.current = window.setTimeout(() => {
      listRefreshTimer.current = null
      void refreshConversations()
    }, 1_500)
  }, [refreshConversations])

  /** Coalesced re-read of the open thread, used when an event carries no body. */
  const refreshThreadSoon = useCallback(() => {
    if (threadRefreshTimer.current) return
    threadRefreshTimer.current = window.setTimeout(() => {
      threadRefreshTimer.current = null
      const wanted = activeIdRef.current
      if (!openRef.current || !token || !wanted) return
      void messagingService.messages(wanted, { limit: 50 }, { token }).then((page) => {
        if (page.status === 'ok' && activeIdRef.current === wanted) setMessages(page.data.items)
      })
    }, 250)
  }, [token])

  /**
   * Apply one persisted message event. The engine only emits after the row is
   * committed, so this is delivery of stored data, not an optimistic guess. The
   * selection is read from a ref and is never changed here.
   */
  const applyStreamMessage = useCallback(
    (event: MessagingStreamMessageEvent) => {
      // An engine build without stream payloads sends identifiers only. Without
      // the stored body there is nothing to render, so read the thread instead
      // of drawing an empty bubble.
      if (typeof event.body !== 'string') {
        refreshThreadSoon()
        refreshListSoon()
        return
      }
      const conversationId = event.conversation_id
      const selected = activeIdRef.current === conversationId
      const reading =
        selected && openRef.current && document.visibilityState === 'visible'
      const mine = event.sender_id === myId
      const known = conversationsRef.current.some((row) => row.id === conversationId)
      if (!known) refreshListSoon()
      setConversations((current) =>
        current.map((row) => {
          if (row.id !== conversationId) return row
          let unread = row.unread_count
          if (reading) unread = 0
          else if (!mine && !event.deleted) unread += 1
          return {
            ...row,
            unread_count: unread,
            last_message: event.deleted ? 'Message removed' : event.body,
            last_message_at: event.created_at,
          }
        }),
      )
      if (reading) scheduleRead(conversationId)

      if (!selected) return
      setMessages((current) => {
        const index = current.findIndex((message) => message.id === event.message_id)
        if (index >= 0) {
          const next = current.slice()
          next[index] = {
            ...next[index],
            body: event.body,
            edited_at: event.edited ? event.created_at : next[index].edited_at,
            deleted: event.deleted,
          }
          return next
        }
        const incoming: MessagingMessage = {
          id: event.message_id,
          conversation_id: conversationId,
          sender_id: event.sender_id,
          sender_name: event.sender_name,
          // Display only; the engine re-authorizes every action on the message.
          sender_role: 'TEACHER',
          body: event.body,
          created_at: event.created_at,
          edited_at: event.edited ? event.created_at : null,
          deleted: event.deleted,
          pinned: false,
          can_edit: false,
          can_delete: false,
          reply_to: null,
        }
        return [...current, incoming].sort((left, right) =>
          left.created_at < right.created_at ? -1 : left.created_at > right.created_at ? 1 : 0,
        )
      })
    },
    [myId, refreshListSoon, refreshThreadSoon, scheduleRead],
  )

  /** A notification for an unseen conversation means the list is stale. */
  const applyStreamNotification = useCallback(
    (conversationId: string) => {
      if (!conversationsRef.current.some((row) => row.id === conversationId)) {
        refreshListSoon()
      }
    },
    [refreshListSoon],
  )

  /** After a drop, re-read stored state instead of trusting the gap. */
  const reconcile = useCallback(async () => {
    await refreshConversations()
    const wanted = activeIdRef.current
    if (!openRef.current || !token || !wanted) return
    const page = await messagingService.messages(wanted, { limit: 50 }, { token })
    if (page.status === 'ok' && activeIdRef.current === wanted) {
      setMessages(page.data.items)
    }
  }, [refreshConversations, token])

  useEffect(() => {
    streamHandlers.current = {
      onEvent: (event) => {
        if (event.type === 'reconnect') void reconcile()
        else if (event.type === 'message') applyStreamMessage(event)
        else applyStreamNotification(event.conversation_id)
      },
    }
  }, [applyStreamMessage, applyStreamNotification, reconcile])

  useEffect(() => {
    openRef.current = open
  }, [open])

  // One authorized stream per signed-in session, shared with the header bell.
  // It reconnects on its own and reconciles from history after a gap; nothing
  // here polls for messages.
  useEffect(() => {
    if (!token) return
    return subscribeMessagingStream(token, (event) => streamHandlers.current.onEvent(event))
  }, [token])

  useEffect(
    () => () => {
      if (readTimer.current) window.clearTimeout(readTimer.current)
      if (listRefreshTimer.current) window.clearTimeout(listRefreshTimer.current)
      if (threadRefreshTimer.current) window.clearTimeout(threadRefreshTimer.current)
    },
    [],
  )

  /** Explicit selection. Only user actions call this. */
  const selectConversation = useCallback((conversationId: string) => {
    activeIdRef.current = conversationId
    setActiveId(conversationId)
    setListVisible(false)
    setMode('list')
    setQuery('')
    setNotice(null)
  }, [])

  const openConversationFromNotice = useCallback(
    (conversationId: string) => {
      setOpen(true)
      selectConversation(conversationId)
      void refreshConversations()
    },
    [refreshConversations, selectConversation],
  )

  const openPanel = useCallback(() => {
    setOpen(true)
    setMode('list')
    void refreshConversations()
  }, [refreshConversations])

  // Load the list once for the unread badge. The stream already updates rows as
  // messages are committed; this slow reconciliation only covers an event that
  // was never seen (for example while the tab was suspended), and it never
  // touches the active conversation.
  useEffect(() => {
    if (!token) return
    let cancelled = false
    const load = async () => {
      const result = await messagingService.conversations(undefined, { token })
      if (cancelled) return
      if (result.status === 'ok') applyConversations(result.data)
      setLoadingList(false)
    }
    void load()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load()
    }, 120_000)
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load()
    }
    window.addEventListener('focus', onVisible)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      window.removeEventListener('focus', onVisible)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [applyConversations, token])

  // Load history for the selected id. A late response for a previous
  // conversation is discarded by comparing with the ref, so switching threads
  // can never be undone by an in-flight fetch.
  useEffect(() => {
    if (!open || !token || !activeId) return
    const wanted = activeId
    let cancelled = false
    setLoadingThread(true)
    setMessages([])
    void messagingService.messages(wanted, { limit: 50 }, { token }).then((result) => {
      if (cancelled || activeIdRef.current !== wanted) return
      if (result.status === 'ok') {
        setMessages(result.data.items)
        setNotice(null)
      } else {
        setNotice({ tone: 'error', text: result.reason })
      }
      setLoadingThread(false)
    })
    void messagingService.markRead(wanted, { token }).then((result) => {
      if (cancelled || result.status !== 'ok' || activeIdRef.current !== wanted) return
      setConversations((current) =>
        current.map((row) => (row.id === wanted ? { ...row, unread_count: 0 } : row)),
      )
    })
    return () => {
      cancelled = true
    }
  }, [activeId, open, token])

  // Deep links: the notification bell and the /messages compatibility route
  // ask this panel to open instead of navigating anywhere.
  useEffect(() => {
    if (!token) return
    const onMessages = () => openPanel()
    const onConversation = (event: Event) => {
      const detail = (event as CustomEvent<OpenConversationDetail>).detail
      if (detail?.conversationId) openConversationFromNotice(detail.conversationId)
    }
    window.addEventListener(OPEN_MESSAGES_EVENT, onMessages)
    window.addEventListener(OPEN_CONVERSATION_EVENT, onConversation)
    const saved = takeOpenConversationRequest()
    if (saved) openConversationFromNotice(saved)
    return () => {
      window.removeEventListener(OPEN_MESSAGES_EVENT, onMessages)
      window.removeEventListener(OPEN_CONVERSATION_EVENT, onConversation)
    }
  }, [openConversationFromNotice, openPanel, token])

  // Escape closes; a pointer outside dismisses. Neither clears the selection.
  useEffect(() => {
    if (!open) return
    const close = (restoreFocus: boolean) => {
      setOpen(false)
      if (restoreFocus) triggerRef.current?.focus({ preventScroll: true })
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      close(true)
    }
    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return
      close(false)
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  useEffect(() => {
    if (open) panelRef.current?.focus({ preventScroll: true })
  }, [open])

  useEffect(() => {
    if (!open) return
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, open, activeId])

  useEffect(() => {
    if (mode !== 'new' || !token || directory.length > 0) return
    setDirectoryLoading(true)
    void messagingService.directory(undefined, { token }).then((result) => {
      setDirectoryLoading(false)
      if (result.status === 'ok') setDirectory(result.data)
      else setNotice({ tone: 'error', text: result.reason })
    })
  }, [directory.length, mode, token])

  async function sendMessage(event: React.FormEvent) {
    event.preventDefault()
    const conversation = active
    if (!token || !conversation || !draft.trim() || sending) return
    if (!conversation.can_post) {
      setNotice({ tone: 'error', text: 'You cannot post in this conversation.' })
      return
    }
    const body = draft.trim()
    const mentioned = directory
      .filter((person) => body.toLocaleLowerCase().includes(`@${person.display_name.toLocaleLowerCase()}`))
      .map((person) => person.id)
    const conversationId = conversation.id
    setSending(true)
    const result = await messagingService.send(
      conversationId,
      {
        body,
        client_id: newClientId(),
        reply_to_id: null,
        mentioned_user_ids: mentioned,
      },
      { token },
    )
    setSending(false)
    if (result.status !== 'ok') {
      setNotice({ tone: 'error', text: `Not sent: ${result.reason}` })
      return
    }
    setDraft('')
    setNotice(null)
    // Only touch the open thread; a send that resolves after the user moved on
    // must not repopulate another conversation's history.
    if (activeIdRef.current === conversationId) {
      const stored = result.data
      setMessages((current) =>
        current.some((message) => message.id === stored.id) ? current : [...current, stored],
      )
    }
    setConversations((current) =>
      current.map((row) =>
        row.id === conversationId
          ? { ...row, last_message: body, last_message_at: result.data.created_at, unread_count: 0 }
          : row,
      ),
    )
  }

  async function startDirect(person: MessagingDirectoryUser) {
    if (!token) return
    const result = await messagingService.createDirect(person.id, { token })
    if (result.status !== 'ok') {
      setNotice({ tone: 'error', text: result.reason })
      return
    }
    const created = result.data
    setConversations((current) =>
      current.some((row) => row.id === created.id)
        ? current.map((row) => (row.id === created.id ? created : row))
        : [created, ...current],
    )
    selectConversation(created.id)
  }

  if (!token) return null

  const needle = query.trim().toLocaleLowerCase()
  const filtered = needle
    ? conversations.filter((conversation) =>
        conversation.title.toLocaleLowerCase().includes(needle),
      )
    : conversations
  const shown = activeId && !listVisible ? 'thread' : 'list'

  return (
    <div className="msgp" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="hub-bell__trigger"
        aria-label={unread > 0 ? `Messages, ${unread} unread` : 'Messages'}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Messages"
        onClick={() => {
          if (open) {
            setOpen(false)
            return
          }
          openPanel()
        }}
      >
        <Icon name="message" size={17} />
        {unread > 0 ? (
          <span className="hub-bell__count" aria-hidden="true">
            {unread > 99 ? '99+' : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div
          ref={panelRef}
          className="msgp__panel"
          role="dialog"
          aria-label="Messages"
          tabIndex={-1}
          data-view={shown}
        >
          <header className="msgp__head">
            <div className="msgp__heading">
              <p className="mono msgp__eyebrow">Workspace messaging</p>
              <h3>
                Messages
                {unread > 0 ? <span className="msgp__head-count">{unread > 99 ? '99+' : unread}</span> : null}
              </h3>
            </div>
            <div className="msgp__head-actions">
              <button
                type="button"
                className="msgp__icon"
                aria-label="Start a new conversation"
                title="New conversation"
                aria-pressed={mode === 'new'}
                onClick={() => {
                  setMode(mode === 'new' ? 'list' : 'new')
                  setNotice(null)
                }}
              >
                <Icon name="pen" size={15} />
              </button>
              <button
                type="button"
                className="msgp__icon"
                aria-label="Close messages"
                title="Close"
                onClick={() => {
                  setOpen(false)
                  triggerRef.current?.focus({ preventScroll: true })
                }}
              >
                <Icon name="close" size={15} />
              </button>
            </div>
          </header>

          {mode === 'new' ? (
            <div className="msgp__pane">
              <div className="msgp__sub">
                <button
                  type="button"
                  className="msgp__icon"
                  aria-label="Back to conversations"
                  onClick={() => setMode('list')}
                >
                  <Icon name="arrow" size={15} />
                </button>
                <strong>New conversation</strong>
              </div>
              {directoryLoading ? (
                <p className="msgp__empty">Loading your workspace colleagues…</p>
              ) : directory.length === 0 ? (
                <p className="msgp__empty">
                  No colleagues are available in this workspace. Platform administrators do not gain
                  access to workspace messages.
                </p>
              ) : (
                <ul className="msgp__people">
                  {directory.map((person) => (
                    <li key={person.id}>
                      <span className="msgp__avatar" aria-hidden="true">
                        {initials(person.display_name) || '?'}
                      </span>
                      <span className="msgp__person">
                        <strong>{person.display_name}</strong>
                        <small>{roleLabel(person.role)}</small>
                      </span>
                      <button
                        type="button"
                        className="msgp__pill"
                        onClick={() => void startDirect(person)}
                      >
                        Message
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : shown === 'thread' && active ? (
            <div className="msgp__pane msgp__pane--thread">
              <div className="msgp__sub">
                <button
                  type="button"
                  className="msgp__icon"
                  aria-label="Back to conversations"
                  onClick={() => setListVisible(true)}
                >
                  <Icon name="arrow" size={15} />
                </button>
                <span className="msgp__sub-title">
                  <strong>{active.title}</strong>
                  <small>
                    {active.kind === 'CHANNEL' ? 'Workspace channel' : 'Direct message'}
                    {active.archived ? ' · archived' : ''}
                  </small>
                </span>
              </div>

              <div className="msgp__messages" aria-live="polite">
                {loadingThread ? (
                  <p className="msgp__empty">Loading stored history…</p>
                ) : messages.length === 0 ? (
                  <p className="msgp__empty">
                    No messages yet. {active.can_post ? 'Write the first one below.' : 'Only managers can post here.'}
                  </p>
                ) : (
                  messages.map((message) => (
                    <article
                      key={message.id}
                      className="msgp__message"
                      data-deleted={message.deleted ? '' : undefined}
                    >
                      <div className="msgp__meta">
                        <strong>{message.sender_name}</strong>
                        <span className="mono">{shortTime(message.created_at)}</span>
                        {message.edited_at && !message.deleted ? (
                          <span className="mono">edited</span>
                        ) : null}
                      </div>
                      {message.reply_to ? (
                        <p className="msgp__reply">
                          <span>{message.reply_to.sender_name}</span>{' '}
                          {message.reply_to.deleted ? 'Message removed' : message.reply_to.body}
                        </p>
                      ) : null}
                      <p className="msgp__body">
                        {message.deleted ? <em>Message removed</em> : message.body}
                      </p>
                    </article>
                  ))
                )}
                <div ref={endRef} />
              </div>

              {notice ? (
                <p className="msgp__notice" data-tone={notice.tone} role={notice.tone === 'error' ? 'alert' : 'status'}>
                  {notice.text}
                </p>
              ) : null}

              <form className="msgp__composer" onSubmit={sendMessage}>
                <label className="visually-hidden" htmlFor="msgp-composer">
                  Message {active.title}
                </label>
                <textarea
                  id="msgp-composer"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                  placeholder={
                    active.archived
                      ? 'This channel is archived.'
                      : active.can_post
                        ? `Message ${active.title}`
                        : 'Only workspace managers can post here.'
                  }
                  maxLength={4000}
                  rows={2}
                  disabled={!active.can_post || sending}
                />
                <button
                  type="submit"
                  className="msgp__send"
                  disabled={!active.can_post || sending || !draft.trim()}
                  aria-label="Send message"
                >
                  {sending ? 'Sending…' : 'Send'}
                </button>
              </form>
              <p className="msgp__hint">Plain text · Enter sends · Shift+Enter adds a line</p>
            </div>
          ) : (
            <div className="msgp__pane">
              {notice ? (
                <p className="msgp__notice" data-tone={notice.tone} role="alert">
                  {notice.text}
                </p>
              ) : null}
              <label className="msgp__search">
                <span className="visually-hidden">Search conversations</span>
                <Icon name="search" size={14} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search conversations"
                  type="search"
                />
              </label>

              {loadingList && conversations.length === 0 ? (
                <p className="msgp__empty">Loading conversations…</p>
              ) : filtered.length === 0 ? (
                <p className="msgp__empty">
                  {conversations.length === 0
                    ? 'No conversations yet. Use New conversation to message a colleague.'
                    : 'No conversation matches this search.'}
                </p>
              ) : (
                <ul className="msgp__list">
                  {filtered.map((conversation) => (
                    <li key={conversation.id}>
                      <button
                        type="button"
                        className="msgp__row"
                        data-active={conversation.id === activeId ? '' : undefined}
                        onClick={() => selectConversation(conversation.id)}
                      >
                        <span className="msgp__avatar" aria-hidden="true">
                          {conversation.kind === 'CHANNEL'
                            ? '#'
                            : initials(conversation.title) || '?'}
                        </span>
                        <span className="msgp__row-body">
                          <span className="msgp__row-top">
                            <strong>{conversation.title}</strong>
                            <span className="mono">{stamp(conversation.last_message_at)}</span>
                          </span>
                          <span className="msgp__preview">
                            {conversation.last_message ?? 'No messages yet'}
                          </span>
                        </span>
                        {conversation.unread_count > 0 ? (
                          <span
                            className="msgp__unread"
                            aria-label={`${conversation.unread_count} unread`}
                          >
                            {conversation.unread_count > 99 ? '99+' : conversation.unread_count}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
