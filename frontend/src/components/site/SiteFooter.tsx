import { Link } from '@tanstack/react-router'
import { Brand } from '../ui/Brand'

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="shell">
        <div className="site-footer__top">
          <div className="site-footer__brand">
            <Brand />
            <p>
              AI-assisted mathematics marking for Edexcel IGCSE 4MA1, built around
              examiner-level consistency and human oversight.
            </p>
          </div>

          <nav className="site-footer__col" aria-label="Product">
            <h2 className="site-footer__heading">Product</h2>
            <Link to="/" hash="platform">Platform preview</Link>
            <Link to="/" hash="workflow">Workflow</Link>
            <Link to="/" hash="features">Features</Link>
            <Link to="/" hash="security">Security</Link>
          </nav>

          <nav className="site-footer__col" aria-label="Access">
            <h2 className="site-footer__heading">Access</h2>
            <Link to="/sign-in">Sign in</Link>
            <Link to="/sign-in" hash="access">Pilot access</Link>
          </nav>

          <nav className="site-footer__col" aria-label="Legal">
            <h2 className="site-footer__heading">Legal</h2>
            <Link to="/terms">Terms of Service</Link>
            <Link to="/privacy">Privacy Policy</Link>
            <Link to="/cookies">Cookie Policy</Link>
            <Link to="/ai-disclosure">AI Use Disclosure</Link>
            <Link to="/acceptable-use">Acceptable Use</Link>
            <Link to="/legal">All legal documents</Link>
          </nav>

          <div className="site-footer__col">
            <h2 className="site-footer__heading">Build</h2>
            <p>TanStack Start 1.0 · React SSR</p>
            <p>Cloudflare Workers</p>
            <p>Multi-tenant by design</p>
          </div>
        </div>

        <div className="site-footer__bottom">
          <p className="mono">© 2026 Aetrix · V5.5 pre-release</p>
          <p className="mono site-footer__note">
            Demonstration data only. No account, pricing or compliance claim is made
            on this site.
          </p>
        </div>
      </div>
    </footer>
  )
}
