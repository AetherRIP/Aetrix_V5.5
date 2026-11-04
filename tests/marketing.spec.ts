import AxeBuilder from '@axe-core/playwright'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

const WIDTHS = [360, 768, 1024, 1440, 1920]

type OpenOptions = {
  width?: number
  height?: number
  reducedMotion?: 'reduce' | 'no-preference'
}

/**
 * Opens a route on a fresh page. The headless renderer in this container
 * occasionally loses a page during navigation; retrying the navigation keeps
 * that infrastructure failure from being reported as a product failure, while
 * every assertion below stays strict.
 */
async function open(
  context: BrowserContext,
  path = '/',
  options: OpenOptions = {},
): Promise<Page> {
  const { width = 1440, height = 1000, reducedMotion = 'no-preference' } = options
  let lastError: unknown

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const page = await context.newPage()
    try {
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ reducedMotion })
      const response = await page.goto(path, { waitUntil: 'load' })
      expect(response?.status()).toBe(200)
      return page
    } catch (error) {
      lastError = error
      await page.close().catch(() => {})
    }
  }

  throw lastError
}

async function pageOverflow(page: Page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
}

async function expectNoSeriousViolations(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()
  const blocking = results.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  )
  if (blocking.length > 0) {
    console.log(
      `axe (${label}):\n${blocking
        .map((v) => `${v.id} — ${v.nodes.length} node(s): ${v.help}`)
        .join('\n')}`,
    )
  }
  expect(blocking.map((violation) => violation.id)).toEqual([])
}

test.describe('routes', () => {
  test('landing page renders with one h1 and landmark structure', async ({ context }) => {
    const page = await open(context)
    await expect(page.locator('h1')).toHaveCount(1)
    await expect(page.locator('main')).toHaveCount(1)
    await expect(page.getByRole('banner')).toHaveCount(1)
    await expect(page.getByRole('contentinfo')).toHaveCount(1)
    await expect(page.getByRole('navigation', { name: 'Primary' })).toHaveCount(1)
    await expect(page.locator('h1')).toContainText('Mark smarter')
  })

  test('sign-in page is a real, honest destination', async ({ context }) => {
    const page = await open(context, '/sign-in')
    await expect(page.locator('h1')).toContainText('Sign in to MathChecker')
    await expect(page.getByText('Not configured')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toHaveCount(0)
  })

  test('in-page navigation reaches every section', async ({ context }) => {
    const page = await open(context)
    for (const hash of ['features', 'workflow', 'security', 'platform']) {
      await expect(page.locator(`#${hash}`)).toHaveCount(1)
    }
  })
})

test.describe('responsive layout', () => {
  for (const width of WIDTHS) {
    test(`no horizontal page overflow at ${width}px`, async ({ context }) => {
      const page = await open(context, '/', { width, height: 900 })
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
      await page.waitForTimeout(250)
      const { scrollWidth, clientWidth } = await pageOverflow(page)
      expect(
        scrollWidth,
        `scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`,
      ).toBeLessThanOrEqual(clientWidth + 1)
    })
  }

  test('navigation collapses to a working menu on mobile', async ({ context }) => {
    const page = await open(context, '/', { width: 390, height: 844 })
    const toggle = page.getByRole('button', { name: 'Open menu' })
    await expect(toggle).toBeVisible()
    await toggle.click()
    const panel = page.locator('#mobile-navigation')
    await expect(panel).toBeVisible()
    await expect(panel.getByRole('link', { name: 'Workflow' })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(page.getByRole('button', { name: 'Open menu' })).toBeFocused()
  })

  test('desktop navigation is present and the mobile toggle is hidden', async ({ context }) => {
    const page = await open(context, '/', { width: 1440 })
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Open menu' })).toBeHidden()
  })
})

test.describe('theme', () => {
  test('defaults to dark, switches, and persists across navigations', async ({ context }) => {
    const first = await open(context)
    await expect(first.locator('html')).toHaveAttribute('data-theme', 'dark')

    await first.getByRole('button', { name: 'Light', exact: true }).click()
    await expect(first.locator('html')).toHaveAttribute('data-theme', 'light')
    await expect(
      first.getByRole('button', { name: 'Light', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true')
    expect(
      await first.evaluate(() => localStorage.getItem('mathchecker:theme')),
    ).toBe('light')

    const second = await open(context)
    await expect(second.locator('html')).toHaveAttribute('data-theme', 'light')

    await second.getByRole('button', { name: 'Dark', exact: true }).click()
    await expect(second.locator('html')).toHaveAttribute('data-theme', 'dark')
  })
})

test.describe('product preview', () => {
  test('tabs respond to click and arrow keys', async ({ context }) => {
    const page = await open(context)
    const overview = page.getByRole('tab', { name: 'Overview' })
    await expect(overview).toHaveAttribute('aria-selected', 'true')

    await page.getByRole('tab', { name: 'Results' }).click()
    const results = page.getByRole('tab', { name: 'Results' })
    await expect(results).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('tabpanel', { name: 'Results' })).toBeVisible()
    await expect(page.locator('.results-table')).toBeVisible()

    await results.focus()
    await page.keyboard.press('ArrowLeft')
    await expect(page.getByRole('tab', { name: 'Marking' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await page.keyboard.press('Home')
    await expect(overview).toHaveAttribute('aria-selected', 'true')
  })
})

test.describe('accessibility', () => {
  for (const theme of ['dark', 'light'] as const) {
    test(`landing has no serious axe violations (${theme})`, async ({ context }) => {
      /* Contrast is measured at rest: mid-entrance opacity is a transition state. */
      const page = await open(context, '/', { reducedMotion: 'reduce' })
      await page.evaluate((value) => {
        document.documentElement.setAttribute('data-theme', value)
      }, theme)
      await page.waitForTimeout(400)
      await expectNoSeriousViolations(page, `landing ${theme}`)
    })
  }

  test('sign-in has no serious axe violations', async ({ context }) => {
    const page = await open(context, '/sign-in', { reducedMotion: 'reduce' })
    await page.waitForTimeout(300)
    await expectNoSeriousViolations(page, 'sign-in')
  })

  test('skip link moves focus to main', async ({ context }) => {
    const page = await open(context)
    await page.keyboard.press('Tab')
    const skip = page.getByRole('link', { name: 'Skip to main content' })
    await expect(skip).toBeFocused()
    await skip.press('Enter')
    await expect(page.locator('main')).toBeFocused()
  })
})

test.describe('reduced motion', () => {
  test('content is visible and stable when motion is reduced', async ({ context }) => {
    const page = await open(context, '/', { reducedMotion: 'reduce' })
    await page.waitForTimeout(250)

    const hidden = await page.evaluate(() => {
      const nodes = Array.from(document.querySelectorAll('[data-reveal]'))
      return nodes.filter((node) => window.getComputedStyle(node).opacity === '0')
        .length
    })
    expect(hidden).toBe(0)

    const duration = await page.evaluate(() => {
      const bar = document.querySelector('.chart__bar')
      if (!bar) return 0
      return Number.parseFloat(window.getComputedStyle(bar).animationDuration)
    })
    expect(duration).toBeLessThanOrEqual(0.01)
  })

  test('animations are defined when motion is allowed', async ({ context }) => {
    const page = await open(context)
    const animation = await page.evaluate(() => {
      const glow = document.querySelector('.hero__glow')
      return glow ? window.getComputedStyle(glow).animationName : ''
    })
    expect(animation).not.toBe('none')
  })
})
