import { Link, createFileRoute } from '@tanstack/react-router'
import {
  LegalPage,
  LegalPlaceholder,
  LegalSection,
  type LegalTocItem,
} from '../components/legal/LegalPage'
import { LEGAL_DOCUMENTS } from '../lib/legal'

const TOC: LegalTocItem[] = [
  { id: 'scope', label: 'What this policy covers' },
  { id: 'controls', label: 'Controls in place' },
  { id: 'limitations', label: 'Known limitations' },
  { id: 'reporting', label: 'Reporting a vulnerability' },
  { id: 'rules', label: 'Rules for security research' },
  { id: 'expect', label: 'What to expect from us' },
  { id: 'breach', label: 'Security incidents and notification' },
  { id: 'contact', label: 'Contact' },
]

export const Route = createFileRoute('/_marketing/security')({
  head: () => ({
    meta: [
      { title: 'Security and Vulnerability Disclosure Policy — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'The security controls the Aetrix pilot implements, the limitations it discloses, and how to report a vulnerability responsibly.',
      },
      { property: 'og:title', content: 'Security and Vulnerability Disclosure Policy — Aetrix V5.5' },
      { property: 'og:type', content: 'article' },
    ],
  }),
  component: SecurityPolicy,
})

function SecurityPolicy() {
  return (
    <LegalPage
      doc={LEGAL_DOCUMENTS.security}
      eyebrow="Security"
      title="What protects the data, and what does not yet."
      lede="Aetrix holds examination scripts and account records. This page states the controls that exist in the code, the gaps the operator has not closed, and how to report a vulnerability without putting student data at risk."
      toc={TOC}
    >
      <LegalSection id="scope" number="01" title="What this policy covers">
        <p>
          This policy covers the public website, the authenticated frontend, the FastAPI
          engine, its database and its local file store, as operated for the pilot. It does
          not cover Google, Supabase, Cloudflare, Tailscale or any other provider’s own
          systems, which are governed by their terms.
        </p>
        <p>
          It also explains how the operator responds to a report. It is not a certification
          and it does not promise a service level.
        </p>
      </LegalSection>

      <LegalSection id="controls" number="02" title="Controls in place">
        <p>The following are implemented and visible in the source code:</p>
        <ul>
          <li>
            HTTPS for the public site, the API, Supabase and Google; the browser bundle holds
            only Supabase’s publishable key, never a service-role key or provider credential.
          </li>
          <li>
            Supabase-issued JSON Web Tokens are verified server-side, and the tenant is
            resolved from the verified claim rather than from a request body, so one workspace
            cannot address another by asking for it.
          </li>
          <li>
            Role and membership checks on workspace and administrative routes, enforced in the
            engine rather than in the browser.
          </li>
          <li>
            Provider credentials encrypted with Fernet and never returned to the browser; the
            frontend receives a fingerprint, not the secret.
          </li>
          <li>
            Upload validation: declared type and size limits (PDF, PNG and JPEG, 25 MiB, up to
            80 pages), page and pixel caps, checksums, and a path-traversal guard around the
            local file store.
          </li>
          <li>
            Structured JSON logs that redact bearer tokens, API keys, JSON Web Tokens, long
            hexadecimal values and sensitive field names, and that do not record request bodies
            or prompts.
          </li>
          <li>
            Append-only audit and provider-usage records, so approval and administrative
            actions leave a trail.
          </li>
        </ul>
        <p>
          The <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link> describes the data
          these controls protect.
        </p>
      </LegalSection>

      <LegalSection id="limitations" number="03" title="Known limitations">
        <p>
          The pilot does not have the following, and a reader should not assume otherwise:
        </p>
        <ul>
          <li>malware scanning or antivirus quarantine for uploads;</li>
          <li>application-level rate limiting or request throttling;</li>
          <li>
            database row-level security relied on for isolation — tenancy is enforced by the
            application layer;
          </li>
          <li>
            independent encryption of stored files by Aetrix; files sit on the operator host
            and rely on its disk controls;
          </li>
          <li>
            a consented, time-limited support-access feature — platform operators can reach
            workspace data when resolving an incident, without a scoped grant;
          </li>
          <li>
            enforced multi-factor authentication — this depends on the user’s Google account;
          </li>
          <li>
            a penetration test, an ISO 27001 or SOC 2 certification, or any independent audit;
          </li>
          <li>
            24/7 monitoring, a formal incident-response runbook, or a tested disaster-recovery
            and backup-restore procedure; and
          </li>
          <li>
            a public status page. Availability reporting is direct communication with workspace
            owners.
          </li>
        </ul>
        <p>
          These are recorded as gaps rather than described as roadmap certainty. A school that
          requires them should not treat the pilot as meeting its procurement standard yet.
        </p>
      </LegalSection>

      <LegalSection id="reporting" number="04" title="Reporting a vulnerability">
        <p>
          Send reports to <LegalPlaceholder>SECURITY CONTACT — TO BE CONFIRMED</LegalPlaceholder>.
          A monitored address has not been published in this build; until one is, a report can
          be raised with the workspace owner, who will pass it to the operator.
        </p>
        <p>A useful report includes:</p>
        <ul>
          <li>the affected URL, endpoint or component, and the version or date you tested;</li>
          <li>the impact you believe it has, including which data could be reached;</li>
          <li>clear reproduction steps, with requests or screenshots where helpful;</li>
          <li>whether you accessed any real data, and what you did with it; and</li>
          <li>how you would like to be credited, or a request to remain anonymous.</li>
        </ul>
        <p>
          Do not attach student scripts, personal data or provider credentials to a report.
          Describe the access instead.
        </p>
      </LegalSection>

      <LegalSection id="rules" number="05" title="Rules for security research">
        <p>Research is welcome if it stays within these limits:</p>
        <ul>
          <li>
            test only accounts and workspaces you are authorised to use, or a workspace the
            operator has explicitly made available for testing;
          </li>
          <li>
            do not access, download, alter or retain another person’s data; if you reach it
            accidentally, stop, do not copy it, and report it;
          </li>
          <li>
            do not degrade the service: no denial-of-service, load testing, brute force, spam
            or automated scanning that affects availability or provider quota;
          </li>
          <li>do not use social engineering, phishing or physical intrusion;</li>
          <li>
            do not test the AI provider’s platform directly, and do not attempt to extract
            provider credentials or prompts through the marking endpoints; and
          </li>
          <li>
            give the operator a reasonable opportunity to fix the issue before publishing
            details, and do not publish student data at any point.
          </li>
        </ul>
        <p>
          The operator intends not to pursue action against a researcher who follows these
          rules and acts in good faith. That intention is not a legal waiver, it does not bind
          any third party, and it is subject to review by counsel.
        </p>
      </LegalSection>

      <LegalSection id="expect" number="06" title="What to expect from us">
        <p>
          The operator will try to acknowledge a report within five working days and to say
          whether it is being investigated. That target is a courtesy, not a contractual
          service level, and the pilot has no bug-bounty programme or payment.
        </p>
        <p>
          Fixes are made by a small team. A fix may be deployed without a public advisory; if a
          report affects workspace data, the affected workspace owners will be told directly.
          Credit is given if you ask for it and the disclosure is coordinated.
        </p>
      </LegalSection>

      <LegalSection id="breach" number="07" title="Security incidents and notification">
        <p>
          If a personal-data breach occurs, the operator intends to contain it, assess its
          scope, and notify affected workspace owners and any competent authority where the
          applicable law requires it. The pilot does not yet have a written incident-response
          procedure with fixed decision points and deadlines; this is recorded as an open
          compliance item.
        </p>
        <p>
          A school that uses Aetrix should have its own route for reporting a suspected breach
          to the operator, and should not assume the service will detect it independently.
        </p>
      </LegalSection>

      <LegalSection id="contact" number="08" title="Contact">
        <p>
          Security correspondence: <LegalPlaceholder>SECURITY CONTACT — TO BE CONFIRMED</LegalPlaceholder>.
          Privacy correspondence: <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>.
          The complete set of documents is in the <Link to="/legal">legal centre</Link>.
        </p>
        <p>
          This policy is a technical and product draft. It is not legal advice and should be
          reviewed by qualified counsel before it is treated as final.
        </p>
      </LegalSection>
    </LegalPage>
  )
}
