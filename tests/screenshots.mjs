import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:3000'
const OUT = 'docs/implementation/screenshots'
const ARGS = ['--disable-dev-shm-usage', '--in-process-gpu', '--disable-gpu-sandbox']

await mkdir(OUT, { recursive: true })

const shots = [
  { name: 'landing-dark', path: '/', width: 1280, height: 900, theme: 'dark', full: true },
  { name: 'landing-light', path: '/', width: 1280, height: 900, theme: 'light', full: true },
  { name: 'landing-hero-dark', path: '/', width: 1440, height: 920, theme: 'dark', full: false },
  { name: 'landing-hero-light', path: '/', width: 1440, height: 920, theme: 'light', full: false },
  { name: 'landing-mobile', path: '/', width: 390, height: 844, theme: 'dark', full: true },
  { name: 'landing-tablet', path: '/', width: 834, height: 1000, theme: 'light', full: true },
  { name: 'sign-in', path: '/sign-in', width: 1280, height: 900, theme: 'dark', full: true },
]

async function capture(shot) {
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const browser = await chromium.launch({ args: ARGS })
    try {
      const context = await browser.newContext({
        viewport: { width: shot.width, height: shot.height },
        deviceScaleFactor: 1,
        colorScheme: shot.theme,
        reducedMotion: 'reduce',
      })
      const page = await context.newPage()
      await page.addInitScript((theme) => {
        window.localStorage.setItem('mathchecker:theme', theme)
      }, shot.theme)
      await page.goto(`${BASE}${shot.path}`, { waitUntil: 'load', timeout: 20000 })
      await page.waitForTimeout(700)
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
      await page.waitForTimeout(400)
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.waitForTimeout(300)
      await page.screenshot({ path: `${OUT}/${shot.name}.png`, fullPage: shot.full })
      console.log('captured', shot.name, `(attempt ${attempt})`)
      await browser.close()
      return true
    } catch (error) {
      console.log('retry', shot.name, String(error).split('\n')[0])
      await browser.close().catch(() => {})
      await new Promise((resolve) => setTimeout(resolve, 1500))
    }
  }
  console.log('FAILED', shot.name)
  return false
}

let failures = 0
for (const shot of shots) {
  const ok = await capture(shot)
  if (!ok) failures += 1
}

console.log(failures === 0 ? 'all screenshots captured' : `${failures} screenshot(s) failed`)
process.exitCode = failures === 0 ? 0 : 1
