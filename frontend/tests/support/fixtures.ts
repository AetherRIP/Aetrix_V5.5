import { test as base, expect } from '@playwright/test'
import { stubLegalAcceptance } from './legal-acceptance'

/**
 * The authenticated shell now refuses to render until the account's recorded
 * legal acceptance is confirmed from the database. Specs that seed a session
 * therefore have to answer that request, or they would be testing the gate
 * instead of the screen they name.
 *
 * The stub is installed on the context, so every page a spec opens — including
 * ones created with `context.newPage()` — sees the same accepted account. A test
 * that needs a different answer installs its own `page.route`, which takes
 * priority over the context route.
 */
export const test = base.extend({
  context: async ({ context }, use) => {
    await stubLegalAcceptance(context)
    await use(context)
  },
})

export { expect }
