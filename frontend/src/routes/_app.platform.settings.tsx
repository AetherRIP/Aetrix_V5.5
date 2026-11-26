import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { Panel } from '../components/app/PageBlocks'
import { useAuth } from '../lib/auth/AuthProvider'
import { formatDateTime } from '../lib/format'
import type { ApiResult } from '../lib/api/client'
import type {
  PlatformSettings as PlatformSettingsRow,
  RetentionPreview,
  RetentionSweep,
} from '../lib/api/types'
import { platformSettingsService } from '../lib/services'

export const Route = createFileRoute('/_app/platform/settings')({
  head: () => ({ meta: [{ title: 'Platform settings · Aetrix' }] }),
  component: PlatformSettings,
})

type Read =
  | { state: 'loading' }
  | { state: 'ok' }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

type Draft = {
  template: string
  retentionDays: string
  auditTypes: string[]
}

function draftOf(settings: PlatformSettingsRow): Draft {
  return {
    template: settings.default_workspace_template,
    retentionDays: String(settings.uploaded_script_retention_days),
    auditTypes: [...settings.audit_view_allowed_account_types],
  }
}

/**
 * The single persisted platform configuration row.
 *
 * Every value shown here came from `GET /admin/settings`; a save is reported as
 * successful only after the engine returns the persisted row. A 403 is shown as
 * a refusal, and a missing API as unavailable — the form is never rendered as
 * editable when it cannot read the current values.
 */
function PlatformSettings() {
  const { session } = useAuth()
  const token = session?.access_token ?? null
  const claim = session?.user?.app_metadata as Record<string, unknown> | undefined
  const claimRole = claim?.aetrix_role
  const isOwner = claimRole === 'owner' || claimRole === 'PLATFORM_OWNER'

  const [read, setRead] = useState<Read>({ state: 'loading' })
  const [settings, setSettings] = useState<PlatformSettingsRow | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  const [preview, setPreview] = useState<RetentionPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [sweeping, setSweeping] = useState(false)
  const [sweep, setSweep] = useState<RetentionSweep | null>(null)

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!token) {
        setRead({ state: 'unavailable', reason: 'Sign in with a platform account to read the settings.' })
        return
      }
      setRead({ state: 'loading' })
      void platformSettingsService.read({ token, signal }).then((result) => {
        if (result.status === 'ok') {
          setSettings(result.data)
          setDraft(draftOf(result.data))
          setRead({ state: 'ok' })
          return
        }
        if (result.status === 'unavailable') {
          setRead({ state: 'unavailable', reason: result.reason })
          return
        }
        setRead({ state: 'error', reason: result.reason, code: result.code })
      })
    },
    [token],
  )

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  const dirty =
    settings !== null &&
    draft !== null &&
    (draft.template !== settings.default_workspace_template ||
      draft.retentionDays !== String(settings.uploaded_script_retention_days) ||
      draft.auditTypes.join(',') !== [...settings.audit_view_allowed_account_types].sort().join(','))

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!token || !settings || !draft) return
    const days = Number(draft.retentionDays)
    if (!Number.isInteger(days) || days < settings.retention_min_days || days > settings.retention_max_days) {
      setNotice({
        tone: 'error',
        text: `The retention window must be a whole number of days between ${settings.retention_min_days} and ${settings.retention_max_days}.`,
      })
      return
    }
    setSaving(true)
    setNotice(null)
    const result: ApiResult<PlatformSettingsRow> = await platformSettingsService.update(
      {
        default_workspace_template: draft.template,
        uploaded_script_retention_days: days,
        audit_view_allowed_account_types: draft.auditTypes,
        expected_version: settings.version,
      },
      { token },
    )
    setSaving(false)
    if (result.status === 'ok') {
      setSettings(result.data)
      setDraft(draftOf(result.data))
      setPreview(null)
      setSweep(null)
      setConfirmed(false)
      setNotice({
        tone: 'ok',
        text: `Saved and persisted by the engine (version ${result.data.version}).`,
      })
      return
    }
    setNotice({
      tone: 'error',
      text: result.status === 'unavailable' ? result.reason : result.reason,
    })
    if (result.status === 'error' && result.code === 409) load()
  }

  async function loadPreview() {
    if (!token) return
    setPreviewing(true)
    setPreviewError(null)
    setSweep(null)
    setConfirmed(false)
    const result = await platformSettingsService.retentionPreview({ token })
    setPreviewing(false)
    if (result.status === 'ok') setPreview(result.data)
    else setPreviewError(result.reason)
  }

  async function runSweep() {
    if (!token || !preview || !settings) return
    setSweeping(true)
    setPreviewError(null)
    const result = await platformSettingsService.sweepRetention(
      { expected_retention_days: preview.retention_days, limit: 100 },
      { token },
    )
    setSweeping(false)
    if (result.status === 'ok') {
      setSweep(result.data)
      setConfirmed(false)
      setPreview(null)
      return
    }
    setPreviewError(result.reason)
    if (result.status === 'error' && result.code === 409) loadPreview()
  }

  if (read.state === 'loading') {
    return (
      <div className="app-stack">
        <Panel title="Platform defaults" note="Loading">
          <p className="panel-copy">Reading the persisted platform configuration from the engine…</p>
        </Panel>
      </div>
    )
  }

  if (read.state === 'unavailable') {
    return (
      <div className="app-stack">
        <StatePanel tone="wip" title="Platform settings are unavailable" capability="engine: platform settings API">
          <p>{read.reason}</p>
          <p>The screen cannot show current values, so it does not offer editing.</p>
        </StatePanel>
      </div>
    )
  }

  if (read.state === 'error') {
    return (
      <div className="app-stack">
        <StatePanel tone="error" title="The platform settings could not be read">
          <p>{read.reason}</p>
          {read.code === 403 ? (
            <p>This screen is restricted to platform owners and platform administrators.</p>
          ) : null}
        </StatePanel>
      </div>
    )
  }

  if (!settings || !draft) return null

  const selectedTemplate =
    settings.available_templates.find((t) => t.key === draft.template) ?? null

  return (
    <div className="app-stack">
      <Panel title="Platform defaults" note={`version ${settings.version}`}>
        <p className="panel-copy">
          One configuration row governs every workspace. Values are stored in the engine
          database, validated on the server and recorded in the append-only audit ledger.
        </p>
        <p className="panel-copy mono">
          Last updated {formatDateTime(settings.updated_at)}
          {settings.updated_by_label || settings.updated_by_subject
            ? ` by ${settings.updated_by_label ?? settings.updated_by_subject}`
            : ' · no change recorded since initialization'}
        </p>
      </Panel>

      <form className="app-form" onSubmit={save}>
        <Panel title="Default workspace template" note={selectedTemplate?.label ?? draft.template}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="platform-template">
              Template applied to a new teacher workspace
            </label>
            <select
              id="platform-template"
              value={draft.template}
              onChange={(event) => setDraft({ ...draft, template: event.target.value })}
            >
              {settings.available_templates.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <p className="panel-copy">
            {selectedTemplate?.description ??
              'This template key is not in the engine registry; a new workspace falls back to the default and the fallback is audited.'}
          </p>
          <p className="panel-copy">
            Changing this affects workspaces created after the save only. Existing workspaces are
            never restyled and keep their current members, papers and settings.
          </p>
        </Panel>

        <Panel title="Uploaded-script retention" note={`${settings.uploaded_script_retention_days} days`}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="platform-retention">
              Retain uploaded student scripts for (days)
            </label>
            <input
              id="platform-retention"
              type="number"
              min={settings.retention_min_days}
              max={settings.retention_max_days}
              step={1}
              value={draft.retentionDays}
              onChange={(event) => setDraft({ ...draft, retentionDays: event.target.value })}
            />
          </div>
          <p className="panel-copy">
            <strong>What retention removes:</strong> after the window, the stored upload and the
            rendered page images of an eligible student script are deleted from storage.
          </p>
          <p className="panel-copy">
            <strong>What is kept:</strong> the document row (hash, filename, size, timestamps),
            page text and quality verdicts, correction jobs, results, approved grades and the audit
            trail. Scripts on an active job or with an approved grade are never purged.
          </p>
          <p className="panel-copy">
            Purging is a separate, deliberate action: saving the window changes the policy, and the
            sweep below removes only what the engine reports as eligible right now.
          </p>
        </Panel>

        <Panel title="Audit-view access" note={isOwner ? 'owner-controlled' : 'owner only can change'}>
          <p className="panel-copy">
            These account types may open the <strong>platform-wide</strong> audit view, which reads
            every workspace. A workspace member's own ledger stays scoped to that workspace and is
            governed by membership, not by this list. A workspace role is never traded for the
            cross-tenant ledger.
          </p>
          <fieldset disabled={!isOwner}>
            {settings.audit_account_types.map((option) => (
              <label className="app-form__row" key={option.key}>
                <input
                  type="checkbox"
                  checked={draft.auditTypes.includes(option.key)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      auditTypes: event.target.checked
                        ? [...draft.auditTypes, option.key]
                        : draft.auditTypes.filter((key) => key !== option.key),
                    })
                  }
                />
                <span className="app-form__label">
                  {option.label} <span className="mono">({option.platform_role})</span>
                </span>
                <span className="panel-copy">{option.description}</span>
              </label>
            ))}
          </fieldset>
          {isOwner ? null : (
            <p className="panel-copy">Only the platform owner may change who can open the audit view.</p>
          )}
        </Panel>

        {notice ? (
          <p className={notice.tone === 'ok' ? 'panel-copy' : 'app-form__error'} role={notice.tone === 'ok' ? 'status' : 'alert'}>
            {notice.text}
          </p>
        ) : null}

        <div className="app-form__row">
          <button type="submit" className="btn btn--primary" disabled={!dirty || saving}>
            {saving ? 'Saving…' : 'Save platform settings'}
          </button>
          {dirty && !saving ? <span className="panel-copy">Unsaved changes</span> : null}
        </div>
      </form>

      <Panel title="Retention eligibility" note="nothing is deleted by a preview">
        <p className="panel-copy">
          The engine decides eligibility from stored rows: student documents older than the window,
          not attached to an active correction job and not carrying an approved grade.
        </p>
        <div className="app-form__row">
          <button type="button" className="btn" onClick={() => void loadPreview()} disabled={previewing || sweeping}>
            {previewing ? 'Checking…' : 'Check what is eligible now'}
          </button>
        </div>
        {previewError ? <p className="app-form__error" role="alert">{previewError}</p> : null}
        {preview ? (
          <>
            <p className="panel-copy">
              Window {preview.retention_days} days · cutoff {formatDateTime(preview.cutoff)} · scanned{' '}
              {formatDateTime(preview.scanned_at)}
            </p>
            <p className="panel-copy">
              {preview.eligible_documents} script(s), {preview.eligible_pages} page image(s),{' '}
              {preview.eligible_bytes.toLocaleString()} bytes eligible. {preview.already_purged_documents}{' '}
              already purged.
            </p>
            <ul className="rule-list">
              {preview.protected.length === 0 ? (
                <li>No older scripts are held back by an active job, an approval or missing provenance.</li>
              ) : (
                preview.protected.map((row) => (
                  <li key={row.reason}>
                    Kept: {row.documents} script(s) — {row.reason}.
                  </li>
                ))
              )}
            </ul>
            {preview.eligible_documents > 0 ? (
              <>
                <label className="app-form__row">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                  />
                  <span className="app-form__label">
                    I understand the stored files for these eligible scripts will be deleted. Records,
                    marks and audit history are kept.
                  </span>
                </label>
                <div className="app-form__row">
                  <button
                    type="button"
                    className="btn btn--danger"
                    disabled={!confirmed || sweeping}
                    onClick={() => void runSweep()}
                  >
                    {sweeping ? 'Purging…' : `Purge up to ${Math.min(100, preview.eligible_documents)} eligible script file(s)`}
                  </button>
                </div>
              </>
            ) : null}
          </>
        ) : null}
        {sweep ? (
          <p className="panel-copy" role="status">
            Purged {sweep.purged_documents} script(s) and {sweep.purged_pages} page image(s);{' '}
            {sweep.failed_documents} failed and stay eligible for a retry. Completed{' '}
            {formatDateTime(sweep.completed_at)}. Each removal is in the audit ledger.
          </p>
        ) : null}
      </Panel>
    </div>
  )
}
