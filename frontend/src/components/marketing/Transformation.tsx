const SOLUTION = [
  { y: 132, text: '8x − 12 = 5x + 9' },
  { y: 178, text: '8x − 5x = 9 + 12' },
  { y: 224, text: '3x = 21' },
  { y: 270, text: 'x = 7' },
  { y: 316, text: 'check: 8(7) − 12 = 44' },
] as const

const CRITERIA = [
  { code: 'M1', label: 'Method selected', mark: '1/1', y: 330 },
  { code: 'A1', label: 'Accuracy', mark: '1/1', y: 280 },
  { code: 'B1', label: 'Reasoning shown', mark: '1/1', y: 230 },
  { code: 'C1', label: 'Substitution verified', mark: '1/1', y: 180 },
  { code: 'D1', label: 'Conclusion stated', mark: '0/1', y: 130 },
] as const

const STAGES = [
  {
    letter: 'A',
    title: 'A solution arrives',
    text: 'A class set of scans is stored by the engine, bound to one student and one assignment, and rendered to pages before any marking begins.',
  },
  {
    letter: 'B',
    title: 'The content is extracted',
    text: 'Question boundaries and the working inside them are pulled from the page into a draft extraction, against the approved question list.',
  },
  {
    letter: 'C',
    title: 'Criteria are attached',
    text: 'Each question resolves against the locked blueprint: a fixed question list with its official maximum marks, versioned and immutable.',
  },
  {
    letter: 'D',
    title: 'Marks become evidence',
    text: 'Every award names the criterion it belongs to. A mark cannot exceed its question maximum, and the total is recomputed from the questions.',
  },
  {
    letter: 'E',
    title: 'What is uncertain is flagged',
    text: 'A step that does not verify, or an answer two methods could explain, becomes Needs review — never a silent zero.',
  },
  {
    letter: 'F',
    title: 'The result resolves',
    text: 'The layers settle into a correction report that can be read backwards: from the total, to the criterion, to the working, to the person.',
  },
] as const

/**
 * The signature sequence: one student's working is carried through the engine
 * and comes out as criteria, marks and evidence.
 *
 * The three layers — handwriting, the criterion tree, the evidence lattice —
 * live in one SVG. GSAP scrubs them while the section is pinned and advances six
 * stage captions in step, so the reader drives the transformation. Every mark in
 * the diagram is illustrative; the caption says so.
 */
export function Transformation() {
  return (
    <section
      className="mk-transform"
      id="transformation"
      aria-labelledby="transformation-title"
    >
      <div className="mk-transform__pin">
        <div className="shell mk-transform__inner">
          <header className="mk-transform__head" data-reveal>
            <p className="mk-eyebrow">
              <span className="mono">02</span>
              <span>The transformation</span>
            </p>
            <h2 className="mk-h2" id="transformation-title">
              From working to evidence.
            </h2>
            <p className="mk-note">
              A script is not a number. Aetrix reads the working, resolves it
              against the locked marking criteria, verifies what can be checked,
              and keeps the trail from the first line to the final mark.
            </p>
          </header>

          <div className="mk-transform__body">
            <div className="mk-transform__stage" aria-hidden="true">
              <span className="mk-transform__layer-label mono">Solution</span>
              <span className="mk-transform__layer-label mk-transform__layer-label--b mono">
                Criteria
              </span>
              <span className="mk-transform__layer-label mk-transform__layer-label--c mono">
                Evidence
              </span>

              <svg className="tr" viewBox="0 0 1040 620" fill="none" focusable="false">
                <g className="tr-grid">
                  {[0, 1, 2, 3, 4, 5].map((row) => (
                    <line key={row} x1="24" x2="1016" y1={70 + row * 100} y2={70 + row * 100} />
                  ))}
                  {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((column) => (
                    <line
                      key={column}
                      y1="40"
                      y2="580"
                      x1={24 + column * 110}
                      x2={24 + column * 110}
                    />
                  ))}
                </g>

                <g className="tr-sol-group">
                  <line className="tr-margin" x1="24" y1="96" x2="24" y2="360" />
                  {SOLUTION.map((line) => (
                    <g key={line.text}>
                      <text className="tr-sol-text" x="52" y={line.y}>
                        {line.text}
                      </text>
                      <path
                        className="tr-sol"
                        d={`M52 ${line.y + 10} C 150 ${line.y + 8}, 260 ${line.y + 13}, 372 ${line.y + 9}`}
                        strokeWidth="1.2"
                      />
                    </g>
                  ))}
                </g>

                <g className="tr-tree-group">
                  {SOLUTION.map((line) => (
                    <path
                      key={`m${line.y}`}
                      className="tr-tree"
                      d={`M372 ${line.y + 9} C 440 ${line.y + 9}, 452 300, 520 300`}
                      strokeWidth="1.2"
                    />
                  ))}

                  <path className="tr-tree tr-spine" d="M520 330V96" strokeWidth="1.6" />

                  {CRITERIA.map((criterion, index) => (
                    <g key={criterion.code}>
                      <path
                        className="tr-tree"
                        d={`M520 ${315 - index * 50} C 610 ${315 - index * 50}, 640 ${criterion.y}, 748 ${criterion.y}`}
                        strokeWidth="1.4"
                      />
                      <circle className="tr-node" cx="748" cy={criterion.y} r="4.6" />
                      <line
                        className="tr-tick"
                        x1="782"
                        y1={criterion.y}
                        x2="990"
                        y2={criterion.y}
                      />
                      <text className="tr-node-label" x="782" y={criterion.y - 11}>
                        <tspan className="tr-code">{criterion.code}</tspan>
                        {`  ${criterion.label}`}
                      </text>
                      <text
                        className="tr-node-mark"
                        x="990"
                        y={criterion.y - 11}
                        textAnchor="end"
                        data-empty={criterion.mark === '0/1' ? '' : undefined}
                      >
                        {criterion.mark}
                      </text>
                    </g>
                  ))}

                  <circle className="tr-tree tr-seal" cx="520" cy="72" r="22" />
                </g>

                <g className="tr-net-group">
                  {CRITERIA.map((criterion, index) => (
                    <path
                      key={`n${criterion.code}`}
                      className="tr-net"
                      d={`M748 ${criterion.y} C 840 ${criterion.y}, ${860 + index * 6} 420, 858 470`}
                      strokeWidth="1"
                    />
                  ))}
                  <path className="tr-net" d="M858 470H640" strokeWidth="1" />
                  <path className="tr-net" d="M858 470V540" strokeWidth="1" />

                  {CRITERIA.map((criterion, index) => (
                    <g key={`v${criterion.code}`} className="tr-verify">
                      <circle cx={700 + index * 40} cy="470" r="3" />
                      <path
                        className="tr-net"
                        d={`M858 470 L ${700 + index * 40} 470`}
                        strokeWidth="0.8"
                        strokeOpacity="0.4"
                      />
                    </g>
                  ))}

                  <g className="tr-result">
                    <rect x="640" y="500" width="350" height="92" />
                    <text className="tr-result-label" x="664" y="530">
                      14 / 16
                    </text>
                    <text className="tr-result-note" x="664" y="554">
                      5 criteria reconciled · 1 question needs review
                    </text>
                    <text className="tr-result-note" x="664" y="574">
                      engine aetrix_v5_5 · blueprint v3
                    </text>
                  </g>
                </g>

                <path
                  className="tr-route"
                  id="tr-route"
                  d="M52 326 C 300 326, 400 300, 520 300V96 C 520 58, 650 74, 748 130 C 830 182, 800 380, 858 470"
                  fill="none"
                  stroke="none"
                />
                <circle className="tr-signal" r="5" cx="52" cy="326" />
              </svg>
            </div>

            <ol className="mk-transform__caps">
              {STAGES.map((stage) => (
                <li className="mk-cap" key={stage.letter}>
                  <span className="mk-cap__letter mono">{stage.letter}</span>
                  <div>
                    <h3 className="mk-cap__title">{stage.title}</h3>
                    <p className="mk-cap__text">{stage.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <p className="mk-figcaption mono" data-reveal>
            Scrubbed diagram · illustrative values, not a real submission
          </p>
        </div>
      </div>
    </section>
  )
}
