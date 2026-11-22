/**
 * The hero figure: a reasoning lattice.
 *
 * Five lines of a student's working converge on a spine; the spine branches
 * into five marking criteria, and a single signal travels the whole route from
 * working to criterion. It is a diagram of how Aetrix reads a script, drawn in
 * Aetrix's own visual language rather than a decorative flourish, and it is
 * aria-hidden: the hero copy carries the meaning.
 */
export function Lattice() {
  return (
    <div className="lt">
      <svg
        className="lt__svg"
        viewBox="0 0 600 640"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          {/* userSpaceOnUse: an objectBoundingBox gradient on a flat or upright
              path has a degenerate bounding box, and the stroke is not painted. */}
          <linearGradient
            id="lt-stroke"
            gradientUnits="userSpaceOnUse"
            x1="28"
            y1="612"
            x2="540"
            y2="44"
          >
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.16" />
            <stop offset="52%" stopColor="currentColor" stopOpacity="0.5" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0.9" />
          </linearGradient>
        </defs>

        {/* The drafting datum behind the figure. */}
        <g className="lt-grid">
          {[0, 1, 2, 3, 4].map((row) => (
            <line key={`r${row}`} x1="16" x2="544" y1={80 + row * 120} y2={80 + row * 120} />
          ))}
          {[0, 1, 2, 3, 4, 5].map((column) => (
            <line
              key={`c${column}`}
              y1="40"
              y2="600"
              x1={16 + column * 105}
              x2={16 + column * 105}
            />
          ))}
        </g>

        {/* The working: five lines, each one a path so it can be drawn. */}
        <g className="lt-source">
          {[432, 462, 492, 522, 552].map((y, index) => (
            <path
              key={y}
              className="lt-path"
              d={`M28 ${y} C 70 ${y - 7}, 108 ${y + 7}, 148 ${y}`}
              strokeWidth={index === 4 ? 2.4 : 1.4}
            />
          ))}
          <path className="lt-path lt-path--faint" d="M28 402h96" strokeWidth="1" />
          <path className="lt-path lt-path--faint" d="M28 585h64" strokeWidth="1" />
        </g>

        {/* Every line is carried into the spine. */}
        <g className="lt-merge">
          <path className="lt-path" d="M148 432C 232 432, 232 492, 300 492" />
          <path className="lt-path" d="M148 462C 226 462, 240 492, 300 492" />
          <path className="lt-path" d="M148 492H300" />
          <path className="lt-path" d="M148 522C 226 522, 240 492, 300 492" />
          <path className="lt-path" d="M148 552C 232 552, 232 492, 300 492" />
        </g>

        {/* The spine, and the criteria it resolves into. */}
        <path className="lt-path lt-spine" d="M300 492V132" />

        {[
          { y: 444, to: 430, label: 'M1 · method', mark: '1/1' },
          { y: 372, to: 350, label: 'A1 · accuracy', mark: '2/2' },
          { y: 300, to: 270, label: 'B1 · reasoning', mark: '1/1' },
          { y: 228, to: 190, label: 'C1 · verification', mark: '1/1' },
          { y: 156, to: 110, label: 'D1 · conclusion', mark: '2/2' },
        ].map((branch) => (
          <g key={branch.label}>
            <path
              className="lt-path lt-branch"
              d={`M300 ${branch.y} C 372 ${branch.y}, 396 ${branch.to}, 464 ${branch.to}`}
            />
            <circle className="lt-node" cx="464" cy={branch.to} r="3.6" />
            <text className="lt-label" x="480" y={branch.to - 4}>
              {branch.label}
            </text>
            <text className="lt-mark" x="480" y={branch.to + 12}>
              {branch.mark}
            </text>
          </g>
        ))}

        {/* The verification seal closes the spine. */}
        <circle className="lt-path lt-ring" cx="300" cy="104" r="26" />
        <path className="lt-path" d="m288 104 8 8 16-17" strokeWidth="2" />

        {/* One signal on one route: working → criteria → verification. */}
        <path
          className="lt-route"
          id="lt-route"
          d="M148 492H300V132C 330 90, 380 84, 464 110"
          fill="none"
          stroke="none"
        />
        <circle className="lt-signal" r="4.4" cx="0" cy="0" />

        <g className="lt-foot">
          <line className="lt-path" x1="28" y1="612" x2="532" y2="612" />
        </g>
      </svg>

      <div className="lt__caption">
        <span className="mono">Working</span>
        <span className="lt__caption-rule" aria-hidden="true" />
        <span className="mono">Criteria</span>
        <span className="lt__caption-rule" aria-hidden="true" />
        <span className="mono">Evidence</span>
      </div>
    </div>
  )
}
