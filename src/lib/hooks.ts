import type { CSSProperties } from 'react'
import { useEffect, useState, useSyncExternalStore } from 'react'

export type CSSVars = CSSProperties & Record<`--${string}`, string | number>

export function vars(values: Record<string, string | number>): CSSVars {
  return values as CSSVars
}

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

function subscribeReducedMotion(listener: () => void) {
  const query = window.matchMedia(REDUCED_MOTION_QUERY)
  query.addEventListener('change', listener)
  return () => query.removeEventListener('change', listener)
}

function readReducedMotion() {
  return window.matchMedia(REDUCED_MOTION_QUERY).matches
}

/** True when the visitor has asked the operating system to reduce motion. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReducedMotion, readReducedMotion, () => false)
}

/**
 * Reveals every `[data-reveal]` element once as it enters the viewport.
 *
 * The hidden initial state is only applied after this effect runs, so a
 * visitor without JavaScript — or one whose script fails — always sees the
 * complete page rather than a blank column of invisible sections.
 */
export function useScrollReveal() {
  useEffect(() => {
    const nodes = Array.from(
      document.querySelectorAll<HTMLElement>('[data-reveal]'),
    )
    if (nodes.length === 0) return

    const reduced = window.matchMedia(REDUCED_MOTION_QUERY).matches
    if (reduced || typeof IntersectionObserver === 'undefined') {
      for (const node of nodes) node.setAttribute('data-revealed', '')
      return
    }

    document.documentElement.setAttribute('data-reveal-active', '')

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.setAttribute('data-revealed', '')
          observer.unobserve(entry.target)
        }
      },
      { rootMargin: '0px 0px -6% 0px', threshold: 0.06 },
    )

    for (const node of nodes) observer.observe(node)
    return () => observer.disconnect()
  }, [])
}

export const SECTION_IDS = ['platform', 'workflow', 'features', 'security'] as const

/** Highlights the section currently occupying the reading position. */
export function useActiveSection(): string {
  const [active, setActive] = useState<string>('')

  useEffect(() => {
    const sections = SECTION_IDS.map((id) => document.getElementById(id)).filter(
      (element): element is HTMLElement => element !== null,
    )
    if (sections.length === 0 || typeof IntersectionObserver === 'undefined') return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible) setActive(visible.target.id)
      },
      { rootMargin: '-42% 0px -50% 0px', threshold: [0, 0.2, 0.6] },
    )

    for (const section of sections) observer.observe(section)
    return () => observer.disconnect()
  }, [])

  return active
}

/** Reports whether the page has been scrolled past the header's resting state. */
export function useScrolled(threshold = 12): boolean {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    let frame = 0
    const read = () => {
      frame = 0
      setScrolled(window.scrollY > threshold)
    }
    const onScroll = () => {
      if (frame !== 0) return
      frame = window.requestAnimationFrame(read)
    }
    read()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (frame !== 0) window.cancelAnimationFrame(frame)
    }
  }, [threshold])

  return scrolled
}

/**
 * A pointer tilt for the hero stage. Disabled for coarse pointers and for
 * visitors who asked for reduced motion, where the stage stays flat.
 */
export function usePointerTilt(
  ref: React.RefObject<HTMLElement | null>,
  strength = 4,
) {
  useEffect(() => {
    const element = ref.current
    if (!element) return
    if (window.matchMedia(`${REDUCED_MOTION_QUERY}, (hover: none)`).matches) return

    let frame = 0
    let targetX = 0
    let targetY = 0

    const write = () => {
      frame = 0
      element.style.setProperty('--tilt-x', `${targetY.toFixed(2)}deg`)
      element.style.setProperty('--tilt-y', `${targetX.toFixed(2)}deg`)
    }

    const schedule = () => {
      if (frame !== 0) return
      frame = window.requestAnimationFrame(write)
    }

    const onMove = (event: PointerEvent) => {
      const bounds = element.getBoundingClientRect()
      const x = (event.clientX - bounds.left) / bounds.width - 0.5
      const y = (event.clientY - bounds.top) / bounds.height - 0.5
      targetX = x * strength
      targetY = -y * strength
      schedule()
    }

    const onLeave = () => {
      targetX = 0
      targetY = 0
      schedule()
    }

    element.addEventListener('pointermove', onMove)
    element.addEventListener('pointerleave', onLeave)
    return () => {
      element.removeEventListener('pointermove', onMove)
      element.removeEventListener('pointerleave', onLeave)
      if (frame !== 0) window.cancelAnimationFrame(frame)
    }
  }, [ref, strength])
}
