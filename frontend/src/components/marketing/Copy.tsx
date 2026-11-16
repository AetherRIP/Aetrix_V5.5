import { Fragment } from 'react'

/**
 * Text primitives for the landing page.
 *
 * The hero headline animates per word, so each word is its own element inside a
 * clipped line box — the element rises from behind its own baseline. This is a
 * plain JSX split rather than a runtime text-splitting pass: the words exist in
 * the server-rendered HTML in reading order, a screen reader announces one
 * continuous sentence, and there is no DOM mutation to undo on unmount.
 *
 * The whitespace between words is real text rather than a CSS margin, so the
 * accessible name of the heading reads "Beyond marking." and not "Beyondmarking."
 */

export type HeadlineWord = { text: string; accent?: boolean }

export function MaskedLine({
  words,
  className,
}: {
  words: readonly HeadlineWord[]
  className?: string
}) {
  return (
    <span className={className ? `mk-line ${className}` : 'mk-line'}>
      {words.map((word, index) => (
        <Fragment key={`${word.text}-${index}`}>
          <span className="mk-word">
            <span
              className={word.accent ? 'mk-word__i mk-word__i--accent' : 'mk-word__i'}
              data-arm
            >
              {word.text}
            </span>
          </span>
          {index < words.length - 1 ? ' ' : null}
        </Fragment>
      ))}
    </span>
  )
}

/** Splits a plain sentence into masked words for a multi-line reveal. */
export function MaskedSentence({ text }: { text: string }) {
  return (
    <MaskedLine words={text.split(' ').map((word) => ({ text: word }))} />
  )
}
