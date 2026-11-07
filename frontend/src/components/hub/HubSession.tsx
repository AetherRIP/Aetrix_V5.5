import { displayName, useAuth } from '../../lib/auth/AuthProvider'
import { formatDateTime, providerLabel } from '../../lib/format'
import { Icon } from '../ui/Icons'
import { HubSection } from './HubSection'

/**
 * The one block of real data on this screen: the verified session. It is written
 * as a ledger so it reads as evidence rather than marketing copy.
 */
export function HubSession({ index = 2 }: { index?: number }) {
  const { user, session } = useAuth()
  const identity = user?.identities?.[0]
  const provider = (user?.app_metadata?.provider as string | undefined) ?? identity?.provider

  const rows = [
    { label: 'Signed in as', value: displayName(user) },
    { label: 'Email', value: user?.email ?? '—', mono: true },
    { label: 'Provider', value: providerLabel(provider) },
    { label: 'Session verified', value: formatDateTime(session?.user.last_sign_in_at) },
  ]

  return (
    <HubSection
      id="hub-session"
      title="This session"
      index={index}
      action={
        <span className="hub-chip" data-tone="ok">
          <Icon name="shield" size={12} />
          Authenticated
        </span>
      }
    >
      <dl className="hub-ledger">
        {rows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd className={row.mono ? 'mono' : undefined}>{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="hub-ledger__note">
        Live account data from the Supabase session, verified on this device.
      </p>
    </HubSection>
  )
}
