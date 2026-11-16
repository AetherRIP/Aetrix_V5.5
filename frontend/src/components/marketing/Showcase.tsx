import { ProductPreview } from '../product/ProductPreview'
import { Icon, type IconName } from '../ui/Icons'

const CAPABILITIES: { icon: IconName; title: string; text: string }[] = [
  {
    icon: 'blueprint',
    title: 'Locked blueprint',
    text: 'The question list and its maximum marks are fixed once per assignment, then enforced when marks are written.',
  },
  {
    icon: 'pulse',
    title: 'Correction jobs',
    text: 'Each job reports its stage, its attempts and the reason it parked. A failure is a state with a next action, not a spinner.',
  },
  {
    icon: 'review',
    title: 'Review and overrides',
    text: 'A changed mark keeps the original value, the stated reason and the reviewer beside it.',
  },
  {
    icon: 'records',
    title: 'Class and student records',
    text: 'Rosters and per-student history stay inside the workspace. Nothing is shared across a tenant boundary.',
  },
  {
    icon: 'chart',
    title: 'Question-level reporting',
    text: 'Reports are built from approved question marks rather than inferred from a total.',
  },
  {
    icon: 'assignment',
    title: 'Document pipeline',
    text: 'Uploads are validated, rendered to pages and mapped to questions before extraction begins.',
  },
]

const NOTES = [
  { numeral: '01', label: 'Assignment state', text: 'Lifecycle, scheme version and the class it belongs to.' },
  { numeral: '02', label: 'Question ledger', text: 'Every question with its maximum, awarded mark and state.' },
  { numeral: '03', label: 'Exceptions', text: 'What could not be settled, waiting for a person.' },
]

/**
 * The product film: the real console component, framed like a screen and
 * annotated rather than mocked up. The panel is populated with the repository's
 * synthetic demonstration set and says so on its own chrome — this is the actual
 * interface component, not a screenshot and not a live workspace.
 */
export function Showcase() {
  return (
    <section className="mk-showcase mk-section" id="platform" aria-labelledby="platform-title">
      <div className="shell">
        <header className="mk-head mk-head--split" data-reveal>
          <div>
            <p className="mk-eyebrow">
              <span className="mono">06</span>
              <span>The platform</span>
            </p>
            <h2 className="mk-h2" id="platform-title">
              Out of the diagram, into the console.
            </h2>
          </div>
          <p className="mk-note">
            Assignment state, submission progress, question-level marks and the
            exceptions that need a person — in one view. This is the interface
            component itself, populated with synthetic demonstration data; the
            authenticated console is not deployed.
          </p>
        </header>

        <div className="film">
          <div className="film__notes">
            {NOTES.map((note) => (
              <article className="film__note" key={note.numeral} data-reveal>
                <span className="film__note-numeral mono">{note.numeral}</span>
                <h3 className="film__note-label">{note.label}</h3>
                <p className="film__note-text">{note.text}</p>
              </article>
            ))}
          </div>

          <div className="film__frame" data-reveal>
            <div className="film__chrome" aria-hidden="true">
              <span />
              <span />
              <span />
              <p className="mono">aetrix / workspace / assignments / homework 6</p>
            </div>
            <div className="film__body">
              <ProductPreview />
            </div>
            <p className="film__hint">
              Swipe the console to see the whole workspace
            </p>
          </div>
        </div>

        <div className="mk-capabilities" id="features">
          {CAPABILITIES.map((capability) => (
            <article className="mk-capability" key={capability.title} data-reveal>
              <span className="mk-capability__icon">
                <Icon name={capability.icon} size={18} />
              </span>
              <h3 className="mk-capability__title">{capability.title}</h3>
              <p className="mk-capability__text">{capability.text}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
