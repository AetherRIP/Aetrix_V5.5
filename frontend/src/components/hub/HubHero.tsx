import type { ReactNode } from 'react'

function greeting(date = new Date()): string {
  const hour = date.getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

function longDate(date = new Date()): string {
  return new Intl.DateTimeFormat('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(date)
}

/**
 * The greeting is a line, not a banner. It owns the top of the page so the
 * figures below read as the answer to it, and the one filled button is the next
 * piece of work.
 */
export function HubHero({
  name,
  actions,
  lede,
}: {
  name: string
  actions: ReactNode
  /** Each account type states its own scope; the wording is never assumed. */
  lede?: string
}) {
  return (
    <section className="hub-hero" aria-labelledby="hub-greeting">
      <div className="hub-hero__copy">
        <p className="hub-hero__date mono">{longDate()}</p>
        <h1 className="hub-hero__title" id="hub-greeting">
          {greeting()}, {name}.
        </h1>
        <p className="hub-hero__lede">
          {lede ??
            'Your session is verified with Supabase. Marking figures stay blank until the correction engine is deployed — nothing on this screen is estimated.'}
        </p>
      </div>

      <div className="hub-hero__actions">{actions}</div>
    </section>
  )
}
