import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Icon } from '../ui/Icons'
import { HubSection } from './HubSection'

/**
 * Deliberately not three identical tiles. One wide action carries the primary
 * workflow; the next is a different size and weight; the unavailable one is
 * marked as such rather than silently doing nothing.
 */
export function HubActions({ index = 3 }: { index?: number }) {
  const [explained, setExplained] = useState(false)

  return (
    <HubSection
      id="hub-actions"
      title="Quick actions"
      note="What you are most likely to do next."
      index={index}
    >
      <div className="hub-actions">
        <Link to="/queue" className="hub-action hub-action--primary">
          <span className="hub-action__icon">
            <Icon name="pulse" size={20} />
          </span>
          <span className="hub-action__body">
            <span className="hub-action__title">Open the marking queue</span>
            <span className="hub-action__note">
              Job state for this workspace, once the engine answers.
            </span>
          </span>
          <Icon name="arrow" size={16} />
        </Link>

        <Link to="/assignments" className="hub-action">
          <span className="hub-action__icon">
            <Icon name="assignment" size={18} />
          </span>
          <span className="hub-action__body">
            <span className="hub-action__title">Review assignments</span>
            <span className="hub-action__note">The assignment list arrives with the engine.</span>
          </span>
          <Icon name="chevron" size={15} />
        </Link>

        <div className="hub-action hub-action--quiet">
          <span className="hub-action__icon">
            <Icon name="server" size={18} />
          </span>
          <span className="hub-action__body">
            <span className="hub-action__title">Connect the engine</span>
            <span className="hub-action__note">Needs a deployed correction API.</span>
          </span>
          <button
            type="button"
            className="hub-action__badge"
            aria-expanded={explained}
            onClick={() => setExplained((value) => !value)}
          >
            <Icon name="lock" size={12} />
            Why not
          </button>
        </div>
      </div>

      {explained ? (
        <p className="hub-actions__note" role="status">
          This build ships the interface and the authentication, not the marking service.
          There is no endpoint to point at, so every action that would need one is marked
          unavailable rather than wired to sample data.
        </p>
      ) : null}

      <div className="hub-actions__links">
        <Link to="/reports" className="hub-actions__link">
          <Icon name="blueprint" size={15} />
          Reports
        </Link>
        <Link to="/inbox" className="hub-actions__link">
          <Icon name="records" size={15} />
          Inbox
        </Link>
        <Link to="/settings" className="hub-actions__link">
          <Icon name="lock" size={15} />
          Account settings
        </Link>
      </div>
    </HubSection>
  )
}
