import { Icon, type IconName } from '../ui/Icons'
import { HubSection } from './HubSection'

type Check = {
  label: string
  value: string
  detail: string
  state: 'ok' | 'off' | 'unset'
  icon: IconName
}

/**
 * Only what can be verified from inside this build. Nothing here reports a
 * provider as connected unless the application is actually using it, because the
 * honest answer is the useful one when a teacher wonders why marking is not
 * running.
 */
const CHECKS: Check[] = [
  {
    label: 'Authentication',
    value: 'Live',
    detail: 'Google sign-in through Supabase.',
    state: 'ok',
    icon: 'shield',
  },
  {
    label: 'Engine API',
    value: 'Not deployed',
    detail: 'No public endpoint answers yet.',
    state: 'off',
    icon: 'server',
  },
  {
    label: 'Correction pipeline',
    value: 'Unavailable',
    detail: 'Jobs park at PIPELINE_UNAVAILABLE instead of producing a mark.',
    state: 'off',
    icon: 'pulse',
  },
  {
    label: 'Workspace membership',
    value: 'Unresolved',
    detail: 'Roles are decided by the engine, never by the browser.',
    state: 'unset',
    icon: 'classroom',
  },
]

export function HubHealth() {
  return (
    <HubSection id="hub-health" title="Workspace health" index={5}>
      <ul className="hub-health">
        {CHECKS.map((check) => (
          <li className="hub-health__row" key={check.label} data-state={check.state}>
            <span className="hub-health__glyph" aria-hidden="true">
              <Icon name={check.icon} size={13} />
            </span>
            <span className="hub-health__label">{check.label}</span>
            <span className="hub-health__value mono">{check.value}</span>
            <span className="hub-health__detail">{check.detail}</span>
          </li>
        ))}
      </ul>
    </HubSection>
  )
}
