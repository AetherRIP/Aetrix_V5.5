import { Icon } from '../ui/Icons'
import { MaskedLine } from './Copy'
import { Lattice } from './Lattice'
import { SignalCanvas } from './SignalCanvas'
import { Act } from './Act'

const FACTS = [
  'Correction runs on the server',
  'A person decides every exception',
  'One workspace, one boundary',
] as const

const SCENES = ['Capture', 'Understand', 'Assess', 'Verify', 'Review', 'Report'] as const

const BEATS = [
  {
    index: '01',
    title: 'A total is a conclusion',
    text: 'Seven out of ten is the end of a process the student never sees. It says what was decided, not how.',
  },
  {
    index: '02',
    title: 'The working is the record',
    text: 'The lines between the question and the answer are where the mathematics happens — and where a mark can be explained.',
  },
  {
    index: '03',
    title: 'Structure is the explanation',
    text: 'Every decision stays attached to the criterion it was awarded against, so the total can be read back into reasons.',
  },
] as const

const CRITERIA = [
  { y: 250, code: 'M1', label: 'Method' },
  { y: 330, code: 'A1', label: 'Accuracy' },
  { y: 410, code: 'B1', label: 'Reasoning' },
  { y: 490, code: 'C1', label: 'Verification' },
] as const

/**
 * Act I — the opening, and the problem that follows from it.
 *
 * Two scenes share one stage. The hero's reasoning lattice contracts toward the
 * page, the copy lifts away, and the student's sheet resolves in the same frame
 * with its working already bracketed by question boundaries and criteria. On a
 * pinned desktop the viewer never leaves the viewport; without pinning the two
 * scenes simply follow one another.
 */
export function Opening() {
  return (
    <Act
      id="opening"
      kind="open"
      label="Introduction and the problem"
      className="mk-opening"
      scenes={
        <>
          {/*
            * The field belongs to the act, not to the first scene: it is the
            * environment both scenes sit in, so the frame never falls to black
            * while the hero hands over to the problem.
            */}
          <div className="act__bg" aria-hidden="true">
            <SignalCanvas className="mk-hero__shader" intensity={1} />
            <div className="hero__glow mk-hero__glow mk-hero__glow--a" />
            <div className="hero__glow mk-hero__glow mk-hero__glow--b" />
            <div className="mk-hero__vignette" />
          </div>

          <div className="scene scene--hero mk-hero" id="hero" data-scene="hero">
            <div className="shell mk-hero__inner">
              <div className="mk-hero__copy">
                <p className="mk-kicker">
                  <span className="mk-kicker__dot" aria-hidden="true" />
                  <span>Mathematics assessment engine</span>
                  <span className="mk-kicker__rule" aria-hidden="true" />
                  <span className="mono">Edexcel IGCSE 4MA1</span>
                </p>

                <h1 className="mk-hero__title" id="hero-title">
                  <MaskedLine words={[{ text: 'Beyond' }, { text: 'marking.' }]} />{' '}
                  <MaskedLine
                    words={[{ text: 'Better' }, { text: 'understanding.', accent: true }]}
                  />
                </h1>

                <p className="mk-hero__lede" data-arm>
                  Intelligent assessment. Transparent reasoning. Meaningful feedback.
                </p>

                <p className="mk-hero__sub" data-arm>
                  Aetrix marks a class set of mathematics against a locked scheme, shows
                  the reasoning behind every mark, and hands every uncertain question to
                  a person.
                </p>

                <div className="mk-hero__actions" data-arm>
                  <a className="btn btn--primary" href="#transformation">
                    Explore Aetrix
                    <Icon name="arrow" size={16} />
                  </a>
                  <a className="btn btn--outline" href="#chapters">
                    Walk the six scenes
                  </a>
                </div>

                <ul className="mk-hero__facts" data-arm>
                  {FACTS.map((fact) => (
                    <li key={fact}>
                      <span className="mono">{fact}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mk-hero__figure" data-arm>
                <Lattice />
                <button
                  type="button"
                  className="mk-hero__replay"
                  onClick={() => window.dispatchEvent(new Event('aetrix:replay-intro'))}
                >
                  <span className="mk-hero__replay-icon" aria-hidden="true">
                    ↺
                  </span>
                  Replay intro
                </button>
              </div>
            </div>

            <nav className="shell mk-hero__rail" aria-label="Chapters">
              <p className="mk-hero__rail-title mono">Six scenes</p>
              <ol>
                {SCENES.map((scene, index) => (
                  <li key={scene}>
                    <a href="#chapters">
                      <span className="mono">{String(index + 1).padStart(2, '0')}</span>
                      {scene}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          </div>

          <div className="scene scene--problem mk-problem" id="problem" data-scene="problem">
            <div className="shell mk-problem__inner">
              <div className="mk-problem__copy">
                <header className="mk-head">
                  <p className="mk-eyebrow">
                    <span className="mono">01</span>
                    <span>The problem</span>
                  </p>
                  <h2 className="mk-h2" id="problem-title">
                    A mark is not an explanation.
                  </h2>
                  <p className="mk-note">
                    A student can be told they scored seven out of ten and still have no
                    idea which decision cost them the other three. The mark is the end of
                    the process; the understanding is in the reasoning that produced it.
                  </p>
                </header>

                <ol className="mk-beats">
                  {BEATS.map((beat, index) => (
                    <li className="mk-beat" key={beat.index} data-beat={index}>
                      <span className="mk-beat__index mono">{beat.index}</span>
                      <div>
                        <h3 className="mk-beat__title">{beat.title}</h3>
                        <p className="mk-beat__text">{beat.text}</p>
                      </div>
                    </li>
                  ))}
                </ol>

                <p className="mk-problem__aside">
                  <Icon name="blueprint" size={14} />
                  <span>
                    Nothing here invents a statistic about marking errors. The contrast is
                    between a total and its reasoning — not a claim about anyone else’s
                    product.
                  </span>
                </p>
              </div>

              <div className="mk-problem__stage">
                <div className="pb" aria-hidden="true">
                  <svg viewBox="0 0 640 760" fill="none" focusable="false">
                    <g className="pb-grid">
                      {[0, 1, 2, 3, 4, 5, 6].map((row) => (
                        <line key={row} x1="0" x2="640" y1={70 + row * 100} y2={70 + row * 100} />
                      ))}
                      {[0, 1, 2, 3, 4, 5].map((column) => (
                        <line key={column} y1="30" y2="730" x1={60 + column * 104} x2={60 + column * 104} />
                      ))}
                    </g>

                    <g className="pb-shard pb-shard--c">
                      <rect x="150" y="150" width="360" height="470" rx="2" />
                      <path className="pb-rule" d="M186 214h240M186 252h288M186 290h180" />
                    </g>
                    <g className="pb-shard pb-shard--b">
                      <rect x="132" y="172" width="360" height="470" rx="2" />
                      <path className="pb-rule" d="M168 236h264M168 274h190M168 312h232" />
                    </g>
                    <g className="pb-shard pb-shard--a">
                      <rect x="112" y="196" width="360" height="470" rx="2" />
                      <path className="pb-margin" d="M150 226v410" />
                      <text className="pb-hand" x="172" y="252">8x − 12 = 5x + 9</text>
                      <path className="pb-rule" d="M172 262h236" />
                      <text className="pb-hand" x="172" y="304">3x = 21</text>
                      <path className="pb-rule" d="M172 314h140" />
                      <text className="pb-hand" x="172" y="356">x = 7</text>
                      <path className="pb-rule" d="M172 366h96" />
                      <text className="pb-hand pb-hand--faint" x="172" y="398">check: 8(7) − 12 = 44</text>
                      <path className="pb-rule pb-rule--faint" d="M172 408h262" />
                      <text className="pb-hand pb-hand--faint" x="172" y="440">5(7) + 9 = 44</text>
                      <path className="pb-rule pb-rule--faint" d="M172 450h182" />
                    </g>

                    <g className="pb-bounds">
                      {[
                        { y: 226, h: 96, label: 'Q3(a)' },
                        { y: 336, h: 78, label: 'Q3(b)' },
                        { y: 424, h: 96, label: 'Q4' },
                      ].map((box) => (
                        <g key={box.label}>
                          <path className="pb-bracket" d={`M92 ${box.y}h-10v${box.h}h10`} />
                          <text className="pb-tag" x="48" y={box.y + 14}>
                            {box.label}
                          </text>
                        </g>
                      ))}
                      <path className="pb-scan" d="M96 200h400" />
                    </g>

                    <g className="pb-criteria">
                      {CRITERIA.map((criterion) => (
                        <g key={criterion.code} className="pb-node">
                          <circle cx="548" cy={criterion.y} r="4" />
                          <path
                            className="pb-link"
                            d={`M472 ${criterion.y - 4} C 512 ${criterion.y - 4}, 520 ${criterion.y}, 544 ${criterion.y}`}
                          />
                          <text className="pb-code" x="564" y={criterion.y + 4}>
                            {criterion.code}
                          </text>
                          <text className="pb-label" x="564" y={criterion.y + 20}>
                            {criterion.label}
                          </text>
                        </g>
                      ))}
                    </g>

                    <g className="pb-tally">
                      <text className="pb-score" x="112" y="712">7 / 10</text>
                      <text className="pb-score-note" x="296" y="712">→</text>
                      {[0, 1, 2, 3].map((index) => (
                        <rect
                          key={index}
                          className="pb-chip"
                          x={344 + index * 34}
                          y="694"
                          width="26"
                          height="26"
                        />
                      ))}
                      <text className="pb-score-note" x="488" y="712">evidence</text>
                    </g>
                  </svg>
                </div>
                <p className="mk-figcaption mono">Illustrative diagram · not a real submission</p>
              </div>
            </div>
          </div>
        </>
      }
    />
  )
}
