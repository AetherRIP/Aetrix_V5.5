export function Brand({ size = 28 }: { size?: number }) {
  return (
    <span className="brand">
      <svg
        className="brand__monogram"
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <rect
          x="1.5"
          y="1.5"
          width="29"
          height="29"
          rx="1.5"
          stroke="currentColor"
          strokeOpacity="0.55"
        />
        <path d="M10.5 1.5v29" stroke="currentColor" strokeOpacity="0.4" />
        <path d="M5 9.5h2.5M5 16h2.5M5 22.5h2.5" stroke="currentColor" strokeOpacity="0.55" />
        <path
          d="m14.5 16.8 3.4 3.4 6.1-8"
          stroke="currentColor"
          strokeWidth="1.9"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="brand__name">
        <span className="brand__name-strong">Aetrix</span>
      </span>
      <span className="brand__version mono">V5.5</span>
    </span>
  )
}
