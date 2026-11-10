/**
 * Remove build-output files that must never be uploaded.
 *
 * The Cloudflare Vite plugin mirrors `frontend/.env` into
 * `dist/server/.dev.vars` during a build. Only the three public `VITE_*`
 * browser values can ever appear there — the service-role key is never read by
 * this application — but a `.dev.vars` file has no business inside a deployment
 * artifact: one careless future variable and a secret ships. Deleting it at the
 * end of the build makes the artifact safe by construction rather than by
 * review.
 */
import { readdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

// ``URL.pathname`` is ``/C:/...`` on Windows, which no filesystem accepts; the
// earlier version therefore found nothing and reported success while the build
// artifact stayed in place. ``fileURLToPath`` is the portable answer.
const root = fileURLToPath(new URL('../dist/', import.meta.url))

async function strip(directory) {
  let entries
  try {
    entries = await readdir(directory, { withFileTypes: true })
  } catch (error) {
    if (error.code === 'ENOENT') return
    throw error
  }
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      await strip(path)
    } else if (entry.name === '.dev.vars' || entry.name === '.dev.vars.example') {
      await rm(path)
      console.log(`removed build artifact ${path}`)
    }
  }
}

await strip(root)
