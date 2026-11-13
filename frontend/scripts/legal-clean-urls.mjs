/**
 * Cloudflare Pages redirects `/privacy` to `/privacy/` (308) when the only
 * artifact is `privacy/index.html`. Google's OAuth consent screen and the
 * published policy URLs use the slashless form, so emit a sibling
 * `privacy.html` as well: Pages then serves `/privacy` directly with HTTP 200,
 * while `/privacy/` continues to work.
 */
import { copyFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const clientRoot = fileURLToPath(new URL('../dist/client/', import.meta.url))

for (const route of [
  'legal',
  'privacy',
  'terms',
  'cookies',
  'acceptable-use',
  'ai-disclosure',
  'copyright',
  'security',
  'account-deletion',
]) {
  const source = `${clientRoot}${route}/index.html`
  const target = `${clientRoot}${route}.html`
  await copyFile(source, target)
  console.log(`emitted clean URL artifact ${target}`)
}
