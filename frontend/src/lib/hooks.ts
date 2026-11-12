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
 * Publishes the reading position as two custom properties on the root:
 * `--scroll` (0–1 through the document, for the header hairline) and
 * `--scroll-y` (pixels, for the parallax layers). CSS owns the motion, so this
 * runs once per frame and never re-renders React.
 */
export function useScrollProgress() {
  useEffect(() => {
    const root = document.documentElement
    let frame = 0

    const read = () => {
      frame = 0
      const max = root.scrollHeight - window.innerHeight
      const y = window.scrollY
      const progress = max > 0 ? Math.min(1, Math.max(0, y / max)) : 0
      root.style.setProperty('--scroll', progress.toFixed(4))
      root.style.setProperty('--scroll-y', `${Math.round(y)}px`)
    }

    const schedule = () => {
      if (frame !== 0) return
      frame = window.requestAnimationFrame(read)
    }

    read()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      if (frame !== 0) window.cancelAnimationFrame(frame)
    }
  }, [])
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

export const SECTION_IDS = [
  'platform',
  'signal',
  'workflow',
  'features',
  'security',
] as const

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
 * Slides the ambient lamp toward the pointer, as though someone were reading the
 * page under a hand lamp. Only the transform is written, one frame at a time,
 * and the loop stops as soon as the lamp has caught up — an idle page does no
 * work. Coarse pointers have no hover position to follow and a visitor who asked
 * for less motion gets no lamp at all, so neither case installs a listener.
 */
export function usePointerLamp(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const field = ref.current
    const lamp = field?.querySelector<HTMLElement>('[data-lamp]')
    if (!field || !lamp) return
    if (window.matchMedia(`${REDUCED_MOTION_QUERY}, (hover: none)`).matches) return

    let frame = 0
    let lit = false
    let targetX = 0
    let targetY = 0
    let x = 0
    let y = 0

    const paint = () => {
      lamp.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`
    }

    const follow = () => {
      frame = 0
      const dx = targetX - x
      const dy = targetY - y
      // The further behind it fell, the harder the lamp pulls. A flick across
      // the page closes in a few frames; a slow hand keeps the carried feel.
      // 0.10 is what leaves a visible trail at hand speed — at 0.16 the lamp sat
      // too close to the pointer to read as something being carried.
      const pull = 0.1 + Math.min(0.56, Math.hypot(dx, dy) / 900)
      x += dx * pull
      y += dy * pull
      if (Math.abs(targetX - x) < 0.4 && Math.abs(targetY - y) < 0.4) {
        x = targetX
        y = targetY
        paint()
        return
      }
      paint()
      frame = window.requestAnimationFrame(follow)
    }

    const schedule = () => {
      if (frame !== 0) return
      frame = window.requestAnimationFrame(follow)
    }

    const light = () => {
      if (lit) return
      lit = true
      field.setAttribute('data-pointer', 'active')
    }

    const onMove = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return
      const bounds = field.getBoundingClientRect()
      targetX = event.clientX - bounds.left
      targetY = event.clientY - bounds.top
      if (!lit) {
        // First sight of the pointer, or the first move after it left the
        // window: set the lamp down where the pointer is rather than sliding
        // it in from wherever it was parked.
        x = targetX
        y = targetY
        paint()
        light()
        return
      }
      schedule()
    }

    // Leaving the window must not switch the lamp off for good: this only
    // unlights it, and the next pointer move lights it again.
    const lift = () => {
      if (frame !== 0) {
        window.cancelAnimationFrame(frame)
        frame = 0
      }
      field.removeAttribute('data-pointer')
      lit = false
    }

    document.addEventListener('pointermove', onMove, { passive: true })
    document.documentElement.addEventListener('mouseleave', lift)
    return () => {
      document.removeEventListener('pointermove', onMove)
      document.documentElement.removeEventListener('mouseleave', lift)
      if (frame !== 0) window.cancelAnimationFrame(frame)
    }
  }, [ref])
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
