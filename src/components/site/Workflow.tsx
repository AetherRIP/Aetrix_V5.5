import { vars } from '../../lib/hooks'
import { Icon } from '../ui/Icons'
import { SectionHead } from './SectionHead'

const STEPS = [
  {
    title: 'Create the assignment',
    text: 'Name the paper, choose the class, attach the mark scheme. The scheme is read into a fixed question list with its official maximum marks.',
    output: 'Assignment · scheme blueprint',
  },
  {
    title: 'Upload the submissions',
    text: 'Add a class set of scans, or pull them from Google Classroom. Each file is validated, then bound to one student and one assignment.',
    output: 'Submissions in R2',
  },
  {
    title: 'Let the pipeline mark',
    text: 'A queued job prepares the script, marks it against the blueprint and reconciles every question. Nothing is marked in the browser.',
    output: 'Provisional marks',
  },
  {
    title: 'Review what is uncertain',
    text: 'Anything ambiguous arrives as Needs review, never as a zero. Change a mark, record the reason, and keep the original beside it.',
    output: 'Reviewed results',
  },
  {
    title: 'Approve the results',
    text: 'Approval recomputes totals from the question set and writes an audit entry naming who approved what, and when.',
    output: 'Approved marks',
  },
  {
    title: 'Report, then publish',
    text: 'Generate the class report, then optionally attach it and publish draft grades to Classroom as an independent step.',
    output: 'Report · Classroom',
  },
] as const

export function Workflow() {
  return (
    <section className="section" id="workflow" aria-labelledby="workflow-title">
      <div className="shell">
        <SectionHead
          id="workflow-title"
          title="Six steps from a stack of scripts to a published grade."
          note="This is the intended workflow of the rebuild, drawn from the product blueprint. Each step names what it produces, because a marking system should always be able to say what state a script is in."
        />

        <ol className="steps">
          {STEPS.map((step, index) => (
            <li
              key={step.title}
              className="step"
              data-reveal
              style={vars({ '--reveal-delay': `${index * 55}ms` })}
            >
              <span className="step__index mono">
                {String(index + 1).padStart(2, '0')}
              </span>
              <h3 className="step__title">{step.title}</h3>
              <p className="step__text">{step.text}</p>
              <p className="step__output">
                <Icon name="arrow" size={12} />
                <span>{step.output}</span>
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
