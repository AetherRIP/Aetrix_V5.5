import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type * as ThreeTypes from 'three'
import { Icon } from '../ui/Icons'

/**
 * The eight layers of the instrument, in the order the engine works through
 * them. The copy is the honest description of each stage; the 3D scene only
 * gives those stages a shape.
 */
export const LAYERS = [
  {
    id: 'intake',
    code: 'L1',
    name: 'Submission intake',
    detail:
      'A scan arrives for one student on one assignment. It is validated, stored by the engine and rendered to pages before anything reads it.',
    state: 'Implemented',
  },
  {
    id: 'extraction',
    code: 'L2',
    name: 'Question extraction',
    detail:
      'Each question and its working are pulled from the page into a draft extraction. A draft is not a marking decision.',
    state: 'Implemented',
  },
  {
    id: 'interpretation',
    code: 'L3',
    name: 'Mathematical interpretation',
    detail:
      'The working is read as mathematics: expressions, steps and the relationships between them, rather than as text to be described.',
    state: 'Implemented',
  },
  {
    id: 'criteria',
    code: 'L4',
    name: 'Marking criteria',
    detail:
      'A locked blueprint supplies the question list and its official maximum marks. A mark cannot exceed the maximum of its question.',
    state: 'Implemented',
  },
  {
    id: 'assessment',
    code: 'L5',
    name: 'Assessment',
    detail:
      'Provisional marks are awarded against those criteria. The live provider is unverified, so no accuracy figure is claimed anywhere on this page.',
    state: 'Provider unverified',
  },
  {
    id: 'verification',
    code: 'L6',
    name: 'Verification',
    detail:
      'Reasoning is checked symbolically where a question allows it. A step that fails its check is flagged, never assumed correct.',
    state: 'Implemented',
  },
  {
    id: 'review',
    code: 'L7',
    name: 'Human review',
    detail:
      'Anything the engine cannot settle becomes Needs review. Overrides keep the original value, the reason and the reviewer.',
    state: 'Implemented',
  },
  {
    id: 'report',
    code: 'L8',
    name: 'Report',
    detail:
      'Approved question marks recompute into a report. Classroom write-back and grade publishing are separate and not integrated.',
    state: 'Not integrated',
  },
] as const

type LayerId = (typeof LAYERS)[number]['id']

/**
 * A three-dimensional instrument built from the eight layers of the pipeline.
 *
 * Three.js is imported only when the section approaches the viewport, so the
 * landing page never pays for the renderer unless a visitor reaches it. Each
 * layer is a group inside one spindle: dragging turns it, exploding separates
 * the stages, and clicking a layer — or pressing its button in the list — pulls
 * that stage into focus while the camera drifts to it.
 *
 * The list is the accessible control surface: a keyboard user can reach every
 * layer without touching the canvas, and the same list drives the scene. With no
 * WebGL the SVG stack is rendered instead and the list keeps working.
 */
export function Instrument() {
  const host = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState<LayerId | null>(null)
  const [exploded, setExploded] = useState(true)
  const [status, setStatus] = useState<'idle' | 'ready' | 'fallback'>('idle')

  const selectedRef = useRef<LayerId | null>(null)
  const explodedRef = useRef(true)
  const apiRef = useRef<{
    sync: () => void
    reset: () => void
  } | null>(null)

  const select = useCallback((id: LayerId | null) => {
    selectedRef.current = id
    setSelected(id)
    apiRef.current?.sync()
  }, [])

  const toggleExploded = useCallback(() => {
    explodedRef.current = !explodedRef.current
    setExploded(explodedRef.current)
    apiRef.current?.sync()
  }, [])

  const reset = useCallback(() => {
    selectedRef.current = null
    explodedRef.current = true
    setSelected(null)
    setExploded(true)
    apiRef.current?.reset()
  }, [])

  useEffect(() => {
    const element = host.current
    if (!element) return

    let disposed = false
    let cleanup: (() => void) | undefined

    const start = async () => {
      const THREE = await import('three')
      if (disposed) return

      /*
       * three r181 needs WebGL2, and WebGL2 does not require a GPU: Chromium
       * serves it from SwiftShader in software when hardware acceleration is off.
       * So the only genuinely fatal case is a browser that exposes no WebGL2 at
       * all (WebGL disabled by policy, or a software rasteriser switched off).
       * Probe first so that case is named precisely instead of guessed at.
       */
      const probe = document.createElement('canvas')
      const probeGl = probe.getContext('webgl2')
      probeGl?.getExtension('WEBGL_lose_context')?.loseContext()
      if (!probeGl) {
        console.warn(
          '[instrument] no WebGL2 context available (neither hardware nor software); showing the flat diagram',
        )
        setStatus('fallback')
        return
      }

      const options = {
        antialias: true,
        alpha: true,
        // Allow a software adapter rather than refusing to start without a GPU.
        failIfMajorPerformanceCaveat: false,
      }

      let renderer: ThreeTypes.WebGLRenderer
      try {
        renderer = new THREE.WebGLRenderer({ ...options, powerPreference: 'high-performance' })
      } catch (preferredError) {
        /*
         * Some dual-GPU and sandboxed setups refuse the 'high-performance'
         * adapter while accepting the default one, so try again before giving up
         * on the 3D at all.
         */
        try {
          renderer = new THREE.WebGLRenderer({ ...options, powerPreference: 'default' })
        } catch (fallbackError) {
          console.warn(
            '[instrument] could not create a WebGL2 renderer on either adapter:',
            preferredError,
            fallbackError,
          )
          setStatus('fallback')
          return
        }
      }

      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
      renderer.setClearColor(0x000000, 0)
      renderer.domElement.className = 'instr__canvas'
      renderer.domElement.setAttribute('aria-hidden', 'true')
      element.appendChild(renderer.domElement)

      const scene = new THREE.Scene()
      // Far enough back that the assembled stack (eight layers, ~6 units tall)
      // sits inside the frustum rather than running off the top and bottom.
      const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100)
      camera.position.set(0, 0.4, 14.5)

      const spindle = new THREE.Group()
      scene.add(spindle)

      const accent = new THREE.Color('#45d6a0')
      const graphite = new THREE.Color('#9aa8a2')
      const amber = new THREE.Color('#e8b465')

      const disposables: { dispose: () => void }[] = []
      const track = <T extends { dispose: () => void }>(item: T) => {
        disposables.push(item)
        return item
      }

      interface Layer {
        id: LayerId
        group: ThreeTypes.Group
        /** Every material in the layer, with the opacity it was built with. */
        parts: { material: ThreeTypes.Material & { opacity: number }; base: number }[]
        /** The layer's current brightness factor, eased towards a target. */
        factor: number
      }

      const layers: Layer[] = []

      const buildLayer = (
        id: LayerId,
        tint: ThreeTypes.Color,
        accentFace: boolean,
        build: (kit: {
          group: ThreeTypes.Group
          addLines: (points: number[], opacity?: number) => void
          addEdges: (geometry: ThreeTypes.BufferGeometry, opacity?: number) => void
          addWire: (geometry: ThreeTypes.BufferGeometry, opacity?: number) => void
          addFace: (geometry: ThreeTypes.BufferGeometry, opacity?: number) => void
        }) => void,
      ) => {
        const group = new THREE.Group()
        /** Materials are registered so one factor can fade the whole layer. */
        const parts: { material: ThreeTypes.Material & { opacity: number }; base: number }[] = []

        const register = <T extends ThreeTypes.Material & { opacity: number }>(
          material: T,
        ) => {
          parts.push({ material, base: material.opacity })
          return track(material)
        }

        const addLines = (points: number[], opacity = 0.55) => {
          const geometry = track(new THREE.BufferGeometry())
          geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3))
          const material = register(
            new THREE.LineBasicMaterial({ color: tint, transparent: true, opacity }),
          )
          group.add(new THREE.LineSegments(geometry, material))
        }

        const addEdges = (geometry: ThreeTypes.BufferGeometry, opacity = 0.7) => {
          const edges = track(new THREE.EdgesGeometry(geometry, 16))
          const material = register(
            new THREE.LineBasicMaterial({ color: tint, transparent: true, opacity }),
          )
          group.add(new THREE.LineSegments(edges, material))
          track(geometry)
        }

        const addWire = (geometry: ThreeTypes.BufferGeometry, opacity = 0.55) => {
          const wire = track(new THREE.WireframeGeometry(geometry))
          const material = register(
            new THREE.LineBasicMaterial({ color: tint, transparent: true, opacity }),
          )
          group.add(new THREE.LineSegments(wire, material))
          track(geometry)
        }

        const addFace = (geometry: ThreeTypes.BufferGeometry, opacity = 0.06) => {
          const material = register(
            new THREE.MeshBasicMaterial({
              color: accentFace ? accent : graphite,
              transparent: true,
              opacity,
              side: THREE.DoubleSide,
              depthWrite: false,
            }),
          )
          group.add(new THREE.Mesh(track(geometry), material))
        }

        build({ group, addLines, addEdges, addWire, addFace })
        spindle.add(group)
        layers.push({ id, group, parts, factor: 0.82 })
      }

      buildLayer('intake', graphite, false, ({ group, addEdges, addFace }) => {
        addFace(new THREE.BoxGeometry(3.6, 0.04, 2.5), 0.16)
        addEdges(new THREE.BoxGeometry(3.6, 0.04, 2.5), 0.8)
        const page = new THREE.Group()
        page.position.y = 0.08
        const edges = track(new THREE.EdgesGeometry(new THREE.BoxGeometry(2.3, 0.02, 1.5)))
        const material = track(new THREE.LineBasicMaterial({ color: graphite, transparent: true, opacity: 0.3 }))
        page.add(new THREE.LineSegments(edges, material))
        group.add(page)
      })

      buildLayer('extraction', graphite, false, ({ addLines }) => {
        const points: number[] = []
        for (let i = -3; i <= 3; i += 1) points.push(i * 0.42, 0, -1.15, i * 0.42, 0, 1.15)
        for (let i = -2; i <= 2; i += 1) points.push(-1.55, 0, i * 0.46, 1.55, 0, i * 0.46)
        addLines(points, 0.6)
      })

      buildLayer('interpretation', accent, true, ({ addWire, addFace }) => {
        addWire(new THREE.IcosahedronGeometry(0.8, 1), 0.5)
        addFace(new THREE.IcosahedronGeometry(0.76, 1), 0.05)
      })

      buildLayer('criteria', accent, false, ({ addWire, group }) => {
        // Rings are tilted rather than flat or camera-facing: at a glancing
        // angle they read as two hoops around the stack, not as targets.
        group.rotation.x = Math.PI * 0.3
        addWire(new THREE.TorusGeometry(1.2, 0.006, 6, 96), 0.8)
        addWire(new THREE.TorusGeometry(0.82, 0.005, 6, 84), 0.5)
      })

      buildLayer('assessment', accent, true, ({ addLines, addFace }) => {
        addFace(new THREE.RingGeometry(0.55, 1.45, 64, 1), 0.05)
        const spokes: number[] = []
        for (let i = 0; i < 12; i += 1) {
          const angle = (i / 12) * Math.PI * 2
          spokes.push(
            Math.cos(angle) * 0.55,
            0,
            Math.sin(angle) * 0.55,
            Math.cos(angle) * 1.45,
            0,
            Math.sin(angle) * 1.45,
          )
        }
        addLines(spokes, 0.7)
      })

      buildLayer('verification', accent, true, ({ addEdges, addFace }) => {
        addEdges(new THREE.OctahedronGeometry(1.05, 0), 0.9)
        addFace(new THREE.OctahedronGeometry(0.38, 0), 0.16)
      })

      buildLayer('review', graphite, false, ({ addWire, group }) => {
        group.rotation.x = Math.PI * 0.3
        addWire(new THREE.TorusGeometry(1.1, 0.005, 6, 80), 0.65)
        const second = new THREE.Group()
        second.rotation.set(0, 0.5, 0.4)
        const geometry = track(new THREE.TorusGeometry(0.76, 0.01, 6, 64))
        const wire = track(new THREE.WireframeGeometry(geometry))
        const material = track(
          new THREE.LineBasicMaterial({ color: graphite, transparent: true, opacity: 0.45 }),
        )
        second.add(new THREE.LineSegments(wire, material))
        group.add(second)

        const flag = new THREE.Mesh(
          track(new THREE.SphereGeometry(0.07, 14, 14)),
          track(new THREE.MeshBasicMaterial({ color: amber })),
        )
        flag.position.set(1.2, 0.06, 0)
        group.add(flag)
      })

      buildLayer('report', accent, false, ({ addLines, addFace }) => {
        addFace(new THREE.PlaneGeometry(3.1, 2.1), 0.04)
        const rows: number[] = []
        for (let i = -2; i <= 2; i += 1) rows.push(-1.5, 0.01, i * 0.4, 1.5, 0.01, i * 0.4)
        rows.push(-1.5, 0.01, -0.8, 1.5, 0.01, -0.8)
        addLines(rows, 0.55)
      })

      // A faint dust of points gives the structure depth without a starfield.
      const dustCount = 280
      const dustPositions = new Float32Array(dustCount * 3)
      for (let i = 0; i < dustCount; i += 1) {
        const radius = 3.4 + Math.random() * 4
        const theta = Math.random() * Math.PI * 2
        dustPositions[i * 3] = radius * Math.cos(theta)
        dustPositions[i * 3 + 1] = (Math.random() - 0.5) * 9
        dustPositions[i * 3 + 2] = radius * Math.sin(theta)
      }
      const dustGeometry = track(new THREE.BufferGeometry())
      dustGeometry.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3))
      const dustMaterial = track(
        new THREE.PointsMaterial({
          color: graphite,
          size: 0.022,
          transparent: true,
          opacity: 0.45,
          depthWrite: false,
        }),
      )
      const dust = new THREE.Points(dustGeometry, dustMaterial)
      scene.add(dust)

      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      const state = {
        rotationX: 0,
        rotationY: 0,
        targetX: 0.12,
        targetY: 0.4,
        velocityX: 0,
        velocityY: 0,
        dragging: false,
        downX: 0,
        downY: 0,
        lastX: 0,
        lastY: 0,
        spread: 1,
        targetSpread: 1,
        focus: -1,
        targetFocus: -1,
        visible: true,
      }

      /*
       * The loop's own state lives above sync() because sync() wakes the loop on
       * every input: declaring these further down left `frame` in its temporal
       * dead zone on the first call and aborted the scene into the SVG fallback.
       */
      let frame = 0
      let last = 0
      /*
       * The scene renders only while something is actually moving. Its easing
       * curves approach their targets asymptotically, so once the summed change
       * per frame drops below a sub-pixel threshold there is nothing left to
       * draw and the loop stops — a still instrument on screen costs no frames.
       */
      let signaturePrev = Number.NEGATIVE_INFINITY

      const sync = () => {
        state.targetFocus = selectedRef.current
          ? layers.findIndex((layer) => layer.id === selectedRef.current)
          : -1
        state.targetSpread = explodedRef.current ? 1 : 0.1
        // The loop sleeps when the scene is at rest, so every input has to wake it.
        schedule()
      }
      sync()

      let sized = { width: 0, height: 0 }
      const resize = () => {
        const width = element.clientWidth
        const height = element.clientHeight
        if (width === 0 || height === 0) return
        sized = { width, height }
        renderer.setSize(width, height, false)
        camera.aspect = width / height
        camera.updateProjectionMatrix()
      }

      /*
       * The stage can be measured before the pinned layout settles (a pinned
       * element that has just been switched to fixed can report 0 for a frame),
       * which would leave the drawing buffer at the canvas default and render a
       * blurry 300×150 scene. Re-checking the size before each frame is a couple
       * of property reads and makes the buffer self-healing.
       */
      const ensureSize = () => {
        if (element.clientWidth !== sized.width || element.clientHeight !== sized.height) {
          resize()
        }
      }

      const raycaster = new THREE.Raycaster()
      const pointer = new THREE.Vector2(-2, -2)

      const onPointerDown = (event: PointerEvent) => {
        state.dragging = true
        state.downX = event.clientX
        state.downY = event.clientY
        state.lastX = event.clientX
        state.lastY = event.clientY
        renderer.domElement.setPointerCapture(event.pointerId)
        renderer.domElement.classList.add('is-dragging')
        // The loop sleeps at rest, so every input has to wake it.
        schedule()
      }

      const onPointerMove = (event: PointerEvent) => {
        const bounds = renderer.domElement.getBoundingClientRect()
        if (bounds.width > 0 && bounds.height > 0) {
          pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
          pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
        }
        if (!state.dragging) return
        const dx = event.clientX - state.lastX
        const dy = event.clientY - state.lastY
        state.targetY += dx * 0.006
        state.targetX += dy * 0.004
        state.velocityY = dx * 0.001
        state.velocityX = dy * 0.0007
        state.lastX = event.clientX
        state.lastY = event.clientY
        schedule()
      }

      const onPointerUp = (event: PointerEvent) => {
        state.dragging = false
        renderer.domElement.classList.remove('is-dragging')
        if (renderer.domElement.hasPointerCapture(event.pointerId)) {
          renderer.domElement.releasePointerCapture(event.pointerId)
        }
        // Inertia keeps running after the pointer lifts.
        schedule()
        const travel =
          Math.abs(event.clientX - state.downX) + Math.abs(event.clientY - state.downY)
        if (travel > 6) return

        raycaster.setFromCamera(pointer, camera)
        const hits = raycaster.intersectObjects(
          layers.map((layer) => layer.group),
          true,
        )
        if (hits.length === 0) return
        let node: ThreeTypes.Object3D | null = hits[0].object
        const owner = () => layers.find((layer) => layer.group === node)
        while (node && !owner()) node = node.parent
        const hit = owner()
        if (!hit) return
        select(hit.id === selectedRef.current ? null : hit.id)
      }

      const onPointerLeave = () => {
        state.dragging = false
        pointer.set(-2, -2)
      }

      renderer.domElement.addEventListener('pointerdown', onPointerDown)
      renderer.domElement.addEventListener('pointermove', onPointerMove)
      renderer.domElement.addEventListener('pointerup', onPointerUp)
      renderer.domElement.addEventListener('pointerleave', onPointerLeave)

      /*
       * A lost GPU context — a driver reset, sleep/wake, or switching graphics
       * adapters — would otherwise leave an empty black stage with a "drag to
       * rotate" hint and controls that quietly do nothing. Falling back to the
       * SVG diagram keeps the section usable and says what happened.
       */
      const onContextLost = (event: Event) => {
        event.preventDefault()
        if (frame !== 0) {
          window.cancelAnimationFrame(frame)
          frame = 0
        }
        setStatus('fallback')
      }
      renderer.domElement.addEventListener('webglcontextlost', onContextLost)

      const observer =
        typeof ResizeObserver === 'undefined'
          ? null
          : new ResizeObserver(() => {
              resize()
              if (reduced) tick(0)
            })
      observer?.observe(element)

      function tick(stamp: number) {
        if (frame !== 0) {
          window.cancelAnimationFrame(frame)
          frame = 0
        }
        ensureSize()
        const dt = last === 0 ? 16 : Math.min(40, stamp - last || 16)
        last = stamp

        const settle = reduced ? 1 : Math.min(1, dt / 150)
        state.rotationX += (state.targetX - state.rotationX) * settle
        state.rotationY += (state.targetY - state.rotationY) * settle
        state.spread += (state.targetSpread - state.spread) * Math.min(1, dt / 240)

        if (!reduced) {
          state.targetY += state.velocityY * (dt / 16)
          state.targetX += state.velocityX * (dt / 16)
          state.velocityY *= 0.93
          state.velocityX *= 0.93
        }

        spindle.rotation.x = state.rotationX * 0.55
        spindle.rotation.y = state.rotationY

        const spacing = 0.26 + state.spread * 0.52
        layers.forEach((layer, index) => {
          const isFocus = state.targetFocus === index
          const isOther = state.targetFocus >= 0 && !isFocus
          const targetY = (index - 3.5) * spacing + (isOther ? (index < state.targetFocus ? -0.7 : 0.7) : 0)
          layer.group.position.y += (targetY - layer.group.position.y) * Math.min(1, dt / 200)

          const targetScale = isFocus ? 1.12 : 1
          const scale = layer.group.scale.x + (targetScale - layer.group.scale.x) * Math.min(1, dt / 180)
          layer.group.scale.setScalar(scale)

          const factor = isOther ? 0.16 : isFocus ? 1.35 : 0.82
          layer.factor += (factor - layer.factor) * Math.min(1, dt / 180)
          for (const part of layer.parts) {
            part.material.opacity = Math.min(1, part.base * layer.factor)
          }
          layer.group.rotation.y = (index % 2 === 0 ? 1 : -1) * state.rotationY * 0.1
        })

        const focusY = state.targetFocus >= 0 ? (state.targetFocus - 3.5) * spacing * 0.5 : 0
        camera.position.y += (0.4 + focusY * 0.3 - camera.position.y) * Math.min(1, dt / 260)
        camera.lookAt(0, focusY * 0.6, 0)

        renderer.render(scene, camera)

        const signature =
          state.rotationX * 3 +
          state.rotationY * 5 +
          state.spread * 7 +
          camera.position.y * 11 +
          layers.reduce(
            (sum, layer) => sum + layer.group.position.y + layer.group.scale.x + layer.factor,
            0,
          )
        const delta = Math.abs(signature - signaturePrev)
        signaturePrev = signature

        if (
          !reduced &&
          state.visible &&
          document.visibilityState === 'visible' &&
          delta > 1e-4
        ) {
          frame = window.requestAnimationFrame(tick)
        }
      }

      function schedule() {
        if (reduced) {
          tick(0)
          return
        }
        if (frame === 0) frame = window.requestAnimationFrame(tick)
      }

      const intersection =
        typeof IntersectionObserver === 'undefined'
          ? null
          : new IntersectionObserver((entries) => {
              state.visible = entries.some((entry) => entry.isIntersecting)
              if (state.visible) {
                last = 0
                schedule()
              }
            })
      intersection?.observe(element)

      const onVisibility = () => {
        if (document.visibilityState === 'visible') {
          last = 0
          schedule()
        }
      }
      document.addEventListener('visibilitychange', onVisibility)

      apiRef.current = {
        sync,
        reset: () => {
          state.targetX = 0.16
          state.targetY = 0.4
          state.velocityX = 0
          state.velocityY = 0
          sync()
          schedule()
        },
      }

      /*
       * Scroll can drive the stack from assembled to exploded while the
       * instrument is pinned. It only speaks through the spread value, so a
       * visitor who clicks Assemble or selects a layer keeps control: manual
       * input simply wins until the next scroll event.
       */
      const onSpread = (event: Event) => {
        const detail = (event as CustomEvent<{ progress: number }>).detail
        if (!detail) return
        state.targetSpread = 0.08 + Math.min(1, Math.max(0, detail.progress)) * 0.92
        state.visible = true
        schedule()
      }
      window.addEventListener('aetrix:instrument-spread', onSpread)

      setStatus('ready')
      resize()
      window.requestAnimationFrame(resize)
      schedule()

      cleanup = () => {
        if (frame !== 0) window.cancelAnimationFrame(frame)
        window.removeEventListener('aetrix:instrument-spread', onSpread)
        document.removeEventListener('visibilitychange', onVisibility)
        renderer.domElement.removeEventListener('pointerdown', onPointerDown)
        renderer.domElement.removeEventListener('pointermove', onPointerMove)
        renderer.domElement.removeEventListener('pointerup', onPointerUp)
        renderer.domElement.removeEventListener('pointerleave', onPointerLeave)
        renderer.domElement.removeEventListener('webglcontextlost', onContextLost)
        observer?.disconnect()
        intersection?.disconnect()
        apiRef.current = null
        for (const item of disposables) item.dispose()
        renderer.dispose()
        renderer.domElement.remove()
      }
    }

    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(
            (entries) => {
              if (!entries.some((entry) => entry.isIntersecting)) return
              observer?.disconnect()
              void start().catch((error) => {
                if (disposed) return
                console.warn('[instrument] could not start the 3D scene:', error)
                setStatus('fallback')
              })
            },
            { rootMargin: '300px 0px' },
          )

    if (observer) observer.observe(element)
    else
      void start().catch((error) => {
        console.warn('[instrument] could not start the 3D scene:', error)
        setStatus('fallback')
      })

    return () => {
      disposed = true
      observer?.disconnect()
      cleanup?.()
    }
  }, [select])

  const active = LAYERS.find((layer) => layer.id === selected) ?? null

  return (
    <section className="mk-instrument" id="instrument" aria-labelledby="instrument-title">
      {/* Static wash: the 3D scene already supplies depth, so this act does not
          run another full-screen shader behind it. */}
      <div className="mk-instrument__bg" aria-hidden="true" />

      <div className="shell">
        <header className="mk-head mk-head--split" data-reveal>
          <div>
            <p className="mk-eyebrow">
              <span className="mono">04</span>
              <span>The instrument</span>
            </p>
            <h2 className="mk-h2" id="instrument-title">
              Eight layers, one correction.
            </h2>
          </div>
          <p className="mk-note">
            {status === 'fallback'
              ? 'The pipeline as a stack of eight layers. This browser cannot render WebGL2, so the stack is drawn flat instead of as a turnable object: it assembles and separates as you scroll, and choosing a layer still isolates it.'
              : 'The pipeline, as an object you can turn over. Drag to rotate; choose a layer to isolate it and read what it does. The stages are real; the geometry is only a way of seeing them.'}
          </p>
        </header>

        <div className="mk-instrument__body">
          <div className="instr">
            <div className="instr__stage" ref={host}>
              <div className="instr__fallback-wrap" data-hidden={status === 'ready' ? '' : undefined}>
                <InstrumentFallback active={selected} exploded={exploded} />
              </div>
              <span className="instr__hint mono" aria-hidden="true">
                {status === 'fallback'
                  ? 'Flat diagram · WebGL2 unavailable in this browser'
                  : 'Drag to rotate · click a layer'}
              </span>
            </div>

            <div className="instr__readout">
              <div className="instr__controls">
                <button
                  type="button"
                  className="instr__control"
                  aria-pressed={exploded}
                  onClick={toggleExploded}
                >
                  <span className="mono">{exploded ? 'Assemble' : 'Explode'}</span>
                </button>
                <button type="button" className="instr__control" onClick={reset}>
                  <span className="mono">Reset view</span>
                </button>
              </div>

              <div className="instr__detail" aria-live="polite">
                {active ? (
                  <>
                    <p className="instr__code mono">
                      {active.code} · {active.state}
                    </p>
                    <h3 className="instr__name">{active.name}</h3>
                    <p className="instr__copy">{active.detail}</p>
                  </>
                ) : (
                  <>
                    <p className="instr__code mono">Complete structure</p>
                    <h3 className="instr__name">The correction instrument</h3>
                    <p className="instr__copy">
                      Every layer in the order the engine works through it, from
                      the scan to the report. Select one to see where it sits and
                      what it is responsible for.
                    </p>
                  </>
                )}
              </div>

              <ol className="instr__layers" aria-label="Pipeline layers">
                {LAYERS.map((layer) => (
                  <li key={layer.id}>
                    <button
                      type="button"
                      className="instr__layer"
                      aria-pressed={selected === layer.id}
                      data-state={
                        layer.state === 'Provider unverified'
                          ? 'warn'
                          : layer.state === 'Not integrated'
                            ? 'gap'
                            : 'ok'
                      }
                      onClick={() => select(selected === layer.id ? null : layer.id)}
                    >
                      <span className="mono instr__layer-code">{layer.code}</span>
                      <span className="instr__layer-name">{layer.name}</span>
                      <Icon name="chevron" size={12} />
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </div>

        <p className="mk-figcaption mono">
          Interactive diagram · geometry illustrates the workflow, not internal architecture
        </p>
      </div>
    </section>
  )
}

/**
 * The WebGL-free instrument: the same eight layers, drawn flat in SVG.
 *
 * It is not a dead picture. The stack listens to the same scroll channel as the
 * 3D scene (`aetrix:instrument-spread`) and to the Assemble/Explode control, so
 * it assembles and separates in step with the pin, and selecting a layer still
 * isolates and labels it. Only the third dimension is missing — which is
 * exactly what the hint says.
 */
function InstrumentFallback({ active, exploded }: { active: string | null; exploded: boolean }) {
  const root = useRef<SVGSVGElement>(null)

  useEffect(() => {
    const element = root.current
    if (!element) return

    // Gap between layers: tight when assembled, wide when exploded.
    const apply = (spread: number) => {
      element.style.setProperty('--fb-gap', String(20 + spread * 58))
    }

    apply(exploded ? 1 : 0.06)

    const onSpread = (event: Event) => {
      const detail = (event as CustomEvent<{ progress: number }>).detail
      if (!detail) return
      apply(0.06 + Math.min(1, Math.max(0, detail.progress)) * 0.94)
    }
    window.addEventListener('aetrix:instrument-spread', onSpread)
    return () => window.removeEventListener('aetrix:instrument-spread', onSpread)
  }, [exploded])

  return (
    <svg ref={root} className="instr__fallback" viewBox="0 0 520 620" fill="none" aria-hidden="true">
      <path className="instr__fb-spine" d="M260 40v540" />
      {LAYERS.map((layer, index) => {
        const selected = active === layer.id
        return (
          <g
            key={layer.id}
            className="instr__fb-layer"
            style={{ '--fb-i': index } as CSSProperties}
            data-active={selected ? '' : undefined}
          >
            <ellipse cx="260" cy="310" rx={selected ? 172 : 138} ry={selected ? 27 : 19} />
            <text x="300" y="315">
              {layer.code} · {layer.name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
