import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * The legal pages are public documents. They must load without a session, carry
 * one heading, state their version, and cross-link so a reader can move between
 * them the way a compliance reviewer expects.
 */
const ROUTES = [
  ['/legal', 'The documents behind the pilot.'],
  ['/terms', 'The rules for using the Aetrix pilot.'],
  ['/privacy', 'What Aetrix does with your information.'],
  ['/cookies', 'No cookies. Here is exactly what the browser stores.'],
  ['/acceptable-use', 'What you must not do with Aetrix.'],
  ['/ai-disclosure', 'What the AI does, and what it cannot be trusted to do.'],
  ['/copyright', 'Who owns what, and how to report infringement.'],
  ['/security', 'What protects the data, and what does not yet.'],
  ['/account-deletion', 'Asking for your data, a correction, or deletion.'],
] as const

const DOCUMENT_PATHS = [
  '/terms',
  '/privacy',
  '/cookies',
  '/acceptable-use',
  '/ai-disclosure',
  '/copyright',
  '/security',
  '/account-deletion',
] as const

test.describe('legal documents', () => {
  for (const [path, heading] of ROUTES) {
    test(`${path} is public, readable and versioned`, async ({ page }) => {
      const response = await page.goto(path)
      expect(response?.status()).toBe(200)

      // One page heading, the marketing landmarks, and no session gate.
      await expect(page.locator('h1')).toHaveCount(1)
      await expect(page.locator('h1')).toHaveText(heading)
      await expect(page.getByRole('main')).toHaveCount(1)
      await expect(page.getByRole('banner')).toHaveCount(1)
      await expect(page.getByRole('contentinfo')).toHaveCount(1)
      expect(new URL(page.url()).pathname.replace(/\/$/, '')).toBe(path)

      // The draft status, the version and the last-updated date are visible.
      await expect(
        page.getByText('Pre-release pilot · pending legal review').first(),
      ).toBeVisible()
      await expect(page.getByText('2026-11-13').first()).toBeVisible()
      await expect(page.locator('time').first()).toHaveAttribute('datetime', '2026-11-13')
    })
  }

  test('the legal centre links every document', async ({ page }) => {
    await page.goto('/legal')
    for (const path of DOCUMENT_PATHS) {
      await expect(page.locator(`a[href="${path}"]`).first()).toBeVisible()
    }
  })

  test('policies cross-link to each other and back to the site', async ({ page }) => {
    await page.goto('/privacy')
    await expect(page.locator('a[href="/cookies"]').first()).toBeVisible()
    await expect(page.locator('a[href="/terms"]').first()).toBeVisible()
    await expect(page.locator('a[href="/ai-disclosure"]').first()).toBeVisible()

    // The sidebar links every other document and the legal centre.
    const sidebar = page.getByRole('navigation', { name: 'On this page' })
    await expect(sidebar.getByRole('link', { name: 'Legal centre' })).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'Cookie Policy' })).toBeVisible()
  })

  test('no legal page overflows a phone viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    for (const [path] of ROUTES) {
      await page.goto(path)
      const { scrollWidth, clientWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }))
      expect(scrollWidth, `${path} overflows at 390px`).toBeLessThanOrEqual(
        clientWidth + 1,
      )
    }
  })

  test('no legal page has a serious axe violation', async ({ page }) => {
    for (const [path] of ROUTES) {
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.goto(path)
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze()
      const blocking = results.violations.filter(
        (violation) => violation.impact === 'serious' || violation.impact === 'critical',
      )
      expect(
        blocking.map((violation) => `${path} ${violation.id}: ${violation.help}`),
      ).toEqual([])
    }
  })

  test('the footer exposes the legal documents on a public page', async ({ page }) => {
    await page.goto('/')
    const footer = page.getByRole('contentinfo')
    for (const name of [
      'Terms of Service',
      'Privacy Policy',
      'Cookie Policy',
      'AI Use Disclosure',
      'Acceptable Use',
      'All legal documents',
    ]) {
      await expect(footer.getByRole('link', { name, exact: true })).toBeVisible()
    }
  })
})

test.describe('sign-in acknowledgement', () => {
  test('is unchecked by default and blocks a provider request until accepted', async ({
    page,
  }) => {
    await page.goto('/sign-in')

    const acknowledgement = page.getByRole('checkbox', { name: /I have read and agree/i })
    await expect(acknowledgement).toBeVisible()
    await expect(acknowledgement).not.toBeChecked()

    let authorizeRequests = 0
    await page.route('**/auth/v1/authorize**', async (route) => {
      authorizeRequests += 1
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<!doctype html><title>provider stub</title><p>provider stub</p>',
      })
    })

    await page.getByRole('button', { name: 'Continue with Google' }).click()
    await expect(
      page.getByRole('alert').filter({ hasText: /accept the Terms of Service/i }),
    ).toBeVisible()
    expect(authorizeRequests).toBe(0)

    await acknowledgement.check()
    await page.getByRole('button', { name: 'Continue with Google' }).click()
    await expect.poll(() => authorizeRequests, { timeout: 15_000 }).toBeGreaterThan(0)
  })

  test('does not claim to record acceptance on the server', async ({ page }) => {
    await page.goto('/sign-in')
    await expect(page.locator('.legal-ack')).toContainText(
      'does not yet record your acceptance',
    )
    await expect(page.locator('.legal-ack')).toContainText(
      'sets no advertising or analytics cookies',
    )
  })
})
