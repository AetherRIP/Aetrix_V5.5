import { useLayoutEffect, type RefObject } from 'react'

const REDUCED_QUERY = '(prefers-reduced-motion: reduce)'

/**
 * Technique reference, not code: Zajno's "Interactive Cicada Genomics Landing
 * Page" (CodePen, Alyona Misiura) scrubs a multi-state SVG between compositions
 * and sends a signal along a motion path. The techniques are reused here; every
 * path, composition, ease and word on this page is Aetrix's own.
 *
 * The landing page's cinematic layer.
 *
 * The page is built as five acts:
 *
 *   I    opening      hero → problem, in one pinned frame
 *   II   transformation  six stages of one correction (pinned)
 *   III  chapters     six scenes handing over inside one frame (pinned)
 *   IV   instrument   the 3D stack exploding under scroll (pinned)
 *   V    evidence     the trail walked node by node (pinned)
 *
 * plus an unpinned product film and the closing invitation. Each act owns one
 * pinned stage and one scrubbed timeline; the stage is released when its
 * timeline ends so the page continues.
 *
 * Everything here is additive. The markup is five ordinary stacked chapters —
 * with no JavaScript, with motion reduced, or on a phone the page reads
 * top-to-bottom. `data-cinema="on"` is what opts a stage into the pinned state,
 * and it is set only on a wide viewport after GSAP has loaded. Elements that
 * would otherwise flash at their final position are armed in a layout effect and
 * disarmed again if GSAP has not taken over within 2.4 s.
 */
export function useCinematicMotion(root: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const page = root.current
    if (!page) return
    if (window.matchMedia(REDUCED_QUERY).matches) return

    const armed = Array.from(page.querySelectorAll<HTMLElement>('.mk-hero [data-arm]'))
    for (const node of armed) node.style.opacity = '0'

    let cancelled = false
    let cleanup: (() => void) | undefined

    const disarm = () => {
      for (const node of armed) node.style.removeProperty('opacity')
    }

    const watchdog = window.setTimeout(() => {
      if (!cleanup) disarm()
    }, 2400)

    void (async () => {
      const [{ gsap }, { ScrollTrigger }, { MotionPathPlugin }, { CustomEase }] =
        await Promise.all([
          import('gsap'),
          import('gsap/ScrollTrigger'),
          import('gsap/MotionPathPlugin'),
          import('gsap/CustomEase'),
        ])

      if (cancelled) return

      gsap.registerPlugin(ScrollTrigger, MotionPathPlugin, CustomEase)
      CustomEase.create('aetrix-rise', '0.16, 1, 0.3, 1')
      CustomEase.create('aetrix-glide', '0.57, 0, 0.43, 1')

      const drawable = (selector: string, scope: HTMLElement = page) =>
        gsap.utils.toArray<SVGPathElement>(selector, scope)

      /** Prepares a path to be drawn by animating its dash offset to zero. */
      const armStroke = (paths: SVGPathElement[]) => {
        for (const path of paths) {
          const length = path.getTotalLength()
          path.style.strokeDasharray = `${length}`
          path.style.strokeDashoffset = `${length}`
        }
      }

      const mm = gsap.matchMedia()
      const detachers: Array<() => void> = []

      const ctx = gsap.context(() => {
        /* ── The opening shot ───────────────────────────────────────────── */
        const hero = page.querySelector<HTMLElement>('.mk-hero')
        let intro: ReturnType<typeof gsap.timeline> | null = null

        if (hero) {
          const heroWords = gsap.utils.toArray<HTMLElement>('.mk-hero .mk-word__i', page)
          const latticePaths = drawable('.mk-hero .lt-path')
          armStroke(latticePaths)

          intro = gsap.timeline({
            defaults: { ease: 'aetrix-rise', duration: 1.1 },
            paused: true,
          })

          intro
            .from('.mk-hero .mk-kicker > *', {
              yPercent: 130,
              opacity: 0,
              stagger: 0.07,
              duration: 0.9,
            })
            .fromTo(
              heroWords,
              { yPercent: 120, opacity: 0 },
              { yPercent: 0, opacity: 1, stagger: { each: 0.05 }, duration: 1.15 },
              '-=0.72',
            )
            .fromTo(
              '.mk-hero [data-arm]:not(.mk-word__i)',
              { y: 26, opacity: 0 },
              { y: 0, opacity: 1, stagger: 0.09, duration: 0.9 },
              '-=0.86',
            )
            .to(
              latticePaths,
              { strokeDashoffset: 0, duration: 1.7, stagger: 0.05, ease: 'power2.inOut' },
              '-=0.95',
            )
            .from(
              '.mk-hero .lt-node',
              {
                scale: 0,
                opacity: 0,
                transformOrigin: 'center',
                stagger: 0.055,
                duration: 0.55,
                ease: 'back.out(2.2)',
              },
              '-=1.15',
            )
            .from(
              '.mk-hero .lt-label',
              { opacity: 0, x: -6, stagger: 0.05, duration: 0.5 },
              '-=0.5',
            )
            .to(
              '.mk-hero .lt-signal',
              {
                motionPath: {
                  path: '.mk-hero .lt-route',
                  align: '.mk-hero .lt-route',
                  alignOrigin: [0.5, 0.5],
                },
                duration: 2.6,
                ease: 'none',
              },
              '-=1.9',
            )
            .from(
              '.mk-hero__rail li',
              { opacity: 0, y: 10, stagger: 0.05, duration: 0.6 },
              '-=1.2',
            )

          const play = () => intro?.play(0)
          window.addEventListener('aetrix:replay-intro', play)
          detachers.push(() => window.removeEventListener('aetrix:replay-intro', play))

          const settle = () => {
            if (document.visibilityState === 'hidden') {
              intro?.progress(1).pause()
            } else {
              intro?.play()
            }
          }
          intro.play()
          settle()
          document.addEventListener('visibilitychange', settle)
          detachers.push(() => document.removeEventListener('visibilitychange', settle))
        }

        /* ── The transformation: the signature sequence ─────────────────── */
        const transform = page.querySelector<HTMLElement>('.mk-transform')
        const captions = gsap.utils.toArray<HTMLElement>('.mk-cap', page)

        if (transform && captions.length === 6) {
          const solutionPaths = drawable('.mk-transform .tr-sol')
          const treePaths = drawable('.mk-transform .tr-tree')
          const netPaths = drawable('.mk-transform .tr-net')
          armStroke(solutionPaths)
          armStroke(treePaths)
          armStroke(netPaths)

          const swap = (from: HTMLElement, to: HTMLElement, at: number) => {
            tl.call(
              () => {
                from.dataset.active = 'false'
                to.dataset.active = 'true'
              },
              undefined,
              at + 0.08,
            )
            tl.to(from, { opacity: 0.5, duration: 0.35 }, at)
            tl.to(to, { opacity: 1, duration: 0.35 }, at + 0.08)
          }

          let tl: ReturnType<typeof gsap.timeline>

          mm.add('(min-width: 900px)', () => {
            tl = gsap.timeline({
              defaults: { ease: 'none' },
              scrollTrigger: {
                trigger: transform,
                start: 'top top',
                end: '+=320%',
                scrub: 0.6,
                pin: '.mk-transform__pin',
                anticipatePin: 1,
              },
            })

            captions[0].dataset.active = 'true'
            for (const caption of captions.slice(1)) caption.dataset.active = 'false'
            gsap.set(captions[0], { opacity: 1 })
            gsap.set(captions.slice(1), { opacity: 0.5 })
            gsap.set('.mk-transform .tr-signal', { opacity: 1 })

            tl.to(solutionPaths, { strokeDashoffset: 0, duration: 1.4, stagger: 0.1 }, 0)
              .from(
                '.mk-transform .tr-sol-text',
                { opacity: 0, y: 8, stagger: 0.08, duration: 0.6 },
                0.1,
              )
              .to('.mk-transform .tr-sol-group', { opacity: 0.42, duration: 0.6 }, 1.7)
              .to(treePaths, { strokeDashoffset: 0, duration: 1.5, stagger: 0.14 }, 1.8)
              .from(
                '.mk-transform .tr-node',
                {
                  scale: 0,
                  opacity: 0,
                  transformOrigin: 'center',
                  stagger: 0.11,
                  duration: 0.5,
                  ease: 'back.out(1.8)',
                },
                2.4,
              )
              .from(
                '.mk-transform .tr-node-label',
                { opacity: 0, y: 6, stagger: 0.1, duration: 0.5 },
                2.6,
              )
              .to('.mk-transform .tr-tree-group', { opacity: 0.55, duration: 0.7 }, 3.9)
              .to(netPaths, { strokeDashoffset: 0, duration: 1.3, stagger: 0.09 }, 3.9)
              .from(
                '.mk-transform .tr-verify',
                {
                  scale: 0.4,
                  opacity: 0,
                  transformOrigin: 'center',
                  stagger: 0.08,
                  duration: 0.5,
                  ease: 'back.out(2)',
                },
                4.2,
              )
              .from('.mk-transform .tr-result', { opacity: 0, y: 18, duration: 0.7 }, 4.7)
              .to(
                '.mk-transform .tr-signal',
                {
                  motionPath: {
                    path: '.mk-transform .tr-route',
                    align: '.mk-transform .tr-route',
                    alignOrigin: [0.5, 0.5],
                  },
                  duration: 5.6,
                },
                0,
              )

            swap(captions[0], captions[1], 1.6)
            swap(captions[1], captions[2], 2.7)
            swap(captions[2], captions[3], 3.8)
            swap(captions[3], captions[4], 4.5)
            swap(captions[4], captions[5], 5.1)
          })

          mm.add('(max-width: 899px)', () => {
            gsap.set(solutionPaths, { strokeDashoffset: 0 })
            gsap.set(treePaths, { strokeDashoffset: 0 })
            gsap.set(netPaths, { strokeDashoffset: 0 })
            gsap.set('.mk-transform .tr-sol-group', { opacity: 0.42 })
            gsap.set('.mk-transform .tr-tree-group', { opacity: 0.55 })
            gsap.set('.mk-transform .tr-signal', { opacity: 0 })

            captions.forEach((caption) => {
              gsap.from(caption, {
                opacity: 0,
                y: 16,
                duration: 0.7,
                ease: 'aetrix-rise',
                scrollTrigger: { trigger: caption, start: 'top 90%' },
              })
            })
          })
        }

        /* ── The pinned acts ─────────────────────────────────────────────── */
        const opening = page.querySelector<HTMLElement>('.act--open')
        const chapters = page.querySelector<HTMLElement>('.act--chapters')
        const instrument = page.querySelector<HTMLElement>('#instrument')
        const film = page.querySelector<HTMLElement>('.film')
        const security = page.querySelector<HTMLElement>('#security')

        mm.add('(min-width: 900px)', () => {
          page.dataset.cinema = 'on'

          /* ACT I — the hero becomes the problem. */
          if (opening) {
            const heroScene = opening.querySelector<HTMLElement>('[data-scene="hero"]')
            const problemScene = opening.querySelector<HTMLElement>('[data-scene="problem"]')
            const stage = opening.querySelector<HTMLElement>('[data-pin]')

            if (heroScene && problemScene && stage) {
              armStroke(drawable('.pb-bracket, .pb-link', opening))
              gsap.set(problemScene, { opacity: 0, y: 44 })

              const tl = gsap.timeline({
                defaults: { ease: 'none' },
                scrollTrigger: {
                  trigger: opening,
                  start: 'top top',
                  end: '+=220%',
                  scrub: 0.6,
                  pin: stage,
                  anticipatePin: 1,
                },
              })

              /*
               * The hero is lifted out, not switched off: its field and lattice
               * stay at low opacity behind the incoming sheet, so the frame is
               * never empty and there is no dip to black between the two scenes.
               */
              /*
               * autoAlpha (opacity + visibility) rather than opacity alone: a
               * transparent hero must not keep capturing clicks or tab stops
               * once the problem scene owns the frame.
               *
               * The hand-over is compressed into the first third and the sheet's
               * own reveals run to 0.95, so the finished scene holds for the last
               * stretch of the pin instead of assembling as it releases.
               */
              tl.to('.mk-hero__rail', { autoAlpha: 0, duration: 0.18 }, 0)
                .to('.mk-hero__shader', { opacity: 0.42, duration: 0.7 }, 0)
                .to('.mk-hero__copy', { yPercent: -6, autoAlpha: 0, duration: 0.34 }, 0.04)
                .to(
                  '.mk-hero__figure',
                  { scale: 0.9, yPercent: -3, autoAlpha: 0, duration: 0.4 },
                  0.06,
                )
                .to(heroScene, { autoAlpha: 0, duration: 0.3 }, 0.18)
                /*
                 * autoAlpha, not opacity: an invisible scene that is still
                 * `visibility: visible` sits on top of the hero in the same
                 * stacking context and eats every click on the hero's buttons.
                 */
                .fromTo(
                  problemScene,
                  { autoAlpha: 0, y: 30 },
                  { autoAlpha: 1, y: 0, duration: 0.34 },
                  0.14,
                )
                .fromTo(
                  '.pb-shard--b',
                  { x: 0, y: 0, opacity: 0.5 },
                  { x: -20, y: -24, opacity: 1, duration: 0.45 },
                  0.22,
                )
                .fromTo(
                  '.pb-shard--c',
                  { x: 0, y: 0, opacity: 0.35 },
                  { x: -38, y: -46, opacity: 1, duration: 0.45 },
                  0.26,
                )
                .from('.mk-problem .pb-hand', { opacity: 0, stagger: 0.05, duration: 0.32 }, 0.26)
                .to('.mk-problem .pb-scan', { y: 300, duration: 0.7, ease: 'power1.inOut' }, 0.28)
                .to(
                  '.mk-problem .pb-bracket, .mk-problem .pb-link',
                  { strokeDashoffset: 0, duration: 0.4, stagger: 0.04 },
                  0.32,
                )
                .from('.mk-problem .mk-head', { opacity: 0, y: 14, duration: 0.36 }, 0.3)
                .from(
                  '.mk-problem .mk-beat',
                  { opacity: 0, y: 18, stagger: 0.07, duration: 0.36 },
                  0.36,
                )
                .from(
                  '.mk-problem .pb-tag',
                  { opacity: 0, x: -8, stagger: 0.05, duration: 0.28 },
                  0.4,
                )
                .from(
                  '.mk-problem .pb-node',
                  { opacity: 0, x: 12, stagger: 0.06, duration: 0.32 },
                  0.44,
                )
                .from('.mk-problem .pb-score', { opacity: 0, duration: 0.28 }, 0.58)
                .from(
                  '.mk-problem .pb-chip',
                  { scale: 0, opacity: 0, transformOrigin: 'center', stagger: 0.05, duration: 0.28 },
                  0.62,
                )
                .from('.mk-problem .mk-problem__aside', { opacity: 0, duration: 0.28 }, 0.66)
            }
          }

          /* ACT III — six scenes in one frame. */
          if (chapters) {
            const stage = chapters.querySelector<HTMLElement>('[data-pin]')
            const items = gsap.utils.toArray<HTMLElement>('.ch', chapters)
            const markers = gsap.utils.toArray<HTMLElement>('[data-chapter-marker]', chapters)
            const counter = chapters.querySelector<HTMLElement>('[data-chapter-count]')

            if (stage && items.length > 0) {
              // Hidden scenes must leave the hit-test and tab order entirely.
              gsap.set(items.slice(1), { autoAlpha: 0, y: 34 })

              const mark = (index: number) => {
                markers.forEach((marker, position) => {
                  marker.toggleAttribute('data-active', position === index)
                  marker.toggleAttribute('data-seen', position <= index)
                })
                if (counter) counter.textContent = String(index + 1).padStart(2, '0')
              }
              mark(0)

              const tl = gsap.timeline({
                defaults: { ease: 'none' },
                scrollTrigger: {
                  trigger: chapters,
                  start: 'top top',
                  end: '+=560%',
                  scrub: 0.6,
                  pin: stage,
                  anticipatePin: 1,
                },
              })

              tl.to('.ch__rail-track i', { scaleX: 1, duration: 6 }, 0)

              let cursor = 0
              items.forEach((item, index) => {
                const paths = drawable('.sc-path', item)
                armStroke(paths)

                if (index > 0) {
                  /* The incoming scene starts before the outgoing one begins to
                     leave, so the stage is never empty mid-handover. */
                  tl.fromTo(
                    item,
                    { autoAlpha: 0, y: 34 },
                    { autoAlpha: 1, y: 0, duration: 0.5 },
                    cursor - 0.18,
                  )
                  tl.to(items[index - 1], { autoAlpha: 0, y: -28, duration: 0.42 }, cursor + 0.02)
                  tl.call(() => mark(index), undefined, cursor + 0.12)
                }

                tl.to(paths, { strokeDashoffset: 0, duration: 0.9, stagger: 0.035 }, cursor)
                tl.from(
                  item.querySelectorAll('.sc-pop'),
                  { opacity: 0, y: 14, stagger: 0.055, duration: 0.45 },
                  cursor + 0.1,
                )

                cursor += 1
              })
            }
          }

          /* ACT IV — the instrument, exploded by scroll. */
          if (instrument) {
            ScrollTrigger.create({
              trigger: instrument,
              start: 'top top',
              end: '+=180%',
              pin: true,
              anticipatePin: 1,
              onUpdate: (self) => {
                window.dispatchEvent(
                  new CustomEvent('aetrix:instrument-spread', {
                    detail: { progress: self.progress },
                  }),
                )
              },
              onEnter: () => {
                window.dispatchEvent(
                  new CustomEvent('aetrix:instrument-spread', { detail: { progress: 0 } }),
                )
              },
            })
          }

          /* The product film, pinned just long enough to assemble. */
          if (film) {
            gsap.fromTo(
              film,
              { clipPath: 'inset(12% 6% 12% 6%)', opacity: 0.4 },
              {
                clipPath: 'inset(0% 0% 0% 0%)',
                opacity: 1,
                ease: 'none',
                scrollTrigger: {
                  trigger: film,
                  start: 'top 18%',
                  end: '+=110%',
                  scrub: 0.5,
                  pin: true,
                  anticipatePin: 1,
                },
              },
            )
          }

          /* ACT V — walk the evidence trail. */
          let lastNode = -1

          if (security) {
            ScrollTrigger.create({
              trigger: security,
              start: 'top top',
              end: '+=240%',
              pin: true,
              anticipatePin: 1,
              onUpdate: (self) => {
                const index = Math.min(5, Math.floor(self.progress * 6))
                // Only speak when the step changes: the walk used to dispatch a
                // state update on every scroll frame of a 240% pin.
                if (index === lastNode) return
                lastNode = index
                window.dispatchEvent(
                  new CustomEvent('aetrix:evidence-node', { detail: { index } }),
                )
              },
              onEnter: () => {
                lastNode = 0
                window.dispatchEvent(
                  new CustomEvent('aetrix:evidence-node', { detail: { index: 0 } }),
                )
              },
            })
          }

          /*
           * Every pin above changes the scroll length of the triggers below it.
           * ScrollTrigger caches start positions, so the batch has to be
           * re-sorted and re-measured once all of them exist — otherwise a later
           * act starts inside the previous act's pinned range and two panels are
           * pinned at the same time.
           */
          ScrollTrigger.sort()
          ScrollTrigger.refresh()
        })

        /* ── Phones: no pins, same choreography in miniature ─────────────── */
        mm.add('(max-width: 899px)', () => {
          page.dataset.cinema = 'off'

          gsap.utils.toArray<HTMLElement>('.ch', page).forEach((chapter) => {
            const paths = drawable('.sc-path', chapter)
            armStroke(paths)
            gsap.to(paths, {
              strokeDashoffset: 0,
              duration: 1.1,
              stagger: 0.02,
              scrollTrigger: { trigger: chapter, start: 'top 82%' },
            })
          })

          gsap.utils.toArray<HTMLElement>('.mk-beat', page).forEach((beat) => {
            gsap.from(beat, {
              opacity: 0,
              y: 18,
              duration: 0.6,
              scrollTrigger: { trigger: beat, start: 'top 88%' },
            })
          })

          if (instrument) {
            window.dispatchEvent(
              new CustomEvent('aetrix:instrument-spread', { detail: { progress: 1 } }),
            )
          }
        })

        /* ── The closing composition ─────────────────────────────────────── */
        gsap.from('.mk-invite .mk-word__i', {
          yPercent: 118,
          duration: 1.15,
          stagger: 0.06,
          ease: 'aetrix-rise',
          scrollTrigger: { trigger: '.mk-invite', start: 'top 74%' },
        })

        const invitePaths = drawable('.mk-invite .in-path')
        if (invitePaths.length > 0) {
          armStroke(invitePaths)
          gsap.to(invitePaths, {
            strokeDashoffset: 0,
            duration: 1.8,
            stagger: 0.03,
            ease: 'power2.inOut',
            scrollTrigger: { trigger: '.mk-invite', start: 'top 80%' },
          })
          gsap.from('.mk-invite .in-node', {
            scale: 0,
            opacity: 0,
            transformOrigin: 'center',
            stagger: 0.04,
            duration: 0.6,
            ease: 'back.out(2)',
            scrollTrigger: { trigger: '.mk-invite', start: 'top 80%' },
          })
        }

      }, page)

      cleanup = () => {
        for (const detach of detachers) detach()
        delete page.dataset.cinema
        mm.revert()
        ctx.revert()
        for (const node of armed) node.style.removeProperty('opacity')
      }

      window.clearTimeout(watchdog)

      if (document.fonts?.ready) {
        void document.fonts.ready.then(() => ScrollTrigger.refresh())
      }
    })()

    return () => {
      cancelled = true
      window.clearTimeout(watchdog)
      cleanup?.()
      if (!cleanup) disarm()
    }
  }, [root])
}
