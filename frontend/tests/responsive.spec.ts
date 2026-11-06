import { expect, test, type BrowserContext, type Page } from '@playwright/test'

/**
 * Device matrix: every application page is loaded at phone, tablet, laptop and
 * wide-desktop widths, against a real server. For each combination this checks
 * that the document answers, that the expected screen is on display, that the
 * layout does not overflow horizontally and that nothing logged an error.
 *
 * Protected routes cannot render their signed-in content without a session, so
 * the expectation for them is the protected-route behaviour: a clean redirect to
 * the sign-in page with no application chrome. That is still a page load on
 * every device, which is what this suite is for.
 */

const DEVICES = [
  { name: 'phone-375', width: 375, height: 667, scale: 2 },
  { name: 'phone-390', width: 390, height: 844, scale: 2 },
  { name: 'phablet-412', width: 412, height: 915, scale: 2 },
  { name: 'tablet-768', width: 768, height: 1024, scale: 1 },
  { name: 'tablet-landscape-1024', width: 1024, height: 768, scale: 1 },
  { name: 'laptop-1440', width: 1440, height: 900, scale: 1 },
  { name: 'wide-1920', width: 1920, height: 1080, scale: 1 },
] as const

const PROTECTED = [
  '/dashboard',
  '/workspace',
  '/inbox',
  '/queue',
  '/assignments',
  '/assignments/example',
  '/submissions/example',
  '/reports',
  '/settings',
]

type Expectation = { path: string; heading: RegExp }

const ROUTES: Expectation[] = [
  { path: '/', heading: /Mark smarter/i },
  { path: '/sign-in', heading: /Sign in to Aetrix/i },
  { path: '/auth/callback', heading: /Sign-in did not complete|Completing sign-in/i },
  ...PROTECTED.map((path) => ({ path, heading: /Sign in to Aetrix/i })),
]

async function load(context: BrowserContext, path: string, device: (typeof DEVICES)[number]) {
  const page = await context.newPage()
  await page.setViewportSize({ width: device.width, height: device.height })
  const problems: string[] = []
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console: ${message.text()}`)
  })

  const response = await page.goto(path, { waitUntil: 'load' })
  // Bounded settle: a remote origin can keep a connection open long enough that
  // the default 30s idle wait would dominate the run.
  await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {})

  return { page, response, problems }
}

async function layoutReport(page: Page) {
  return page.evaluate(() => {
    const documentElement = document.documentElement
    const main = document.querySelector('main')
    const mainBox = main?.getBoundingClientRect()
    return {
      scrollWidth: documentElement.scrollWidth,
      clientWidth: documentElement.clientWidth,
      mainCount: document.querySelectorAll('main').length,
      mainWidth: mainBox?.width ?? 0,
      title: document.title,
    }
  })
}

for (const device of DEVICES) {
  test.describe(`${device.name} (${device.width}×${device.height})`, () => {
    for (const route of ROUTES) {
      test(`${route.path} loads cleanly`, async ({ context }) => {
        const { page, response, problems } = await load(context, route.path, device)
        try {
          expect(response?.status(), `${route.path} status`).toBe(200)

          await expect(page.getByRole('heading', { name: route.heading })).toBeVisible({
            timeout: 20_000,
          })

          const layout = await layoutReport(page)
          expect(layout.title).not.toBe('')
          expect(layout.mainCount, `${route.path} has exactly one main landmark`).toBe(1)
          expect(layout.mainWidth, `${route.path} main is laid out`).toBeGreaterThan(0)
          expect(
            layout.scrollWidth,
            `${route.path} must not overflow horizontally at ${device.width}px`,
          ).toBeLessThanOrEqual(layout.clientWidth + 1)

          expect(problems, `${route.path} logged errors`).toEqual([])
        } finally {
          await page.close()
        }
      })
    }

    test('marketing navigation suits the viewport', async ({ context }) => {
      const { page } = await load(context, '/', device)
      try {
        const menuToggle = page.getByRole('button', { name: /menu/i }).first()
        if (device.width < 900) {
          await expect(menuToggle).toBeVisible()
        } else {
          await expect(menuToggle).toBeHidden()
          await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
        }
      } finally {
        await page.close()
      }
    })
  })
}
