import { expect, test, type Page } from '@playwright/test'
import { stubLegalAcceptance } from './support/legal-acceptance'

/**
 * Every authenticated destination at the three review widths.
 *
 * The older responsive suite loads protected paths as an anonymous visitor, so
 * it only proves the sign-in redirect. This suite opens the real role shell and
 * checks the screen the account actually reaches. `/me` is answered with an
 * explicit unavailable response so the app renders its honest states without a
 * remote engine and without depending on network timing.
 */

const EMAIL = {
  supervisor: 'teacher@aetrix.test',
  assistant: 'ana@aetrix.test',
  platform_operator: 'operator@aetrix.test',
}

type AuditRole = keyof typeof EMAIL

const WIDTHS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
] as const

const ROUTES: { role: AuditRole; path: string }[] = [
  { role: 'supervisor', path: '/dashboard' },
  { role: 'supervisor', path: '/workspace' },
  { role: 'supervisor', path: '/inbox' },
  { role: 'supervisor', path: '/notifications' },
  { role: 'supervisor', path: '/history' },
  { role: 'supervisor', path: '/queue' },
  { role: 'supervisor', path: '/assignments' },
  { role: 'supervisor', path: '/assignments/example' },
  { role: 'supervisor', path: '/submissions/example' },
  { role: 'supervisor', path: '/reports' },
  { role: 'supervisor', path: '/settings' },
  { role: 'supervisor', path: '/students' },
  { role: 'supervisor', path: '/gradebook' },
  { role: 'supervisor', path: '/analytics' },
  { role: 'supervisor', path: '/assistants' },
  { role: 'supervisor', path: '/classroom' },
  { role: 'assistant', path: '/assistant' },
  { role: 'assistant', path: '/assistant/classes' },
  { role: 'assistant', path: '/assistant/work' },
  { role: 'assistant', path: '/assistant/tasks' },
  { role: 'assistant', path: '/assistant/progress' },
  { role: 'assistant', path: '/queue' },
  { role: 'assistant', path: '/reports' },
  { role: 'assistant', path: '/inbox' },
  { role: 'assistant', path: '/notifications' },
  { role: 'assistant', path: '/history' },
  { role: 'assistant', path: '/settings' },
  { role: 'assistant', path: '/assignments' },
  { role: 'assistant', path: '/submissions/example' },
  { role: 'platform_operator', path: '/platform' },
  { role: 'platform_operator', path: '/platform/workspaces' },
  { role: 'platform_operator', path: '/platform/users' },
  { role: 'platform_operator', path: '/platform/health' },
  { role: 'platform_operator', path: '/platform/audit' },
  { role: 'platform_operator', path: '/platform/gemini' },
  { role: 'platform_operator', path: '/platform/integrations' },
  { role: 'platform_operator', path: '/platform/settings' },
  { role: 'platform_operator', path: '/settings' },
]

const PUBLIC = ['/', '/sign-in', '/privacy', '/terms', '/auth/callback', '/auth/classroom']

function session(role: AuditRole) {
  const now = Math.floor(Date.now() / 1000)
  return {
    access_token: 'test-access-token',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: 4102444800,
    refresh_token: 'test-refresh-token',
    user: {
      id: '00000000-0000-4000-8000-000000000001',
      aud: 'authenticated',
      role: 'authenticated',
      email: EMAIL[role],
      email_confirmed_at: new Date(now * 1000).toISOString(),
      phone: '',
      confirmed_at: new Date(now * 1000).toISOString(),
      last_sign_in_at: new Date(now * 1000).toISOString(),
      app_metadata: { provider: 'google', aetrix_role: role },
      user_metadata: { full_name: 'Ana Ruiz', name: 'Ana Ruiz' },
      identities: [],
      created_at: new Date(now * 1000).toISOString(),
      updated_at: new Date(now * 1000).toISOString(),
    },
  }
}

async function seedRole(page: Page, role: AuditRole) {
  await page.addInitScript((payload) => {
    window.localStorage.setItem('aetrix:auth', JSON.stringify(payload))
  }, session(role))
  await stubLegalAcceptance(page)
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'The correction engine is not available.' }),
    }),
  )
}

async function layout(page: Page, _path: string, width: number) {
  await page.setViewportSize({ width, height: WIDTHS.find((entry) => entry.width === width)!.height })
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
      }),
  )
  return page.evaluate(() => {
    const root = document.documentElement
    const body = getComputedStyle(document.body)
    const sidebar = document.querySelector<HTMLElement>('.app-sidebar')
    const tabs = document.querySelector<HTMLElement>('.hub-tabs')
    const clipped = (element: Element) => {
      let parent = element.parentElement
      while (parent && parent !== document.body) {
        const overflow = getComputedStyle(parent).overflowX
        if (overflow === 'hidden' || overflow === 'clip' || overflow === 'auto' || overflow === 'scroll') {
          return true
        }
        parent = parent.parentElement
      }
      return false
    }
    const offenders: string[] = []
    for (const element of Array.from(document.querySelectorAll('body *'))) {
      const style = getComputedStyle(element)
      if (style.display === 'none' || style.visibility === 'hidden' || style.position === 'fixed') {
        continue
      }
      if (element.closest('[aria-hidden="true"]') || clipped(element)) continue
      const rect = element.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) continue
      if (rect.right > innerWidth + 1 || rect.left < -1) {
        offenders.push(
          `${element.tagName.toLowerCase()}.${String(element.className).slice(0, 60)} ` +
            `[${Math.round(rect.left)}, ${Math.round(rect.right)}]`,
        )
      }
      if (offenders.length >= 4) break
    }
    return {
      path: location.pathname,
      main: document.querySelectorAll('main').length,
      h1: document.querySelectorAll('h1').length,
      title: document.title,
      overflow: root.scrollWidth - root.clientWidth,
      offenders,
      background: body.backgroundColor,
      font: body.fontFamily,
      sidebar: sidebar ? getComputedStyle(sidebar).display : 'missing',
      tabs: tabs ? getComputedStyle(tabs).display : 'missing',
    }
  })
}

test.describe('authenticated route coverage', () => {
  for (const entry of ROUTES) {
    test(`${entry.role} ${entry.path} holds at 390, 768 and 1440`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      page.on('console', (message) => {
        if (message.type() === 'error' && !message.text().includes('Failed to load resource')) {
          errors.push(message.text())
        }
      })

      await seedRole(page, entry.role)
      const response = await page.goto(entry.path, { waitUntil: 'load' })
      expect(response?.status()).toBe(200)
      await expect(page.locator('.app-main')).toBeVisible({ timeout: 20_000 })
      await expect(page.locator('.app-content')).toBeVisible()

      for (const viewport of WIDTHS) {
        const result = await layout(page, entry.path, viewport.width)
        expect(
          result.path.replace(/\/+$/, '') || '/',
          `${entry.path} at ${viewport.width}`,
        ).toBe(entry.path.replace(/\/+$/, '') || '/')
        expect(result.main, `${entry.path} main at ${viewport.width}`).toBe(1)
        expect(result.h1, `${entry.path} heading at ${viewport.width}`).toBe(1)
        expect(result.title).not.toBe('')
        expect(result.background, `${entry.path} uses the obsidian surface`).toBe(
          'rgb(11, 13, 15)',
        )
        expect(result.font).toContain('Geist')
        expect(
          result.overflow,
          `${entry.path} overflows at ${viewport.width}px: ${result.offenders.join('; ')}`,
        ).toBeLessThanOrEqual(1)
        expect(result.offenders, `${entry.path} has crossing elements at ${viewport.width}px`).toEqual(
          [],
        )
        if (viewport.width < 1024) {
          expect(result.sidebar, `${entry.path} hides the rail at ${viewport.width}px`).toBe('none')
          expect(result.tabs, `${entry.path} shows the tab bar at ${viewport.width}px`).not.toBe(
            'none',
          )
        } else {
          expect(result.sidebar, `${entry.path} shows the rail at ${viewport.width}px`).not.toBe(
            'none',
          )
          expect(result.tabs, `${entry.path} hides the tab bar at ${viewport.width}px`).toBe('none')
        }
      }
      expect(errors, `${entry.path} logged a runtime error`).toEqual([])
    })
  }
})

test.describe('public route coverage', () => {
  for (const route of PUBLIC) {
    test(`${route} holds at 390, 768 and 1440`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      page.on('console', (message) => {
        if (message.type() === 'error' && !message.text().includes('Failed to load resource')) {
          errors.push(message.text())
        }
      })
      const response = await page.goto(route, { waitUntil: 'load' })
      expect(response?.status()).toBe(200)
      await expect(page.locator('main')).toBeVisible({ timeout: 20_000 })

      for (const viewport of WIDTHS) {
        const result = await layout(page, route, viewport.width)
        expect(result.main, `${route} main at ${viewport.width}`).toBe(1)
        expect(result.h1, `${route} heading at ${viewport.width}`).toBe(1)
        expect(result.background, `${route} uses the obsidian surface`).toBe('rgb(11, 13, 15)')
        expect(result.font).toContain('Geist')
        expect(
          result.overflow,
          `${route} overflows at ${viewport.width}px: ${result.offenders.join('; ')}`,
        ).toBeLessThanOrEqual(1)
        expect(result.offenders, `${route} has crossing elements at ${viewport.width}px`).toEqual([])
      }
      expect(errors, `${route} logged a runtime error`).toEqual([])
    })
  }
})
