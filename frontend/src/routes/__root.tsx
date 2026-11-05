import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router'
import appCss from '../styles/app.css?url'
import { THEME_INIT_SCRIPT } from '../lib/theme'
import { SiteHeader } from '../components/site/SiteHeader'
import { SiteFooter } from '../components/site/SiteFooter'

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

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <HeadContent />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to main content
        </a>
        <SiteHeader />
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <SiteFooter />
        <Scripts />
      </body>
    </html>
  )
}
