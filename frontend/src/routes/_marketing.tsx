import { Outlet, createFileRoute } from '@tanstack/react-router'
import { SiteHeader } from '../components/site/SiteHeader'
import { SiteFooter } from '../components/site/SiteFooter'

/** Public marketing chrome: header, main landmark and footer. */
export const Route = createFileRoute('/_marketing')({
  component: MarketingLayout,
})

function MarketingLayout() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <SiteHeader />
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <SiteFooter />
    </>
  )
}
