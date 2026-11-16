import { useEffect, useRef } from 'react'

/**
 * The page's ambient shader: a warped coordinate field drawn on the GPU.
 *
 * A full-screen quad runs one fragment shader — domain-warped noise displacing a
 * fine grid, a slow sweep, and a soft pool of light that follows the pointer.
 * It is the mathematical environment the whole page sits inside, not decoration
 * for its own sake: the same field appears behind the hero and the closing
 * scene, so the visitor stays in one world.
 *
 * Cost control, because this runs on every marketing page view:
 * - the WebGL context is created only when the canvas comes near the viewport,
 *   so a visitor who never scrolls to the closing scene never pays for its
 *   context or its texture memory;
 * - the backing buffer is drawn at ~0.68 of the CSS size. The field is a soft,
 *   low-contrast gradient, so the upscale is invisible while the fill-rate cost
 *   drops by more than half;
 * - it paints at 30fps. The drift is 0.045× time, so half-rate is
 *   indistinguishable and halves the continuous GPU and compositing work;
 * - rendering stops when the canvas is off-screen or the tab is hidden, and the
 *   pointer listener does no layout work while the canvas is not visible;
 * - reduced motion gets one still frame.
 *
 * If WebGL is missing or the shader fails to compile, the canvas reports the
 * failure and the CSS background underneath remains — no blank hero, no thrown
 * error.
 */

const VERTEX = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`

const FRAGMENT = `
precision highp float;

uniform vec2 uRes;
uniform vec2 uPointer;
uniform float uTime;
uniform float uIntensity;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x),
    f.y
  );
}

void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * uRes.xy) / uRes.y;
  float t = uTime * 0.045;

  // The field drifts; the pointer bends it like a lens.
  float warp = noise(p * 2.1 + vec2(t, -t * 0.8));
  vec2 lens = p - uPointer;
  float pull = exp(-dot(lens, lens) * 5.0);
  vec2 q = p + vec2(warp - 0.5) * 0.12 + lens * pull * 0.06;

  // Two grids at different scales, faded towards the edges.
  vec2 g1 = q * 13.0;
  vec2 d1 = abs(fract(g1) - 0.5);
  float line1 = smoothstep(0.465, 0.5, max(d1.x, d1.y));
  line1 *= 1.0 - smoothstep(0.15, 1.25, length(p * vec2(0.9, 1.15)));

  vec2 g2 = q * 3.2;
  vec2 d2 = abs(fract(g2) - 0.5);
  float line2 = smoothstep(0.487, 0.5, max(d2.x, d2.y));
  line2 *= 1.0 - smoothstep(0.05, 0.95, length(p));

  float glow = exp(-length(p - uPointer) * 2.4) * 0.5;
  float sweep = smoothstep(0.0, 1.0, sin(p.y * 2.4 - uTime * 0.25) * 0.5 + 0.5);

  vec3 ink = vec3(0.66, 0.78, 0.73);
  vec3 accent = vec3(0.27, 0.84, 0.63);

  float alpha = line1 * 0.16 + line2 * 0.1 + glow * 0.24 + sweep * 0.012;
  vec3 color = mix(ink, accent, clamp(glow * 1.6 + line2 * 0.35, 0.0, 1.0));

  gl_FragColor = vec4(color, alpha * uIntensity);
}
`

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader)
    return null
  }
  return shader
}

/** Backing-buffer scale. Upscaled by the browser; the field is a soft gradient. */
const RENDER_SCALE = 0.68
/** Frame interval: this field is slow enough that 30fps reads as continuous. */
const FRAME_MS = 1000 / 30

export function SignalCanvas({
  className,
  intensity = 1,
}: {
  className?: string
  intensity?: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    let stop: (() => void) | undefined
    let disposed = false

    const boot = () => {
      if (disposed || stop) return

      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      const gl = canvas.getContext('webgl', {
        alpha: true,
        antialias: false,
        depth: false,
        stencil: false,
        premultipliedAlpha: false,
        powerPreference: 'low-power',
      })

      if (!gl) {
        canvas.dataset.unavailable = ''
        return
      }

      const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX)
      const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT)
      const program = gl.createProgram()
      if (!vertex || !fragment || !program) {
        canvas.dataset.unavailable = ''
        return
      }
      gl.attachShader(program, vertex)
      gl.attachShader(program, fragment)
      gl.linkProgram(program)
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        canvas.dataset.unavailable = ''
        return
      }
      gl.useProgram(program)

      const buffer = gl.createBuffer()
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
      const aPos = gl.getAttribLocation(program, 'aPos')
      gl.enableVertexAttribArray(aPos)
      gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0)

      const uRes = gl.getUniformLocation(program, 'uRes')
      const uTime = gl.getUniformLocation(program, 'uTime')
      const uPointer = gl.getUniformLocation(program, 'uPointer')
      const uIntensity = gl.getUniformLocation(program, 'uIntensity')

      let width = 0
      let height = 0
      const resize = () => {
        const ratio = Math.min(window.devicePixelRatio || 1, 1.25) * RENDER_SCALE
        const nextWidth = Math.max(1, Math.round(canvas.clientWidth * ratio))
        const nextHeight = Math.max(1, Math.round(canvas.clientHeight * ratio))
        if (nextWidth === width && nextHeight === height) return
        width = nextWidth
        height = nextHeight
        canvas.width = width
        canvas.height = height
        gl.viewport(0, 0, width, height)
        gl.uniform2f(uRes, width, height)
      }

      const pointer = { x: 0.15, y: 0.05 }
      const target = { x: 0.15, y: 0.05 }
      let frame = 0
      let time = 0
      let last = 0
      let painted = 0
      let visible = true

      const draw = () => {
        gl.uniform1f(uTime, time)
        gl.uniform2f(uPointer, pointer.x, pointer.y)
        gl.uniform1f(uIntensity, intensity)
        gl.clearColor(0, 0, 0, 0)
        gl.clear(gl.COLOR_BUFFER_BIT)
        gl.drawArrays(gl.TRIANGLES, 0, 3)
      }

      const paint = (stamp: number) => {
        frame = 0
        const dt = last === 0 ? 16 : Math.min(64, stamp - last)
        last = stamp

        // 30fps cap: skip the frame but keep the loop alive.
        if (stamp - painted < FRAME_MS) {
          if (!reduced && visible && document.visibilityState === 'visible') {
            frame = window.requestAnimationFrame(paint)
          }
          return
        }
        painted = stamp
        time += dt / 1000

        pointer.x += (target.x - pointer.x) * 0.06
        pointer.y += (target.y - pointer.y) * 0.06
        draw()

        if (!reduced && visible && document.visibilityState === 'visible') {
          frame = window.requestAnimationFrame(paint)
        }
      }

      const schedule = () => {
        if (frame === 0) frame = window.requestAnimationFrame(paint)
      }

      const onPointer = (event: PointerEvent) => {
        if (!visible) return
        const bounds = canvas.getBoundingClientRect()
        if (bounds.width === 0 || bounds.height === 0) return
        target.x = (event.clientX - bounds.left - bounds.width / 2) / bounds.height
        target.y = -(event.clientY - bounds.top - bounds.height / 2) / bounds.height
        if (reduced) return
        schedule()
      }

      resize()
      schedule()

      const observer =
        typeof ResizeObserver === 'undefined'
          ? null
          : new ResizeObserver(() => {
              resize()
              if (reduced || !visible) draw()
            })
      observer?.observe(canvas)

      const intersection =
        typeof IntersectionObserver === 'undefined'
          ? null
          : new IntersectionObserver((entries) => {
              visible = entries.some((entry) => entry.isIntersecting)
              if (visible) {
                last = 0
                schedule()
              }
            })
      intersection?.observe(canvas)

      const onVisibility = () => {
        if (document.visibilityState === 'visible') {
          last = 0
          schedule()
        }
      }

      if (!reduced) {
        window.addEventListener('pointermove', onPointer, { passive: true })
        window.addEventListener('resize', resize)
        document.addEventListener('visibilitychange', onVisibility)
      }

      stop = () => {
        if (frame !== 0) window.cancelAnimationFrame(frame)
        frame = 0
        window.removeEventListener('pointermove', onPointer)
        window.removeEventListener('resize', resize)
        document.removeEventListener('visibilitychange', onVisibility)
        observer?.disconnect()
        intersection?.disconnect()
        gl.deleteBuffer(buffer)
        gl.deleteProgram(program)
        gl.deleteShader(vertex)
        gl.deleteShader(fragment)
        gl.getExtension('WEBGL_lose_context')?.loseContext()
      }
    }

    /*
     * Nothing is allocated until the canvas is within 250px of the viewport:
     * the closing scene's field sits seven viewports below the fold, and a
     * visitor who never reaches it should never pay for a second WebGL context.
     */
    if (typeof IntersectionObserver === 'undefined') {
      boot()
    } else {
      const gate = new IntersectionObserver(
        (entries) => {
          if (!entries.some((entry) => entry.isIntersecting)) return
          gate.disconnect()
          boot()
        },
        { rootMargin: '250px 0px' },
      )
      gate.observe(canvas)
      return () => {
        disposed = true
        gate.disconnect()
        stop?.()
      }
    }

    return () => {
      disposed = true
      stop?.()
    }
  }, [intensity])

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />
}
