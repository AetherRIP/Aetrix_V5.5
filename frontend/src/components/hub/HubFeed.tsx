import { HubSection } from './HubSection'

/**
 * Real records only. When there is nothing to show, the panel says so instead of
 * inventing a history to look busy.
 */
export function HubFeed({ index = 6 }: { index?: number }) {
  return (
    <HubSection
      id="hub-activity"
      title="Activity"
      action={
        <span className="hub-sectionhead__note" aria-hidden="true">
          engine events
        </span>
      }
      index={index}
    >
      <div className="hub-feed hub-feed--empty">
        <span className="hub-feed__glyph" aria-hidden="true">
          <span className="hub-feed__dot" />
        </span>
        <div>
          <p className="hub-feed__title">Nothing has happened yet</p>
          <p className="hub-feed__note">
            Activity is recorded by the engine when it accepts work. Since no job can run
            yet, this list is genuinely empty rather than filtered.
          </p>
        </div>
      </div>
    </HubSection>
  )
}
