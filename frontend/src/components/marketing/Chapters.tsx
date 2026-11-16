import { Act } from './Act'
import {
  AssessScene,
  CaptureScene,
  ReportScene,
  ReviewScene,
  UnderstandScene,
  VerifyScene,
} from './ChapterScenes'

const CHAPTERS = [
  {
    id: 'capture',
    numeral: '01',
    key: 'Capture',
    title: 'A class set enters the engine.',
    lede: 'Pages, not screenshots.',
    body: 'Each scan is validated, rendered to pages and bound to one student and one assignment before a single question is read. The file is stored by the engine that will mark it.',
    state: 'Implemented · ingestion and page rendering',
    tone: 'engine',
    scene: CaptureScene,
  },
  {
    id: 'understand',
    numeral: '02',
    key: 'Understand',
    title: 'The paper becomes a question list.',
    lede: 'Structure before marks.',
    body: 'The scheme is read into a fixed question list with its official maximum marks. A teacher approves that blueprint before marking begins, and the blueprint version is locked from then on.',
    state: 'Implemented · extraction creates a draft',
    tone: 'engine',
    scene: UnderstandScene,
  },
  {
    id: 'assess',
    numeral: '03',
    key: 'Assess',
    title: 'Every mark lands on a criterion.',
    lede: 'Judgement, made legible.',
    body: 'A queued job prepares the script, marks it against the locked blueprint and reconciles each question. Nothing is marked in the browser, and a mark can never exceed its question maximum.',
    state: 'Implemented · engine aetrix_v5_5',
    tone: 'engine',
    scene: AssessScene,
  },
  {
    id: 'verify',
    numeral: '04',
    key: 'Verify',
    title: 'Mathematics is checked, where it can be.',
    lede: 'No assumption of correctness.',
    body: 'Reasoning is checked symbolically where a question allows it. A step that does not verify is flagged for review rather than accepted, and the live provider’s accuracy remains unverified.',
    state: 'Provider unverified · no accuracy claimed',
    tone: 'review',
    scene: VerifyScene,
  },
  {
    id: 'review',
    numeral: '05',
    key: 'Review',
    title: 'Uncertainty is a state, not a zero.',
    lede: 'A person decides.',
    body: 'Anything ambiguous arrives as Needs review. A teacher can change a mark, and the original value, the stated reason and the reviewer stay attached to the record — approvals are version-checked.',
    state: 'Implemented · audited overrides',
    tone: 'engine',
    scene: ReviewScene,
  },
  {
    id: 'report',
    numeral: '06',
    key: 'Report',
    title: 'The result answers for itself.',
    lede: 'Totals recomputed from questions.',
    body: 'Reports are built from approved question marks. Attaching a report to Google Classroom and publishing grades are separate steps that are not integrated yet, and the page says so rather than implying otherwise.',
    state: 'Reports implemented · Classroom write-back not integrated',
    tone: 'gap',
    scene: ReportScene,
  },
] as const

/**
 * Act II — the six scenes of a correction, in one frame.
 *
 * Each chapter is a full composition: an original SVG scene and its text. On a
 * pinned desktop they occupy the same stage and hand over to one another —
 * scene draws, text rises, the previous pair leaves upward — while the rail
 * counts through 01…06. Without pinning they are six readable chapters.
 */
export function Chapters() {
  return (
    <Act
      id="chapters"
      kind="chapters"
      label="Six scenes inside one correction"
      scenes={
        <>
          <header className="ch__head">
            <div>
              <p className="mk-eyebrow">
                <span className="mono">03</span>
                <span>Scenes</span>
              </p>
              <h2 className="mk-h2 ch__heading" id="chapters-title">
                Six scenes inside one correction.
              </h2>
            </div>
            <ol className="ch__rail" aria-hidden="true">
              {CHAPTERS.map((chapter, index) => (
                <li key={chapter.id} data-chapter-marker={index}>
                  <span className="mono">{chapter.numeral}</span>
                  <span className="ch__rail-name">{chapter.key}</span>
                </li>
              ))}
              <span className="ch__rail-track">
                <i />
              </span>
            </ol>
          </header>

          {CHAPTERS.map((chapter, index) => {
            const Scene = chapter.scene
            return (
              <article
                className="ch"
                id={chapter.id}
                key={chapter.id}
                data-chapter={index}
                aria-labelledby={`ch-title-${index}`}
              >
                <div className="ch__visual">
                  <div className="ch__frame">
                    <Scene />
                    <span className="ch__frame-label mono">
                      scene {chapter.numeral} · {chapter.key.toLowerCase()}
                    </span>
                  </div>
                </div>

                <div className="ch__text">
                  <p className="ch__numeral mono">
                    <span>{chapter.numeral}</span>
                    <span className="ch__rule" aria-hidden="true" />
                    <span>{chapter.key}</span>
                  </p>
                  <h3 className="ch__title" id={`ch-title-${index}`}>
                    {chapter.title}
                  </h3>
                  <p className="ch__lede">{chapter.lede}</p>
                  <p className="ch__body">{chapter.body}</p>
                  <p className="ch__state mono" data-tone={chapter.tone}>
                    {chapter.state}
                  </p>
                </div>
              </article>
            )
          })}

          <p className="ch__counter mono" aria-hidden="true">
            <span data-chapter-count>01</span> / 06
          </p>
        </>
      }
    />
  )
}
