import type { ReactNode } from 'react'
import { StatePanel } from './StatePanel'
import type { Loaded } from '../../lib/api/useResource'

/** Shared rendering for the four states every engine read can be in. */
export function DataState({
  state,
  capability,
  children,
  empty,
}: {
  state: Loaded<unknown>
  capability: string
  children?: ReactNode
  empty?: ReactNode
}) {
  if (state.state === 'loading') {
    return (
      <p className="app-hint mono" role="status" aria-live="polite">
        Loading from the engine…
      </p>
    )
  }
  if (state.state === 'error') {
    return (
      <StatePanel tone="error" title={state.reason} capability={capability}>
        <p>
          {state.code === 403
            ? 'The engine refused this account. Ask a workspace owner to check your role.'
            : 'The engine answered with an error. Nothing is being guessed.'}
        </p>
      </StatePanel>
    )
  }
  if (state.state === 'unavailable') {
    return (
      <StatePanel tone="wip" title="The engine did not answer this screen" capability={capability}>
        <p>{state.reason}</p>
      </StatePanel>
    )
  }
  return <>{children ?? empty}</>
}
