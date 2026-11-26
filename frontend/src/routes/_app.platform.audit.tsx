import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useAuth } from '../lib/auth/AuthProvider'
import { useEngineSession } from '../lib/api/session'
import type { ApiResult, RequestOptions } from '../lib/api/client'
import type { AuditEvent, AuditEventPage, AuditQuery } from '../lib/api/types'
import { platformService, workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/platform/audit')({
  head: () => ({ meta: [{ title: 'Audit log · Aetrix' }] }),
  component: PlatformAudit,
})

const PAGE_SIZE = 25

type Scope = 'workspace' | 'platform'

type Form = {
  scope: Scope
  action: string
  entityType: string
  entityId: string
  actor: string
  actorType: '' | 'USER' | 'SYSTEM' | 'WORKER'
  from: string
  to: string
}

type Read =
  | { state: 'loading' }
  | { state: 'ok' }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

/**
 * The audit screen reads the append-only ledger the engine already writes.
 * It offers no editing affordance because there is none: `audit_events` refuses
 * updates at the database level. Filters are applied explicitly so a half-typed
 * value does not silently change the page.
 */
function PlatformAudit() {
  const { session } = useAuth()
  const engine = useEngineSession()
  const token = session?.access_token ?? null
  const claim = session?.user?.app_metadata as Record<string, unknown> | undefined
  const claimRole = claim?.aetrix_role
  const isOwner = claimRole === 'owner' || claimRole === 'PLATFORM_OWNER'

  const initial: Form = {
    scope: isOwner ? 'platform' : 'workspace',
    action: '',
    entityType: '',
    entityId: '',
    actor: '',
    actorType: '',
    from: '',
    to: '',
  }

  const [draft, setDraft] = useState<Form>(initial)
  const [applied, setApplied] = useState<Form>(initial)
  const [tick, setTick] = useState(0)
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())

  const [rows, setRows] = useState<AuditEvent[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [retrievedAt, setRetrievedAt] = useState<string | null>(null)
  const [read, setRead] = useState<Read>({ state: 'loading' })
  const [loadingMore, setLoadingMore] = useState(false)
  const [moreError, setMoreError] = useState<string | null>(null)

  const query = toQuery(applied)
  const queryRef = useRef(query)
  queryRef.current = query
  const scope = applied.scope
  const tenantId = engine.tenantId
  const key = JSON.stringify({ scope, tenantId, applied })

  useEffect(() => {
    if (!token) {
      setRead({ state: 'unavailable', reason: 'Sign in to read the audit log.' })
      setRows([])
      return
    }
    if (scope === 'workspace' && !tenantId) {
      setRead({
        state: 'unavailable',
        reason: engine.reason ?? 'The engine has not confirmed a workspace for this account.',
      })
      setRows([])
      return
    }
    const controller = new AbortController()
    let live = true
    setRead({ state: 'loading' })
    setRows([])
    setHasMore(false)
    setNextBefore(null)
    setMoreError(null)
    void readAudit(scope, tenantId, queryRef.current, {
      token,
      signal: controller.signal,
    }).then((result) => {
      if (!live) return
      if (result.status === 'ok') {
        setRows(result.data.items)
        setHasMore(result.data.has_more)
        setNextBefore(result.data.next_before)
        setRetrievedAt(result.data.retrieved_at)
        setRead({ state: 'ok' })
      } else if (result.status === 'unavailable') {
        setRead({ state: 'unavailable', reason: result.reason })
      } else {
        setRead({ state: 'error', reason: result.reason, code: result.code })
      }
    })
    return () => {
      live = false
      controller.abort()
    }
    // `engine.reason` is only read when the workspace is missing; the key
    // already changes whenever the tenant or filters do.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, token, scope, tenantId, tick])

  const loadMore = useCallback(() => {
    if (!token || !nextBefore || loadingMore) return
    setLoadingMore(true)
    setMoreError(null)
    void readAudit(
      scope,
      tenantId,
      { ...queryRef.current, before: nextBefore },
      { token },
    ).then((result) => {
      if (result.status === 'ok') {
        setRows((current) => [...current, ...result.data.items])
        setHasMore(result.data.has_more)
        setNextBefore(result.data.next_before)
        setRetrievedAt(result.data.retrieved_at)
      } else {
        setMoreError(
          result.status === 'unavailable'
            ? result.reason
            : `The next page could not be read: ${result.reason}`,
        )
      }
      setLoadingMore(false)
    })
  }, [token, nextBefore, loadingMore, scope, tenantId])

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setApplied(draft)
    setOpen(new Set<string>())
    setTick((value) => value + 1)
  }

  const clear = () => {
    const reset = { ...initial, scope: draft.scope }
    setDraft(reset)
    setApplied(reset)
    setOpen(new Set<string>())
    setTick((value) => value + 1)
  }

  const toggle = (id: string) => {
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const filtered =
    applied.action.trim() !== '' ||
    applied.actor.trim() !== '' ||
    applied.entityType.trim() !== '' ||
    applied.entityId.trim() !== '' ||
    applied.actorType !== '' ||
    applied.from !== '' ||
    applied.to !== ''
  const platform = applied.scope === 'platform'
  const columns = platform ? 6 : 5

  return (
    <div className="app-stack">
      <div className="app-toolbar">
        <div className="app-toolbar__tabs" role="group" aria-label="Audit scope">
          <button
            type="button"
            className={platform ? 'app-tab' : 'app-tab is-active'}
            aria-pressed={!platform}
            onClick={() => {
              const next = { ...applied, scope: 'workspace' as Scope }
              setDraft(next)
              setApplied(next)
              setTick((value) => value + 1)
            }}
          >
            This workspace
          </button>
          {isOwner ? (
            <button
              type="button"
              className={platform ? 'app-tab is-active' : 'app-tab'}
              aria-pressed={platform}
              onClick={() => {
                const next = { ...applied, scope: 'platform' as Scope }
                setDraft(next)
                setApplied(next)
                setTick((value) => value + 1)
              }}
            >
              All workspaces
            </button>
          ) : null}
        </div>
        <button
          type="button"
          className="btn btn--small btn--outline"
          onClick={() => setTick((value) => value + 1)}
          disabled={read.state === 'loading'}
        >
          Refresh
        </button>
      </div>

      <form className="app-form" onSubmit={submit} aria-label="Audit log filters">
        <div className="audit-filters">
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="audit-action">
              Action
            </label>
            <input
              id="audit-action"
              className="app-input"
              value={draft.action}
              maxLength={120}
              placeholder="exam.created"
              onChange={(event) => setDraft({ ...draft, action: event.target.value })}
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="audit-actor">
              Actor
            </label>
            <input
              id="audit-actor"
              className="app-input"
              value={draft.actor}
              maxLength={320}
              placeholder="name or account id"
              onChange={(event) => setDraft({ ...draft, actor: event.target.value })}
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="audit-actor-type">
              Actor kind
            </label>
            <select
              id="audit-actor-type"
              className="app-input"
              value={draft.actorType}
              onChange={(event) =>
                setDraft({ ...draft, actorType: event.target.value as Form['actorType'] })
              }
            >
              <option value="">Any</option>
              <option value="USER">Person</option>
              <option value="SYSTEM">Engine</option>
              <option value="WORKER">Worker</option>
            </select>
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="audit-entity-type">
              Resource type
            </label>
            <input
              id="audit-entity-type"
              className="app-input"
              value={draft.entityType}
              maxLength={80}
              placeholder="correction_job"
              onChange={(event) => setDraft({ ...draft, entityType: event.target.value })}
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="audit-entity-id">
              Resource id
            </label>
            <input
              id="audit-entity-id"
              className="app-input"
              value={draft.entityId}
              maxLength={200}
              placeholder="exact identifier"
              onChange={(event) => setDraft({ ...draft, entityId: event.target.value })}
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="audit-from">
              From (UTC)
            </label>
            <input
              id="audit-from"
              type="date"
              className="app-input"
              value={draft.from}
              onChange={(event) => setDraft({ ...draft, from: event.target.value })}
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="audit-to">
              To (UTC)
            </label>
            <input
              id="audit-to"
              type="date"
              className="app-input"
              value={draft.to}
              onChange={(event) => setDraft({ ...draft, to: event.target.value })}
            />
          </div>
          <div className="app-inline-actions">
            <button type="submit" className="btn btn--small btn--primary">
              Apply filters
            </button>
            <button type="button" className="btn btn--small btn--outline" onClick={clear}>
              Clear
            </button>
          </div>
        </div>
      </form>

      <p className="app-hint">
        Event times are recorded by the engine. This page was{' '}
        {retrievedAt ? `retrieved ${stamp(retrievedAt)}` : 'not read yet'}; the two are
        different facts. Date filters use UTC.
      </p>

      {read.state === 'loading' ? (
        <p className="app-hint mono" role="status" aria-live="polite">
          Reading the audit ledger…
        </p>
      ) : null}

      {read.state === 'unavailable' ? (
        <StatePanel
          tone="wip"
          title="The engine did not answer this screen"
          capability="GET /api/v1/workspaces/{id}/audit"
        >
          <p>{read.reason}</p>
        </StatePanel>
      ) : null}

      {read.state === 'error' ? (
        <StatePanel
          tone="error"
          title="The audit log could not be read"
          capability={platform ? 'GET /api/v1/admin/audit' : 'GET /api/v1/workspaces/{id}/audit'}
        >
          <p>{read.reason}</p>
          <p>
            {read.code === 403
              ? 'The engine refused this account. Platform-wide audit is reserved for the platform owner; switch to “This workspace”, or ask the owner to review your role.'
              : 'Nothing is being shown as zero: an unread ledger is not an empty ledger.'}
          </p>
        </StatePanel>
      ) : null}

      {read.state === 'ok' ? (
        <Panel
          title={platform ? 'Audit trail · all workspaces' : 'Audit trail · this workspace'}
          note={
            retrievedAt
              ? `${rows.length} event${rows.length === 1 ? '' : 's'} · read ${stamp(retrievedAt)}`
              : undefined
          }
        >
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">
                Append-only audit events, newest first, with actor, action and resource
              </caption>
              <thead>
                <tr>
                  <th scope="col">Event time</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Action</th>
                  <th scope="col">Resource</th>
                  {platform ? <th scope="col">Workspace</th> : null}
                  <th scope="col">
                    <span className="visually-hidden">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.length > 0 ? (
                  rows.map((row) => {
                    const expanded = open.has(row.id)
                    return [
                      <tr key={row.id}>
                        <td>
                          <time className="mono" dateTime={row.created_at} title={row.created_at}>
                            {stamp(row.created_at)}
                          </time>
                        </td>
                        <td>
                          <span className="audit-cell">
                            <span>{row.actor_label ?? row.actor_id ?? 'Unattributed'}</span>
                            <span className="chip app-chip" data-tone="neutral">
                              {row.actor_type}
                            </span>
                          </span>
                        </td>
                        <td>
                          <span className="audit-cell">
                            <span>{eventLabel(row.action)}</span>
                            <code className="app-hint">{row.action}</code>
                          </span>
                        </td>
                        <td>
                          <span className="audit-cell">
                            <span>{row.entity_type}</span>
                            <code className="app-hint">{row.entity_id}</code>
                          </span>
                        </td>
                        {platform ? (
                          <td>{row.tenant_name ?? row.tenant_id ?? 'Platform'}</td>
                        ) : null}
                        <td className="audit-expand">
                          <button
                            type="button"
                            className="btn btn--small btn--outline"
                            aria-expanded={expanded}
                            onClick={() => toggle(row.id)}
                          >
                            {expanded ? 'Hide' : 'Details'}
                          </button>
                        </td>
                      </tr>,
                      expanded ? (
                        <tr key={`${row.id}-detail`}>
                          <td colSpan={columns} className="data-table__detail">
                            <EventDetail event={row} />
                          </td>
                        </tr>
                      ) : null,
                    ]
                  })
                ) : (
                  <tr>
                    <td colSpan={columns} className="data-table__empty">
                      {filtered
                        ? 'No events match these filters. Narrowing a filter never invents a row; clear it to read the whole trail.'
                        : 'No audit events have been recorded in this scope yet. Rows appear here when the engine writes one; nothing is seeded for display.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {moreError ? (
            <p className="app-hint" role="alert">
              {moreError}
            </p>
          ) : null}

          <div className="app-inline-actions">
            <button
              type="button"
              className="btn btn--small btn--outline"
              onClick={loadMore}
              disabled={!hasMore || loadingMore}
            >
              {loadingMore ? 'Reading…' : hasMore ? 'Load older events' : 'End of the trail'}
            </button>
          </div>
        </Panel>
      ) : null}

      {read.state === 'ok' && rows.length === 0 ? (
        <StatePanel
          tone="empty"
          title={filtered ? 'No events match these filters' : 'No audit events recorded yet'}
        >
          <p>
            This table reads the tenant’s append-only <code>audit_events</code> rows. An empty
            result is reported as empty; the screen never fabricates entries to look complete.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

function toQuery(form: Form): AuditQuery {
  return {
    action: form.action.trim() || undefined,
    entity_type: form.entityType.trim() || undefined,
    entity_id: form.entityId.trim() || undefined,
    actor: form.actor.trim() || undefined,
    actor_type: form.actorType || undefined,
    date_from: form.from ? `${form.from}T00:00:00.000Z` : undefined,
    date_to: form.to ? `${form.to}T23:59:59.999Z` : undefined,
    limit: PAGE_SIZE,
  }
}

function readAudit(
  scope: Scope,
  tenantId: string | null,
  query: AuditQuery,
  options: RequestOptions,
): Promise<ApiResult<AuditEventPage>> {
  if (scope === 'platform') return platformService.audit(query, options)
  if (!tenantId) {
    return Promise.resolve({
      status: 'unavailable',
      reason: 'A workspace session is required to read this ledger.',
    })
  }
  return workspaceService.audit(tenantId, query, options)
}

function stamp(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** `result.approved` reads as “Result approved”; the exact code stays visible. */
function eventLabel(action: string): string {
  const parts = action.split('.').filter(Boolean)
  const words = (parts.length > 1 ? parts.slice(1) : parts).join(' ').replace(/[_-]/g, ' ')
  if (!words) return action
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function EventDetail({ event }: { event: AuditEvent }) {
  const entries = Object.entries(event.detail)
  return (
    <div>
      <dl className="audit-detail">
        <dt>Event id</dt>
        <dd>{event.id}</dd>
        {event.request_id ? (
          <>
            <dt>Request id</dt>
            <dd>{event.request_id}</dd>
          </>
        ) : null}
        {event.before_hash ? (
          <>
            <dt>Before digest</dt>
            <dd>{event.before_hash}</dd>
          </>
        ) : null}
        {event.after_hash ? (
          <>
            <dt>After digest</dt>
            <dd>{event.after_hash}</dd>
          </>
        ) : null}
        {entries.map(([name, value]) => (
          <DetailEntry key={name} name={name} value={value} />
        ))}
      </dl>
      {entries.length === 0 ? (
        <p className="app-hint">No additional metadata was recorded with this event.</p>
      ) : null}
    </div>
  )
}

function DetailEntry({ name, value }: { name: string; value: unknown }) {
  return (
    <>
      <dt>{name.replace(/[_-]/g, ' ')}</dt>
      <dd>{formatValue(value)}</dd>
    </>
  )
}
