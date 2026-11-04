import { vars } from '../../lib/hooks'
import { Icon, type IconName } from '../ui/Icons'
import { SectionHead } from './SectionHead'

const FEATURES: { icon: IconName; title: string; text: string; detail: string }[] = [
  {
    icon: 'sparkle',
    title: 'AI-assisted marking',
    text: 'Every script is marked against the scheme with a fixed seed and no temperature, so the same answer earns the same mark twice.',
    detail: 'Server-side · deterministic',
  },
  {
    icon: 'blueprint',
    title: 'Mark-scheme blueprint',
    text: 'The question list and its maximum marks are fixed once per assignment, then enforced when marks are written.',
    detail: 'Locked per assignment',
  },
  {
    icon: 'review',
    title: 'Human review and overrides',
    text: 'A person decides every mark that matters. Overrides keep the original value, the reason and the reviewer.',
    detail: 'Audited · reversible',
  },
  {
    icon: 'assignment',
    title: 'Assignment management',
    text: 'One place for the paper, the scheme, the class and the state of the marking, from draft through to published.',
    detail: 'Lifecycle · owned',
  },
  {
    icon: 'records',
    title: 'Class and student records',
    text: 'Rosters and per-student history stay inside the workspace. Nothing is shared across a tenant boundary.',
    detail: 'Workspace-scoped',
  },
  {
    icon: 'pulse',
    title: 'Correction-job monitoring',
    text: 'Each job reports its stage, its attempts and the reason it parked. A failure is a state with a next action, not a spinner.',
    detail: 'Queues · idempotent',
  },
  {
    icon: 'chart',
    title: 'Reports and analytics',
    text: 'Question-level analysis, distributions and trends, generated from the approved marks rather than inferred from them.',
    detail: 'Report · class level',
  },
  {
    icon: 'classroom',
    title: 'Google Classroom',
    text: 'Courses, coursework and submissions can be read in; reports and draft grades can be written back, each as its own operation.',
    detail: 'Integration · optional',
  },
]

export function Features() {
  return (
    <section className="section" id="features" aria-labelledby="features-title">
      <div className="shell">
        <SectionHead
          id="features-title"
          title="Built for the judgement, not just the throughput."
          note="Eight capabilities define the product. None of them is claimed as live on this page: MathChecker V5.5 is a pre-release build, and the marking pipeline is specified and in active development."
        />

        <div className="feature-matrix">
          {FEATURES.map((feature, index) => (
            <article
              key={feature.title}
              className="feature"
              data-reveal
              style={vars({ '--reveal-delay': `${(index % 4) * 50}ms` })}
            >
              <span className="feature__icon">
                <Icon name={feature.icon} size={20} />
              </span>
              <h3 className="feature__title">{feature.title}</h3>
              <p className="feature__text">{feature.text}</p>
              <p className="feature__detail mono">{feature.detail}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
