import { defineConfig } from 'vite'
import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import viteReact from '@vitejs/plugin-react'
import { cloudflare } from '@cloudflare/vite-plugin'

/**
 * The preview host is supplied by the environment rather than committed, so the
 * repository never carries a machine-specific hostname. Set PREVIEW_HOST to the
 * exact hostname the preview is served from.
 */
const previewHost = process.env.PREVIEW_HOST

const allowedHosts = previewHost ? [previewHost] : []

export default defineConfig({
  resolve: { tsconfigPaths: true },
  plugins: [
    cloudflare({ viteEnvironment: { name: 'ssr' } }),
    // Cloudflare Pages serves the frontend as static assets. Prerendering emits
    // real HTML for every public route at build time so a Pages deployment does
    // not need an SSR Worker. It changes build output only, not app behaviour.
    tanstackStart({
      // Application routes sit behind the session gate, so the crawler cannot
      // reach them from the landing page. They are listed explicitly: each one
      // emits real HTML, which is what makes a refresh on a nested route work
      // on static hosting.
      pages: [
        { path: '/dashboard' },
        { path: '/workspace' },
        { path: '/inbox' },
        { path: '/queue' },
        { path: '/assignments' },
        { path: '/assignments/example' },
        { path: '/submissions/example' },
        { path: '/reports' },
        { path: '/settings' },
        { path: '/auth/callback' },
        { path: '/legal' },
        { path: '/privacy' },
        { path: '/terms' },
        { path: '/cookies' },
        { path: '/acceptable-use' },
        { path: '/ai-disclosure' },
        { path: '/copyright' },
        { path: '/security' },
        { path: '/account-deletion' },
      ],
      prerender: {
        enabled: true,
        crawlLinks: true,
        autoSubfolderIndex: true,
        failOnError: true,
      },
    }),
    viteReact(),
  ],
  server: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts,
  },
  preview: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts,
  },
})
