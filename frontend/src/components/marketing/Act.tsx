import type { ReactNode } from 'react'

/**
 * A cinematic act.
 *
 * An act is a section whose content is designed to be pinned in place while
 * scroll drives one continuous transformation inside it. The markup is plain,
 * stacked content: with no JavaScript, with motion reduced, or on a phone the
 * scenes sit one after another and the act is simply a long chapter.
 *
 * `motion.ts` opts the stage into the pinned state (by setting
 * `data-cinema="on"` on the page and pinning `[data-pin]`), at which point CSS
 * stacks the scenes on top of each other inside one viewport and the timeline
 * decides which one is visible. Nothing here requires pinning to be readable.
 */
export function Act({
  id,
  kind,
  label,
  scenes,
  className,
}: {
  id: string
  kind: 'open' | 'chapters' | 'instrument' | 'showcase' | 'evidence' | 'invitation'
  label: string
  scenes: ReactNode
  className?: string
}) {
  return (
    <section
      className={`act act--${kind}${className ? ` ${className}` : ''}`}
      id={id}
      data-act={kind}
      aria-label={label}
    >
      <div className="act__stage" data-pin>
        {scenes}
      </div>
    </section>
  )
}
