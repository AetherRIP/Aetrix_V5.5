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
    tanstackStart(),
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
