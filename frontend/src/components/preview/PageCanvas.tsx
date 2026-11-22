import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { ApiResult } from '../../lib/api/client'

type Drag = { x: number; y: number; startX: number; startY: number; active: boolean }

/**
 * A rendered document page with real zoom and pan.
 *
 * The image is fetched with the session token (an `<img src>` cannot carry a
 * bearer header), shown from an object URL, and released when the page changes.
 * Nothing is cropped: a stored question-page mapping names the page, not a
 * region, so the whole page is the honest unit of evidence.
 */
export function PageCanvas({
  load,
  refreshKey,
  alt,
  emptyNote,
}: {
  load: (signal: AbortSignal) => Promise<ApiResult<Blob>>
  refreshKey: string
  alt: string
  emptyNote?: string
}) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [zoom, setZoom] = useState(1)
  const [drag, setDrag] = useState<Drag>({ x: 0, y: 0, startX: 0, startY: 0, active: false })
  const loader = useRef(load)
  loader.current = load
  const stage = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | null = null
    let live = true
    setLoading(true)
    setError(null)
    setZoom(1)
    setDrag({ x: 0, y: 0, startX: 0, startY: 0, active: false })
    void loader.current(controller.signal).then((result) => {
      if (!live) return
      setLoading(false)
      if (result.status === 'ok') {
        objectUrl = URL.createObjectURL(result.data)
        setUrl(objectUrl)
      } else {
        setUrl(null)
        setError(result.reason)
      }
    })
    return () => {
      live = false
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      setUrl(null)
    }
  }, [refreshKey])

  useEffect(() => {
    if (zoom <= 1 && (drag.x !== 0 || drag.y !== 0)) {
      setDrag({ x: 0, y: 0, startX: 0, startY: 0, active: false })
    }
  }, [zoom, drag.x, drag.y])

  function zoomBy(delta: number) {
    setZoom((value) => Math.min(3, Math.max(0.5, Math.round((value + delta) * 100) / 100)))
  }

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (zoom <= 1) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({
      x: drag.x,
      y: drag.y,
      startX: event.clientX,
      startY: event.clientY,
      active: true,
    })
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!drag.active) return
    setDrag({
      x: drag.x + (event.clientX - drag.startX),
      y: drag.y + (event.clientY - drag.startY),
      startX: event.clientX,
      startY: event.clientY,
      active: true,
    })
  }

  function endDrag(event: React.PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setDrag((value) => ({ ...value, active: false }))
  }

  return (
    <div className="cp-viewer">
      <div className="cp-viewer__bar">
        <span className="cp-viewer__zoomlabel mono">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className="cp-viewer__control"
          onClick={() => zoomBy(-0.25)}
          disabled={zoom <= 0.5 || loading}
          aria-label="Zoom out"
        >
          −
        </button>
        <button
          type="button"
          className="cp-viewer__control"
          onClick={() => zoomBy(0.25)}
          disabled={zoom >= 3 || loading}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className="cp-viewer__control cp-viewer__control--wide"
          onClick={() => {
            setZoom(1)
            setDrag({ x: 0, y: 0, startX: 0, startY: 0, active: false })
          }}
          disabled={zoom === 1 || loading}
        >
          Fit
        </button>
        <span className="cp-viewer__hint mono">
          {zoom > 1 ? 'Drag to pan' : 'Zoom to inspect'}
        </span>
      </div>

      <div
        ref={stage}
        className="cp-viewer__stage"
        data-dragging={drag.active ? 'true' : undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {loading ? (
          <p className="cp-viewer__state mono" role="status" aria-live="polite">
            Loading page…
          </p>
        ) : error ? (
          <p className="cp-viewer__state" data-tone="error">
            {error}
          </p>
        ) : url ? (
          <img
            className="cp-viewer__image"
            src={url}
            alt={alt}
            draggable={false}
            style={
              {
                transform: `translate(${drag.x}px, ${drag.y}px) scale(${zoom})`,
                '--zoom': zoom,
              } as CSSProperties
            }
          />
        ) : (
          <p className="cp-viewer__state">{emptyNote ?? 'No page is available to display.'}</p>
        )}
      </div>
    </div>
  )
}
