import { Link, createFileRoute } from '@tanstack/react-router'
import {
  LegalPage,
  LegalPlaceholder,
  LegalSection,
  type LegalTocItem,
} from '../components/legal/LegalPage'
import { LEGAL_DOCUMENTS } from '../lib/legal'

const TOC: LegalTocItem[] = [
  { id: 'scope', label: 'Scope' },
  { id: 'prohibited', label: 'Prohibited conduct' },
  { id: 'integrity', label: 'Educational integrity' },
  { id: 'ai-abuse', label: 'AI and marking abuse' },
  { id: 'content', label: 'Content standards' },
  { id: 'research', label: 'Authorised security research' },
  { id: 'enforcement', label: 'Enforcement' },
  { id: 'reporting', label: 'Reporting misuse' },
  { id: 'consequences', label: 'Consequences and appeals' },
  { id: 'contact', label: 'Contact' },
]

export const Route = createFileRoute('/_marketing/acceptable-use')({
  head: () => ({
    meta: [
      { title: 'Acceptable Use Policy — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'Conduct rules for the Aetrix pilot: no unauthorised access, no access-control bypasses, no malicious uploads, no AI manipulation and no misuse of student or examination material.',
      },
      { property: 'og:title', content: 'Acceptable Use Policy — Aetrix V5.5' },
      { property: 'og:type', content: 'article' },
    ],
  }),
  component: AcceptableUse,
})

function AcceptableUse() {
  return (
    <LegalPage
      doc={LEGAL_DOCUMENTS['acceptable-use']}
      eyebrow="Acceptable Use Policy"
      title="What you must not do with Aetrix."
      lede="Aetrix holds examination scripts and student work. The rules below protect the people in those records, the schools that own them, and the service itself."
      toc={TOC}
    >
      <LegalSection id="scope" number="01" title="Scope">
        <p>
          This policy applies to everyone who reaches an Aetrix surface: visitors to the
          public site, invited accounts, workspace owners and administrators, reviewers,
          assistants, and platform operators. It forms part of the{' '}
          <Link to={LEGAL_DOCUMENTS.terms.path}>Terms of Service</Link>. Breaking it is a
          breach of those terms.
        </p>
        <p>
          It also applies to anything done with material obtained from Aetrix, including
          copies of scripts, mark schemes, marking output and audit records.
        </p>
      </LegalSection>

      <LegalSection id="prohibited" number="02" title="Prohibited conduct">
        <p>You must not:</p>
        <ul>
          <li>
            <strong>Access without authority.</strong> Sign in with credentials that are not
            yours, use another person’s session, or open a workspace, tenant, record or file
            you have not been given access to.
          </li>
          <li>
            <strong>Abuse authentication.</strong> Share accounts or passwords, automate
            credential stuffing, attempt password or token guessing, replay tokens, or
            interfere with the Google or Supabase sign-in flow.
          </li>
          <li>
            <strong>Bypass access controls.</strong> Probe, defeat or work around
            authentication, role checks, tenant isolation, row scoping, upload validation or
            any other control; or use a client, proxy, script or modified page to reach data
            the interface does not offer you.
          </li>
          <li>
            <strong>Abuse the service automatically.</strong> Scrape, crawl or bulk-download
            records; run load tests, denial-of-service attempts or excessive parallel requests
            against the site, the API or the AI provider; or use automation to create jobs or
            uploads at a rate a human could not.
          </li>
          <li>
            <strong>Upload malicious or inappropriate files.</strong> Send malware, exploits,
            scripts, archives, executables or polyglot files; attempt path traversal or
            filename injection; or upload material unrelated to mathematics marking.
          </li>
          <li>
            <strong>Infringe intellectual property.</strong> Upload or redistribute
            examination papers, mark schemes, textbooks or other material in breach of
            copyright, a licensing condition, an examination board’s rules or a school’s
            policy. See the{' '}
            <Link to={LEGAL_DOCUMENTS.copyright.path}>
              Intellectual Property and Copyright Policy
            </Link>
            .
          </li>
          <li>
            <strong>Misuse educational content.</strong> Publish, sell, publish excerpts of,
            or repurpose student scripts, candidate numbers, teacher annotations or marking
            records; or use the service to build a competing dataset or product.
          </li>
          <li>
            <strong>Manipulate the AI system.</strong> Use prompt injection, hidden
            instructions, adversarial images or crafted mark schemes to make the marking
            engine award or withhold marks, fabricate evidence, or ignore its review rules.
          </li>
          <li>
            <strong>Harass or act unlawfully.</strong> Threaten, harass, defame or
            discriminate against any person; upload unlawful material; or use the service for
            fraud, extortion or any other criminal purpose.
          </li>
          <li>
            <strong>Misrepresent authority.</strong> Claim to act for a school, examination
            board or candidate when you do not, or upload a child’s information without the
            authority of the responsible institution.
          </li>
        </ul>
      </LegalSection>

      <LegalSection id="integrity" number="03" title="Educational integrity">
        <p>
          Aetrix is a marking aid for teachers and authorised reviewers. It must not be used
          to let a candidate see or influence marking decisions, to produce an official
          result, or to replace the moderation and appeals process of a school or examination
          board.
        </p>
        <p>
          Presenting unapproved AI output as a final or official mark is a breach of this
          policy, as is using the service to mark live examination material in a way that
          breaches examination board rules or the school’s own instructions.
        </p>
      </LegalSection>

      <LegalSection id="ai-abuse" number="04" title="AI and marking abuse">
        <p>
          The marking engine is instructed to propose marks, cite evidence and flag
          uncertainty. Attempts to defeat those instructions — including text embedded in a
          page image, a fabricated mark scheme, or an instruction in a filename or comment —
          are prohibited, whether or not they succeed.
        </p>
        <p>
          You must not attempt to extract provider credentials, prompts or internal
          configuration from the service, or use the marking endpoints as a general-purpose
          model API. The{' '}
          <Link to={LEGAL_DOCUMENTS['ai-disclosure'].path}>AI Use Disclosure</Link> explains
          what the models are asked to do.
        </p>
      </LegalSection>

      <LegalSection id="content" number="05" title="Content standards">
        <p>
          Upload only what is needed for the marking task: the script, the mark scheme, the
          blueprint or the teacher’s own material. Do not upload special-category
          information, health information, safeguarding records, home addresses, contact
          details or anything unrelated to the assessment. Where the interface allows a
          pseudonymous student reference, prefer it over a full name.
        </p>
        <p>
          You are responsible for confirming that you have the authority to upload each
          document and that any notice or consent required by your school, examination board
          or the law has been given.
        </p>
      </LegalSection>

      <LegalSection id="research" number="06" title="Authorised security research">
        <p>
          Good-faith security research is welcome within the rules in the{' '}
          <Link to={LEGAL_DOCUMENTS.security.path}>
            Security and Vulnerability Disclosure Policy
          </Link>
          . Research that stays inside those rules is not a breach of this policy. Research
          that reaches another tenant’s data, degrades the service, or is disclosed publicly
          before a fix is a breach.
        </p>
      </LegalSection>

      <LegalSection id="enforcement" number="07" title="Enforcement">
        <p>
          The operator may investigate suspected breaches and may remove content, suspend a
          session, restrict a feature, suspend or terminate an account, or notify the
          workspace owner, the school or a competent authority. Where the risk is to a
          student or to the service, access may be suspended immediately and explained
          afterwards.
        </p>
        <p>
          Enforcement decisions are made by a person. The pilot has no automated
          suspension system and no appeal queue in the application, so a decision is
          communicated through the workspace owner or by direct contact.
        </p>
      </LegalSection>

      <LegalSection id="reporting" number="08" title="Reporting misuse">
        <p>
          Report suspected misuse — a compromised account, an unauthorised upload, a
          misdirected script, or an attempt to manipulate marking — to the workspace owner
          and to <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>. Include
          the workspace, the record or job identifier if you have one, and what you observed.
          Do not forward student scripts to anyone who does not need them.
        </p>
        <p>
          Security vulnerabilities should go through the security policy’s reporting route
          rather than this address.
        </p>
      </LegalSection>

      <LegalSection id="consequences" number="09" title="Consequences and appeals">
        <p>
          A breach can end access to the pilot, and serious breaches can be reported to the
          institution or to the authorities. Where an account is suspended for a suspected
          breach, the account holder may ask the operator to review the decision; the review
          is manual and the pilot does not promise a response time.
        </p>
        <p>
          Suspension does not delete data. Data is handled under the{' '}
          <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link> and the deletion page
          if the account is closed.
        </p>
      </LegalSection>

      <LegalSection id="contact" number="10" title="Contact">
        <p>
          Questions about this policy can be sent to{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>. The complete
          set of documents is in the <Link to="/legal">legal centre</Link>.
        </p>
        <p>
          This policy is a technical and product draft. It is not legal advice and should be
          reviewed by qualified counsel before it is treated as final.
        </p>
      </LegalSection>
    </LegalPage>
  )
}
