/**
 * Six chapter scenes, drawn as original SVG.
 *
 * Each scene shares one language: a 600×640 drafting frame, hairline geometry,
 * emerald reserved for verified or actionable elements and amber for attention.
 * Every animated stroke carries `.sc-path` (dash-drawn), every element that
 * appears carries `.sc-pop`, and every connector carries `.sc-link`, so the
 * motion controller can choreograph any chapter without knowing what it depicts.
 */

const FRAME = { width: 600, height: 640 } as const

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <svg
      className="sc"
      viewBox={`0 0 ${FRAME.width} ${FRAME.height}`}
      fill="none"
      focusable="false"
      aria-hidden="true"
    >
      <g className="sc-grid">
        {[0, 1, 2, 3, 4, 5].map((row) => (
          <line key={row} x1="0" x2="600" y1={70 + row * 100} y2={70 + row * 100} />
        ))}
        {[0, 1, 2, 3, 4, 5].map((column) => (
          <line key={column} y1="30" y2="610" x1={40 + column * 104} x2={40 + column * 104} />
        ))}
      </g>
      {children}
    </svg>
  )
}

/** 01 — CAPTURE: pages arrive, unfold and are scanned. */
export function CaptureScene() {
  return (
    <Frame>
      {[0, 1, 2].map((index) => (
        <g key={index} className="sc-pop" data-order={index}>
          <rect
            className="sc-plate"
            x={150 + index * 26}
            y={132 + index * 24}
            width="272"
            height="348"
            rx="2"
          />
          <path
            className="sc-faint"
            d={`M178 ${170 + index * 24}h216M178 ${196 + index * 24}h140M178 ${222 + index * 24}h184`}
          />
        </g>
      ))}

      <path className="sc-path sc-path--accent" d="M112 118h-18v420h18" strokeWidth="1.2" />
      <path className="sc-path" d="M486 118h18v420h-18" strokeWidth="1.2" />

      <path className="sc-path sc-scan" d="M120 300h360" strokeWidth="1.4" />
      <g className="sc-pop" data-order="3">
        <rect className="sc-badge" x="120" y="516" width="150" height="30" rx="1" />
        <text className="sc-label" x="136" y="536">
          48 pages · validated
        </text>
      </g>
      <text className="sc-label sc-label--faint" x="120" y="574">
        class set / homework 6
      </text>
    </Frame>
  )
}

/** 02 — UNDERSTAND: the sheet becomes a question list. */
export function UnderstandScene() {
  return (
    <Frame>
      <g className="sc-pop" data-order="0">
        <rect className="sc-plate" x="56" y="110" width="240" height="330" rx="2" />
        <path className="sc-faint" d="M84 150h180M84 176h120M84 202h150M84 228h96" />
        <path className="sc-faint" d="M84 276h180M84 302h140M84 328h166" />
      </g>

      {[
        { y: 132, label: 'Q1', dash: 'M320 132h210' },
        { y: 258, label: 'Q2', dash: 'M320 258h210' },
        { y: 372, label: 'Q3', dash: 'M320 372h210' },
      ].map((box, index) => (
        <g key={box.label} className="sc-pop" data-order={index + 1}>
          <path className="sc-link" d={box.dash} strokeDasharray="3 5" />
          <rect className="sc-box" x="330" y={box.y - 18} width="190" height="34" rx="1" />
          <text className="sc-label" x="344" y={box.y + 4}>
            {box.label} · extracted
          </text>
          <text className="sc-label sc-label--faint" x="470" y={box.y + 4}>
            2 marks
          </text>
        </g>
      ))}

      <path className="sc-path sc-path--accent" d="M300 110v330" strokeWidth="1" />
      <path className="sc-path" d="M296 270h8M296 394h8" />
      <g className="sc-pop" data-order="4">
        <rect className="sc-badge" x="330" y="452" width="190" height="30" rx="1" />
        <text className="sc-label" x="344" y="472">
          blueprint draft · not yet approved
        </text>
      </g>
      <text className="sc-label sc-label--faint" x="330" y="512">
        a teacher approves this structure
      </text>
    </Frame>
  )
}

/** 03 — ASSESS: working connects to criteria and marks land. */
export function AssessScene() {
  const rows = [
    { y: 170, expr: '8x − 12 = 5x + 9', code: 'M1', mark: '1' },
    { y: 246, expr: '3x = 21', code: 'A1', mark: '1' },
    { y: 322, expr: 'x = 7', code: 'B1', mark: '1' },
    { y: 398, expr: 'check both sides', code: 'C1', mark: '0' },
  ]
  return (
    <Frame>
      {rows.map((row, index) => (
        <g key={row.code}>
          <g className="sc-pop" data-order={index}>
            <rect className="sc-plate sc-plate--row" x="56" y={row.y - 26} width="250" height="52" rx="1" />
            <text className="sc-mono" x="72" y={row.y + 4}>
              {row.expr}
            </text>
          </g>
          <path
            className="sc-path sc-path--link"
            d={`M306 ${row.y} C 360 ${row.y}, 380 ${row.y}, 424 ${row.y}`}
            strokeWidth="1"
          />
          <g className="sc-pop" data-order={index + 1}>
            <rect className="sc-box" x="424" y={row.y - 20} width="120" height="40" rx="1" />
            <text className="sc-label" x="440" y={row.y - 2}>
              {row.code}
            </text>
            <text className="sc-mono sc-mono--faint" x="440" y={row.y + 14}>
              {row.mark === '1' ? 'awarded 1' : 'not shown'}
            </text>
            <circle
              className={row.mark === '1' ? 'sc-dot' : 'sc-dot sc-dot--warn'}
              cx="528"
              cy={row.y}
              r="4"
            />
          </g>
        </g>
      ))}

      <path className="sc-path sc-path--accent" d="M56 120h488" strokeWidth="1" />
      <g className="sc-pop" data-order="4">
        <rect className="sc-badge" x="56" y="466" width="238" height="30" rx="1" />
        <text className="sc-label" x="72" y="486">
          every mark names its criterion
        </text>
      </g>
      <text className="sc-label sc-label--faint" x="56" y="524">
        provisional · awaiting review
      </text>
    </Frame>
  )
}

/** 04 — VERIFY: the mathematics is checked where it can be. */
export function VerifyScene() {
  return (
    <Frame>
      <circle className="sc-path sc-ring" cx="300" cy="270" r="118" strokeWidth="1.2" />
      <circle className="sc-path sc-ring sc-ring--inner" cx="300" cy="270" r="88" strokeWidth="0.8" />
      <path className="sc-path sc-path--accent" d="m252 272 32 32 66-74" strokeWidth="2.4" />

      {[
        { angle: -90, label: 'substitution' },
        { angle: -18, label: 'identity' },
        { angle: 54, label: 'domain' },
        { angle: 126, label: 'sign' },
        { angle: 198, label: 'units' },
      ].map((node, index) => {
        const radius = 118
        const radians = (node.angle * Math.PI) / 180
        const x = 300 + Math.cos(radians) * radius
        const y = 270 + Math.sin(radians) * radius
        return (
          <g key={node.label} className="sc-pop" data-order={index}>
            <circle className="sc-dot" cx={x} cy={y} r="3.4" />
            <text
              className="sc-label sc-label--faint"
              x={300 + Math.cos(radians) * (radius + 22)}
              y={270 + Math.sin(radians) * (radius + 26)}
              textAnchor="middle"
            >
              {node.label}
            </text>
          </g>
        )
      })}

      <path className="sc-path" d="M300 388v52" strokeWidth="1" />
      <g className="sc-pop" data-order="5">
        <rect className="sc-badge sc-badge--warn" x="186" y="448" width="228" height="30" rx="1" />
        <text className="sc-label" x="202" y="468">
          one step did not verify → review
        </text>
      </g>
      <text className="sc-label sc-label--faint" x="186" y="508">
        verification is not assumed
      </text>
    </Frame>
  )
}

/** 05 — REVIEW: uncertainty is separated for a person. */
export function ReviewScene() {
  return (
    <Frame>
      <path className="sc-path" d="M300 96v96" strokeWidth="1" />
      <g className="sc-pop" data-order="0">
        <rect className="sc-plate" x="196" y="192" width="208" height="86" rx="2" />
        <text className="sc-label" x="216" y="222">question 4</text>
        <text className="sc-mono sc-mono--faint" x="216" y="248">two methods match</text>
        <circle className="sc-dot sc-dot--warn" cx="384" cy="212" r="4" />
      </g>

      {[
        { x: 116, label: 'method A' },
        { x: 300, label: 'method B' },
        { x: 484, label: 'needs review' },
      ].map((branch, index) => (
        <g key={branch.label}>
          <path
            className="sc-path sc-path--link"
            d={`M300 278 C 300 330, ${branch.x} 330, ${branch.x} 366`}
            strokeWidth="1"
          />
          <g className="sc-pop" data-order={index + 1}>
            <rect
              className={branch.label === 'needs review' ? 'sc-box sc-box--warn' : 'sc-box'}
              x={branch.x - 62}
              y="366"
              width="124"
              height="42"
              rx="1"
            />
            <text className="sc-label" x={branch.x} y="392" textAnchor="middle">
              {branch.label}
            </text>
          </g>
        </g>
      ))}

      <path className="sc-path sc-path--accent" d="M484 408v54" strokeWidth="1" />
      <g className="sc-pop" data-order="4">
        <rect className="sc-badge" x="386" y="462" width="196" height="30" rx="1" />
        <text className="sc-label" x="402" y="482">a person decides</text>
      </g>
      <text className="sc-label sc-label--faint" x="88" y="516">
        never a silent zero
      </text>
      <text className="sc-label sc-label--faint" x="88" y="546">
        the original mark stays beside the change
      </text>
    </Frame>
  )
}

/** 06 — REPORT: the evidence resolves into a readable result. */
export function ReportScene() {
  return (
    <Frame>
      <g className="sc-pop" data-order="0">
        <rect className="sc-plate" x="56" y="104" width="488" height="392" rx="2" />
        <path className="sc-path sc-divider" d="M56 168h488" strokeWidth="1" />
        <text className="sc-label" x="76" y="142">correction report · 10B set 2</text>
        <text className="sc-mono sc-mono--faint" x="452" y="142">approved</text>
      </g>

      {[0, 1, 2, 3, 4].map((row) => (
        <g key={row} className="sc-pop" data-order={row + 1}>
          <path className="sc-divider" d={`M56 ${214 + row * 52}h488`} strokeWidth="0.8" />
          <text className="sc-mono sc-mono--faint" x="76" y={200 + row * 52}>
            {`Q${row + 1}`}
          </text>
          <rect
            className="sc-bar"
            x="120"
            y={190 + row * 52}
            width={[136, 92, 158, 74, 120][row]}
            height="8"
          />
          <text className="sc-mono sc-mono--faint" x="300" y={200 + row * 52}>
            {[4, 3, 5, 2, 3][row]} / {[5, 3, 6, 3, 3][row]}
          </text>
        </g>
      ))}

      <g className="sc-pop" data-order="7">
        <text className="sc-total" x="392" y="452">14 / 20</text>
        <text className="sc-label sc-label--faint" x="394" y="474">recomputed from questions</text>
      </g>

      <path className="sc-path sc-path--accent" d="M56 540h488" strokeWidth="1" />
      <g className="sc-pop" data-order="8">
        <text className="sc-label" x="56" y="572">distribution, approved marks only</text>
      </g>
    </Frame>
  )
}
