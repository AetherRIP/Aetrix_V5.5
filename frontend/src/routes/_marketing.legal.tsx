import { Link, createFileRoute } from '@tanstack/react-router'
import {
  LEGAL_DOCUMENTS,
  LEGAL_DOCUMENT_LIST,
  LEGAL_UPDATED,
  LEGAL_UPDATED_ISO,
} from '../lib/legal'
import { LegalPlaceholder } from '../components/legal/LegalPage'

export const Route = createFileRoute('/_marketing/legal')({
  head: () => ({
    meta: [
      { title: 'Legal centre — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'Every Aetrix legal document in one place: terms, privacy, cookies, acceptable use, AI use, copyright, security and data requests, with versions and dates.',
      },
      { property: 'og:title', content: 'Legal centre — Aetrix V5.5' },
      { property: 'og:type', content: 'article' },
    ],
  }),
  component: LegalCentre,
})

function LegalCentre() {
  return (
    <article className="legal" id="legal-top">
      <div className="shell">
        <header className="legal__head">
          <p className="legal__eyebrow mono">Legal centre</p>
          <h1 className="legal__title">The documents behind the pilot.</h1>
          <p className="legal__lede">
            Aetrix processes examination scripts, mark schemes and account information, and
            it sends marking material to an AI provider. These documents describe what the
            software actually does, what it does not do, and what remains the
            responsibility of the teacher, school or examiner using it.
          </p>

          <dl className="legal__meta">
            <div>
              <dt>Status</dt>
              <dd>Pre-release pilot · pending legal review</dd>
            </div>
            <div>
              <dt>Acceptance versions</dt>
              <dd className="mono">
                Terms {LEGAL_DOCUMENTS.terms.version} · Privacy{' '}
                {LEGAL_DOCUMENTS.privacy.version}
              </dd>
            </div>
            <div>
              <dt>Last updated</dt>
              <dd>
                <time dateTime={LEGAL_UPDATED_ISO}>{LEGAL_UPDATED}</time>
              </dd>
            </div>
            <div>
              <dt>Applies to</dt>
              <dd>aetrix.pages.dev and the Aetrix pilot service</dd>
            </div>
          </dl>

          <p className="legal__notice" role="note">
            <strong>Read this first.</strong> These are pre-release drafts published so the
            pilot’s behaviour is inspectable, not a claim of legal compliance or
            certification. The operator’s legal identity, contact details, governing law
            and liability cap are unresolved and marked in the text. Publishing a policy
            does not by itself make a service compliant with any law.
          </p>
        </header>

        <div className="legal-hub">
          <section aria-labelledby="legal-hub-documents">
            <h2 className="legal-hub__title" id="legal-hub-documents">
              Documents
            </h2>
            <ul className="legal-docs">
              {LEGAL_DOCUMENT_LIST.map((doc) => (
                <li key={doc.id}>
                  <Link className="legal-doc-card" to={doc.path}>
                    <span className="legal-doc-card__title">{doc.title}</span>
                    <span className="legal-doc-card__summary">{doc.summary}</span>
                    <span className="legal-doc-card__meta mono">
                      Version {doc.version}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <section className="legal-hub__block" aria-labelledby="legal-hub-fit">
            <h2 className="legal-hub__title" id="legal-hub-fit">
              How they fit together
            </h2>
            <p>
              The Terms of Service are the agreement for using the service. The Privacy
              Policy explains the personal data the service processes and the basis it
              relies on; the Cookie Policy lists every cookie and browser-storage key. The
              Acceptable Use Policy sets conduct rules, the AI Use Disclosure explains where
              AI is used and how far its output can be trusted, and the Copyright and IP
              Policy covers ownership and infringement reports. The Security Policy states
              the controls and known limitations, and the deletion page explains how to make
              a data request.
            </p>
            <p>
              Where two documents overlap, the Terms of Service control the contractual
              position and the more specific document controls its own subject. Nothing in
              any document limits a right that cannot lawfully be limited.
            </p>
          </section>

          <section className="legal-hub__block" aria-labelledby="legal-hub-requests">
            <h2 className="legal-hub__title" id="legal-hub-requests">
              Privacy, legal and removal requests
            </h2>
            <p>
              The pilot has no self-service account deletion, export or correction screen.
              Requests are handled manually by the operator, and the{' '}
              <Link to="/account-deletion">deletion and data requests page</Link> explains
              what to send and what can be removed. Privacy and legal correspondence goes to{' '}
              <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder> once the
              operator has published a monitored address; no working address exists in this
              build, and no form on this site pretends to deliver one.
            </p>
            <p>
              Schools and institutions that need a data-processing agreement, a security
              schedule or a subprocessor list should treat those as outstanding contractual
              items. None is published here because none has been executed.
            </p>
          </section>

          <section className="legal-hub__block" aria-labelledby="legal-hub-gaps">
            <h2 className="legal-hub__title" id="legal-hub-gaps">
              What these documents cannot settle
            </h2>
            <ul>
              <li>
                Whether Aetrix is a controller, processor or joint controller for a
                particular school deployment.
              </li>
              <li>
                The operator’s legal entity, address, governing law, forum and liability cap.
              </li>
              <li>
                Retention periods, a deletion deadline, and the international-transfer
                mechanism between the operator and its providers.
              </li>
              <li>
                Whether the AI provider retains or trains on submitted material; the
                provider’s terms have not been recorded in this project.
              </li>
            </ul>
            <p>
              Each of these requires a decision by the operator and review by qualified
              counsel. They are listed rather than guessed, because an invented retention
              period or jurisdiction would be a commitment the service cannot keep.
            </p>
          </section>
        </div>
      </div>
    </article>
  )
}
