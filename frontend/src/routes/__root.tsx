import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router'
import appCss from '../styles/app.css?url'
import hubCss from '../styles/hub.css?url'
import { THEME_INIT_SCRIPT } from '../lib/theme'
import { AuthProvider } from '../lib/auth/AuthProvider'

const TITLE = 'Aetrix V5.5 — Mark smarter. Trust every mark.'
const DESCRIPTION =
  'AI-assisted mathematics marking for Edexcel IGCSE 4MA1, built around examiner-level consistency, transparent corrections and human oversight.'

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { name: 'theme-color', content: '#08090a' },
      { title: TITLE },
      { name: 'description', content: DESCRIPTION },
    ],
    links: [
      { rel: 'stylesheet', href: appCss },
      // The authenticated hub loads after the marketing surface so it can build
      // on the same tokens without touching the public pages.
      { rel: 'stylesheet', href: hubCss },
      {
        rel: 'preload',
        href: '/fonts/schibsted-grotesk.woff2',
        as: 'font',
        type: 'font/woff2',
        crossOrigin: 'anonymous',
      },
    ],
  }),
  shellComponent: RootDocument,
})

/**
 * The document shell only. Chrome lives in the layout routes so the marketing
 * surface and the authenticated application can differ without a path check.
 */
function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <HeadContent />
      </head>
      <body>
        <AuthProvider>{children}</AuthProvider>
        <Scripts />
      </body>
    </html>
  )
}
