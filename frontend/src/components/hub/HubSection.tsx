import type { CSSProperties, ReactNode } from 'react'

/**
 * One titled block of the hub. The heading is a section label rather than a
 * second headline, and the optional action sits on the same baseline as it.
 */
export function HubSection({
  id,
  title,
  note,
  action,
  index = 0,
  className,
  children,
}: {
  id: string
  title: string
  note?: string
  action?: ReactNode
  /** Position in the page, used to stagger the entrance. */
  index?: number
  className?: string
  children: ReactNode
}) {
  return (
    <section
      className={className ? `hub-section ${className}` : 'hub-section'}
      aria-labelledby={id}
      style={{ '--i': index } as CSSProperties}
    >
      <header className="hub-sectionhead">
        <h2 id={id}>{title}</h2>
        {note ? <p className="hub-sectionhead__note">{note}</p> : null}
        {action ? <div className="hub-sectionhead__action">{action}</div> : null}
      </header>
      {children}
    </section>
  )
}
