import { useTheme, type Theme } from '../../lib/theme'

const OPTIONS: { value: Theme; label: string }[] = [
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
]

/**
 * Two explicit options rather than one ambiguous toggle: the control announces
 * the available themes, and the pressed state reports which one is applied.
 */
export function ThemeSwitch() {
  const { theme, setTheme } = useTheme()

  return (
    <div className="theme-switch" data-active={theme} role="group" aria-label="Colour theme">
      <span className="theme-switch__thumb" aria-hidden="true" />
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={theme === option.value}
          onClick={() => setTheme(option.value)}
          className="theme-switch__option"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
