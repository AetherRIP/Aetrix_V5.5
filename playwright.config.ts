import { defineConfig, devices } from '@playwright/test'

/**
 * Runs against an already-running preview, so the same suite can be pointed at
 * the local dev server or a deployed environment with BASE_URL.
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  timeout: 45_000,
  /** The headless renderer in this container occasionally loses a page. */
  retries: 2,
  use: {
    baseURL: process.env.BASE_URL ?? 'http://127.0.0.1:3000',
    trace: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        /** Software compositing is unstable in this container without GPU. */
        launchOptions: {
          args: ['--disable-dev-shm-usage', '--in-process-gpu', '--disable-gpu-sandbox'],
        },
      },
    },
  ],
})
