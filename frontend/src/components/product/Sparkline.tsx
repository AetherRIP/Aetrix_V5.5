/** A small trend line. `pathLength` gives the draw-in animation a stable length. */
export function Sparkline({
  points,
  label,
}: {
  points: number[]
  label: string
}) {
  const max = Math.max(...points)
  const min = Math.min(...points)
  const span = max - min || 1
  const path = points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 100
      const y = 28 - ((point - min) / span) * 24
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg
      className="spark"
      viewBox="0 0 100 32"
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      <path
        d={path}
        pathLength={1}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        vectorEffect="non-scaling-stroke"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
