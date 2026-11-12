import { useRef } from 'react'
import { usePointerLamp } from '../../lib/hooks'

/**
 * The page's ambient field: the drafting grid, three slow pools of light that
 * every translucent pane refracts, and one lamp that follows the pointer. All of
 * it is decorative and inert — it never receives a pointer event, carries no
 * information, and is removed entirely when motion is reduced.
 */
export function AmbientField() {
  const field = useRef<HTMLDivElement>(null)
  usePointerLamp(field)

  return (
    <div className="field" aria-hidden="true" ref={field}>
      <div className="field__grid" />
      <div className="field__glow field__glow--lead" />
      <div className="field__glow field__glow--mid" />
      <div className="field__glow field__glow--foot" />
      <div className="field__lamp" data-lamp />
    </div>
  )
}
