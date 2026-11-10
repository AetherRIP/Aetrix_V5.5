import type { ReactNode } from 'react'
import { Link } from '@tanstack/react-router'

export type LegalTocItem = { id: string; label: string }

type LegalPageProps = {
  eyebrow: string
  title: string
  lede: string
  updated: string
  toc: LegalTocItem[]
  children: ReactNode
}

/**
 * Shared shell for the public legal pages. It is deliberately not behind the
 * application shell or the session gate: Google's OAuth review and any visitor
 * must be able to read these pages without an account.
 */
export function LegalPage({ eyebrow, title, lede, updated, toc, children }: LegalPageProps) {
  return (
    <article className="legal" id="legal-top">
      <div className="shell">
        <header className="legal__head">
          <p className="legal__eyebrow mono">{eyebrow}</p>
          <h1 className="legal__title">{title}</h1>
          <p className="legal__lede">{lede}</p>

          <dl className="legal__meta">
            <div>
              <dt>Status</dt>
              <dd>Pre-release pilot · pending legal review</dd>
            </div>
            <div>
              <dt>Last updated</dt>
              <dd>
                <time dateTime="2026-11-09">{updated}</time>
              </dd>
            </div>
            <div>
              <dt>Applies to</dt>
              <dd>aetrix.pages.dev and the Aetrix pilot service</dd>
            </div>
          </dl>

          <p className="legal__notice" role="note">
            <strong>Publication status.</strong> This is a pre-release policy published for
            the Aetrix pilot. The operator’s legal identity, contact details, governing law
            and some liability terms are unresolved and marked in the text. It is a
            technical and product draft, not legal advice, and it should not be treated as
            final until qualified counsel has reviewed it.
          </p>
        </header>

        <div className="legal__body">
          <nav className="legal__toc" aria-label="On this page">
            <p className="legal__toc-title mono">On this page</p>
            <ol>
              {toc.map((item, index) => (
                <li key={item.id}>
                  <a href={`#${item.id}`}>
                    <span className="legal__toc-num mono" aria-hidden="true">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span>{item.label}</span>
                  </a>
                </li>
              ))}
            </ol>
            <div className="legal__toc-links">
              <Link to="/privacy">Privacy Policy</Link>
              <Link to="/terms">Terms of Service</Link>
              <Link to="/">Back to Aetrix</Link>
              <a href="#legal-top">Back to top</a>
            </div>
          </nav>

          <div className="legal__content">{children}</div>
        </div>
      </div>
    </article>
  )
}

type LegalSectionProps = {
  id: string
  number: string
  title: string
  children: ReactNode
}

export function LegalSection({ id, number, title, children }: LegalSectionProps) {
  return (
    <section className="legal__section" id={id} aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>
        <span className="legal__num mono" aria-hidden="true">
          {number}
        </span>
        <span>{title}</span>
      </h2>
      {children}
    </section>
  )
}

/** Marks a fact that the repository does not establish and the owner must supply. */
export function LegalPlaceholder({ children }: { children: ReactNode }) {
  return <mark className="legal__placeholder">{children}</mark>
}
