export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' }).format(date)
}

/** Provider ids arrive as e.g. `google`; render something readable. */
export function providerLabel(provider: string | undefined): string {
  if (!provider) return 'Unknown'
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}
