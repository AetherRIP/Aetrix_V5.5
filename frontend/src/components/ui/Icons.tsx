import type { ReactNode } from 'react'

export type IconName =
  | 'arrow'
  | 'check'
  | 'checkDouble'
  | 'triangle'
  | 'dot'
  | 'half'
  | 'pen'
  | 'sparkle'
  | 'blueprint'
  | 'review'
  | 'assignment'
  | 'records'
  | 'pulse'
  | 'chart'
  | 'classroom'
  | 'shield'
  | 'server'
  | 'lock'
  | 'eye'
  | 'menu'
  | 'close'
  | 'moon'
  | 'sun'

const PATHS: Record<IconName, ReactNode> = {
  arrow: <path d="M4 12h15m-6-6 6 6-6 6" />,
  check: <path d="m4.5 12.5 5 5L20 6.5" />,
  checkDouble: <path d="m2 12.5 4 4 8-8m-6 8 4 4 8-8" />,
  triangle: <path d="M12 3.5 21.5 20.5H2.5L12 3.5Z" />,
  dot: <circle cx="12" cy="12" r="6.5" />,
  half: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5v17a8.5 8.5 0 0 0 0-17Z" fill="currentColor" stroke="none" />
    </>
  ),
  pen: <path d="M15.5 4.5 19.5 8.5 8 20H4v-4L15.5 4.5Z" />,
  sparkle: (
    <>
      <path d="M12 3v5m0 8v5M3 12h5m8 0h5" />
      <path d="m6.4 6.4 2.1 2.1m7 7 2.1 2.1m0-11.2-2.1 2.1m-7 7-2.1 2.1" />
    </>
  ),
  blueprint: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="1" />
      <path d="M3 9h18M9 9v11M15 9v11" />
    </>
  ),
  review: (
    <>
      <path d="M12 3.5 21.5 20.5H2.5L12 3.5Z" />
      <path d="M12 9.5v5m0 2.4v.1" />
    </>
  ),
  assignment: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="1" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </>
  ),
  records: (
    <>
      <circle cx="9" cy="8.5" r="3.5" />
      <path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
      <path d="M16.5 5.6a3.5 3.5 0 0 1 0 6.8M18 14.4c2.1.7 3.5 2.6 3.5 5.1" />
    </>
  ),
  pulse: <path d="M2 12h4l2.5-6.5L13 19l2.5-7H22" />,
  chart: (
    <>
      <path d="M3 20.5V3.5" />
      <path d="M3 20.5h18" />
      <path d="M7 17v-5M11.5 17V7.5M16 17v-3M20 17V5" />
    </>
  ),
  classroom: (
    <>
      <path d="M2.5 8.5 12 4l9.5 4.5L12 13 2.5 8.5Z" />
      <path d="M6 10.8v5.4c0 1.7 2.7 3.3 6 3.3s6-1.6 6-3.3v-5.4" />
    </>
  ),
  shield: (
    <>
      <path d="M12 2.8 20 6v6c0 4.6-3.3 8.2-8 9.2-4.7-1-8-4.6-8-9.2V6l8-3.2Z" />
      <path d="m8.8 12.2 2.2 2.2 4.2-4.4" />
    </>
  ),
  server: (
    <>
      <rect x="3" y="4" width="18" height="6.5" rx="1" />
      <rect x="3" y="13.5" width="18" height="6.5" rx="1" />
      <path d="M7 7.2h.01M7 16.8h.01" />
    </>
  ),
  lock: (
    <>
      <rect x="4.5" y="10" width="15" height="10.5" rx="1" />
      <path d="M8 10V7.5a4 4 0 0 1 8 0V10" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  menu: <path d="M3.5 7h17M3.5 12h17M3.5 17h17" />,
  close: <path d="m5.5 5.5 13 13m0-13-13 13" />,
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2m0 15v2M2.5 12h2m15 0h2M5.2 5.2l1.4 1.4m10.8 10.8 1.4 1.4m0-13.6-1.4 1.4M6.6 17.4l-1.4 1.4" />
    </>
  ),
}

export function Icon({
  name,
  size = 20,
  className,
  strokeWidth = 1.5,
}: {
  name: IconName
  size?: number
  className?: string
  strokeWidth?: number
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {PATHS[name]}
    </svg>
  )
}
