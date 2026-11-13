import { Link, createFileRoute } from '@tanstack/react-router'
import {
  LegalPage,
  LegalPlaceholder,
  LegalSection,
  type LegalTocItem,
} from '../components/legal/LegalPage'
import { LEGAL_DOCUMENTS } from '../lib/legal'

const TOC: LegalTocItem[] = [
  { id: 'acceptance', label: 'Acceptance of these terms' },
  { id: 'other-policies', label: 'Other policies that apply' },
  { id: 'description', label: 'What Aetrix is' },
  { id: 'eligibility', label: 'Eligibility and accounts' },
  { id: 'account-security', label: 'Account security' },
  { id: 'google', label: 'Google authentication' },
  { id: 'roles', label: 'Workspace roles' },
  { id: 'acceptable-use', label: 'Acceptable use' },
  { id: 'content', label: 'Educational content and uploads' },
  { id: 'ai-limits', label: 'AI marking and its limits' },
  { id: 'human-review', label: 'Human review and final grading' },
  { id: 'ip', label: 'Intellectual property' },
  { id: 'content-licence', label: 'Your content and permissions' },
  { id: 'third-parties', label: 'Third-party services' },
  { id: 'availability', label: 'Availability and interruptions' },
  { id: 'fees', label: 'Fees and no paid plans' },
  { id: 'termination', label: 'Suspension and termination' },
  { id: 'disclaimers', label: 'Disclaimers' },
  { id: 'liability', label: 'Limitation of liability' },
  { id: 'indemnity', label: 'Indemnity' },
  { id: 'changes', label: 'Changes to these terms' },
  { id: 'law', label: 'Governing law and disputes' },
  { id: 'contact', label: 'Contact' },
]

export const Route = createFileRoute('/_marketing/terms')({
  head: () => ({
    meta: [
      { title: 'Terms of Service — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'The terms for the pre-release Aetrix mathematics-marking pilot, including acceptable use, AI marking limitations, human review responsibilities, and liability.',
      },
      { property: 'og:title', content: 'Terms of Service — Aetrix V5.5' },
      { property: 'og:type', content: 'article' },
    ],
  }),
  component: TermsOfService,
})

function TermsOfService() {
  return (
    <LegalPage
      doc={LEGAL_DOCUMENTS.terms}
      eyebrow="Terms of Service"
      title="The rules for using the Aetrix pilot."
      lede="These terms explain what the pre-release Aetrix service does, what it does not do, and the responsibilities that remain with the teachers, schools, and reviewers who use it."
      toc={TOC}
    >
      <LegalSection id="acceptance" number="01" title="Acceptance of these terms">
        <p>
          These Terms of Service (“terms”) are an agreement between you and{' '}
          <LegalPlaceholder>OPERATOR LEGAL ENTITY — TO BE CONFIRMED</LegalPlaceholder>, of{' '}
          <LegalPlaceholder>REGISTERED ADDRESS — TO BE CONFIRMED</LegalPlaceholder>{' '}
          (“Aetrix”, “we”, “us”). By accessing the public site, signing in, or using an
          Aetrix workspace, you agree to these terms and to the Privacy Policy.
        </p>
        <p>
          If you use Aetrix for a school or other organisation, you confirm that you are
          authorised to accept these terms for that organisation, or that you are using the
          service under a separate agreement with the operator. If you do not agree, do not
          use the service.
        </p>
        <p>
          After you sign in, the service asks you to accept these terms and the Privacy Policy
          before it opens a workspace, and it does not open one if you have not. Each acceptance
          is recorded against your account — the document, its version, and a server-generated
          time — so it is asked once and not on every visit, refresh or device. You are asked
          again only when a document you accepted is published at a new version. If the record
          cannot be read, or cannot be written when you accept, the workspace stays closed.
        </p>
      </LegalSection>

      <LegalSection id="other-policies" number="02" title="Other policies that apply">
        <p>These terms incorporate the following documents, which explain their own subject in more detail:</p>
        <ul>
          <li>
            the <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link> — the personal
            data processed and the basis relied on;
          </li>
          <li>
            the <Link to={LEGAL_DOCUMENTS.cookies.path}>Cookie Policy</Link> — every cookie and
            browser-storage key;
          </li>
          <li>
            the <Link to={LEGAL_DOCUMENTS['acceptable-use'].path}>Acceptable Use Policy</Link> —
            prohibited conduct and enforcement;
          </li>
          <li>
            the <Link to={LEGAL_DOCUMENTS['ai-disclosure'].path}>AI Use Disclosure</Link> — where
            AI is used and what it cannot be trusted to do;
          </li>
          <li>
            the <Link to={LEGAL_DOCUMENTS.copyright.path}>Intellectual Property and Copyright
            Policy</Link> — ownership, licensing and infringement reports; and
          </li>
          <li>
            the <Link to={LEGAL_DOCUMENTS.security.path}>Security and Vulnerability Disclosure
            Policy</Link> — controls, limitations and vulnerability reporting.
          </li>
        </ul>
        <p>
          If they conflict, these terms control the contractual position and the more specific
          document controls its own subject.
        </p>
      </LegalSection>

      <LegalSection id="description" number="03" title="Description of Aetrix">
        <p>
          Aetrix is a pre-release, invitation-only service that assists teachers with marking
          Edexcel IGCSE 4MA1 mathematics scripts. It renders uploaded pages, sends page images
          and marking material to a configured AI provider, proposes question-level marks and
          supporting evidence, flags uncertainty for human review, and records review and
          approval decisions.
        </p>
        <p>
          Aetrix is not an examination board, does not administer examinations, does not issue
          official results, and does not provide legal, regulatory or professional advice.
          Aetrix does not claim affiliation with, sponsorship by or endorsement by Pearson
          Edexcel, Google or any examination board. The service is a pilot and may change, be
          incomplete, or be withdrawn.
        </p>
      </LegalSection>

      <LegalSection id="eligibility" number="04" title="Eligibility and account registration">
        <p>
          You must have the legal capacity to enter into these terms in your jurisdiction. If
          you are below the age of legal majority, you may use Aetrix only through an
          educational institution or under the supervision of an adult who is authorised to act
          for you. Aetrix does not set a separate minimum age and does not verify age; a
          confirmed minimum-age position is an open legal decision.
        </p>
        <p>
          There is no self-service sign-up. Accounts are provisioned by an administrator or by
          the operator, usually by invitation or with a one-time acceptance code. You must give
          accurate account information and must not create an account for someone else or share
          yours.
        </p>
      </LegalSection>

      <LegalSection id="account-security" number="05" title="Account security">
        <p>
          Keep your Google account and any password secure, use a device you control, and sign
          out on a shared machine. Tell the workspace owner and the operator promptly if you
          believe your account has been used without authority, or if a device holding a session
          is lost or stolen.
        </p>
        <p>
          Signing in stores a session in this browser so you stay signed in across refreshes; on
          a shared device, sign out when you finish. Aetrix does not enforce multi-factor
          authentication itself; that protection comes from your Google account, and the
          security policy records this as a limitation.
        </p>
      </LegalSection>

      <LegalSection id="google" number="06" title="Google authentication">
        <p>
          The primary sign-in method is Google OAuth, brokered by Supabase Auth. Aetrix receives
          basic profile and email information (account identifier, email address, name and
          profile-image URL). Sign-in does not request access to Gmail, Google Drive, Google
          Classroom, Google Calendar or other Google content. Separately, a workspace owner or
          administrator may choose to connect Google Classroom, which requests read-only access
          to the workspace’s course list. That connection can be disconnected at any time and is
          described in the <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link>.
        </p>
        <p>
          Your use of your Google account is governed by Google’s terms. Aetrix does not control
          Google, cannot guarantee that Google sign-in will always be available, and is not
          responsible for Google’s decisions about your account. If email-and-password sign-in
          is enabled for your account, keep that password secure and do not reuse it.
        </p>
      </LegalSection>

      <LegalSection id="roles" number="07" title="Workspace roles and responsibilities">
        <p>
          A workspace uses roles such as owner, administrator, teacher or reviewer, assistant
          or viewer, and platform operator. The exact permissions are enforced by the service
          and shown in the workspace. In general:
        </p>
        <ul>
          <li>the workspace owner controls membership, workspace settings and the highest-level approvals;</li>
          <li>administrators invite and manage members and may upload or review content;</li>
          <li>teachers and reviewers upload scripts and material, resolve flagged questions and approve results;</li>
          <li>assistants and viewers may read or support work but must not approve results unless the service permits it; and</li>
          <li>platform operators administer the service, provider credentials and platform audit, and do not become the school’s decision-maker.</li>
        </ul>
        <p>
          A workspace owner must ensure that members have appropriate authority and training.
          Role checks reduce the risk of unauthorised access, but no permission system is
          perfect; report suspected unauthorised access promptly.
        </p>
      </LegalSection>

      <LegalSection id="acceptable-use" number="08" title="Acceptable use">
        <p>
          You must use Aetrix lawfully and only for its intended educational purpose. In
          summary, you must not access another workspace or account without authority, abuse or
          bypass authentication and access controls, send automated or excessive requests,
          upload malicious or unrelated files, infringe intellectual property, misuse student or
          examination material, attempt to manipulate the AI system, or harass any person.
        </p>
        <p>
          The full list, the rules on security research and the enforcement position are in the{' '}
          <Link to={LEGAL_DOCUMENTS['acceptable-use'].path}>Acceptable Use Policy</Link>, which
          forms part of these terms. The operator may investigate suspected misuse and may
          remove content or suspend access where it reasonably believes these rules or the law
          have been breached.
        </p>
      </LegalSection>

      <LegalSection id="content" number="09" title="Educational content and uploaded files">
        <p>
          You are responsible for the scripts, mark schemes, blueprints, images and other
          material you upload, and for having the rights and authority to upload them. This
          includes ensuring that student work is uploaded only with the authority of the school
          or institution responsible for it, and that any required notices or consents have been
          given.
        </p>
        <p>
          The pilot accepts PDF, PNG and JPEG files up to 25 MiB and up to 80 pages per document.
          Do not upload unrelated documents, executable files, or material that is unlawful or
          that you do not need for marking. Uploaded files may contain student names,
          handwriting, candidate numbers, answers, marks or teacher annotations; the{' '}
          <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link> explains how they are
          stored and processed.
        </p>
        <p>
          We do not undertake to monitor every upload, and the pilot does not scan uploads for
          malware. We may review content when needed to operate, secure or support the service,
          investigate a report, or comply with law, and we may remove content that breaches
          these terms or creates a security or legal risk.
        </p>
      </LegalSection>

      <LegalSection id="ai-limits" number="10" title="AI-generated marking and its limitations">
        <p>
          Aetrix uses a third-party AI model to interpret page images and propose marks. AI
          output is probabilistic. It can misread handwriting, diagrams, symbols or page layout;
          misunderstand a mark scheme; omit or invent working; apply a criterion inconsistently;
          or produce a confident but wrong answer. Confidence values and supporting evidence are
          aids to review, not guarantees of correctness.
        </p>
        <p>
          The configured model, provider, prompts and review settings may change during the
          pilot. AI processing may be unavailable, delayed, rate-limited or incomplete. Aetrix
          does not guarantee that its output matches an examiner, an examination board or another
          marker, and does not guarantee any particular mark, grade or outcome. The{' '}
          <Link to={LEGAL_DOCUMENTS['ai-disclosure'].path}>AI Use Disclosure</Link> sets out the
          failure modes in detail.
        </p>
        <p>
          AI output is provisional. It must not be presented as an infallible result, an official
          examination result, or a substitute for professional judgement, and it must not be the
          sole basis for a decision that significantly affects a student.
        </p>
      </LegalSection>

      <LegalSection id="human-review" number="11" title="Human review and final grading responsibility">
        <p>
          Aetrix flags questions that need review and does not permit a job to be approved while
          any question remains flagged. An authorised reviewer must resolve each flag by
          upholding, overriding or otherwise recording a decision, and an authorised approver
          must then approve the result. The approval record identifies the approver, the time and
          the approved totals.
        </p>
        <p>
          The teacher, school or other responsible institution remains responsible for the final
          mark or grade, for checking the output against the mark scheme and the student’s work,
          and for handling appeals, moderation and any communication with students or guardians.
          Aetrix does not make the final educational decision and does not issue official
          results.
        </p>
        <p>
          You must ensure that unapproved output is labelled as provisional, and that no student,
          parent or external body is told that an Aetrix mark is official or final unless a
          responsible human has reviewed and approved it.
        </p>
      </LegalSection>

      <LegalSection id="ip" number="12" title="Intellectual property">
        <p>
          The Aetrix software, interface, design, text, prompts, documentation and branding are
          owned by the operator or its licensors and are protected by intellectual property laws.
          These terms give you a limited, revocable, non-exclusive, non-transferable right to use
          the service for its intended purpose during the pilot. They do not transfer ownership
          of Aetrix or give you the right to copy, modify, distribute, resell or create a
          competing service from it.
        </p>
        <p>
          Examination papers, mark schemes and other third-party material belong to their
          respective owners, and uploading them does not change that. Google, Gemini, Supabase,
          Cloudflare, Tailscale and other product names are the property of their owners; Aetrix
          does not claim endorsement by them. The{' '}
          <Link to={LEGAL_DOCUMENTS.copyright.path}>Intellectual Property and Copyright
          Policy</Link> explains reporting and takedown.
        </p>
        <p>
          If you send feedback or suggestions, you permit the operator to use them to improve the
          service without a separate payment or obligation.
        </p>
      </LegalSection>

      <LegalSection id="content-licence" number="13" title="Your content and processing permissions">
        <p>
          You retain ownership of the content you upload. To operate the service, you give the
          operator a limited licence to host, store, copy, render, transmit, process, display
          within your workspace, and create derived marking records from that content, and to
          transmit it to the providers described in the Privacy Policy. The licence is limited to
          operating, securing, supporting and auditing the service, and ends when the content is
          deleted, subject to backups, audit records and legal obligations.
        </p>
        <p>
          Aetrix does not use your workspace content to train its own models and does not sell
          it. The AI provider processes content under its own terms; Aetrix cannot promise that
          the provider will not retain or use it in ways permitted by those terms. Do not upload
          content you are not prepared to send to that provider.
        </p>
        <p>
          You represent that you have the rights, consents and authorisations needed to grant
          this licence and to permit the processing described in the Privacy Policy.
        </p>
      </LegalSection>

      <LegalSection id="third-parties" number="14" title="Third-party services">
        <p>
          Aetrix relies on third-party services, including Supabase (authentication and
          database), Google (OAuth, Classroom and Gemini), Cloudflare (hosting and network
          security), and Tailscale (network tunnel). Those services are governed by their own
          terms and privacy policies. Aetrix does not control them and is not responsible for
          their availability, security or data-handling practices.
        </p>
        <p>
          Links to third-party sites are provided for convenience and do not imply endorsement.
          You are responsible for reviewing the terms that apply to any third-party service you
          use.
        </p>
      </LegalSection>

      <LegalSection id="availability" number="15" title="Availability and service interruptions">
        <p>
          Aetrix is a pre-release pilot provided on an “as available” basis. There is no
          service-level agreement and no guarantee of uptime, availability or continuity. The
          service may be interrupted by maintenance, model or provider outages, network or tunnel
          failures, host failures, security incidents, or changes to the pilot.
        </p>
        <p>
          Because the engine and uploaded files are hosted on an operator-controlled machine
          reached through a private network tunnel, availability depends on that machine and
          connection. The pilot does not provide a tested disaster-recovery or export process.
          Keep your own copies of scripts, mark schemes and results, and do not use Aetrix as the
          only record of a student’s work.
        </p>
        <p>
          We may add, change, suspend or remove features during the pilot. We do not guarantee
          that data or features will be preserved across a change.
        </p>
      </LegalSection>

      <LegalSection id="fees" number="16" title="Fees, payment and refunds">
        <p>
          The pilot is provided without charge. Aetrix does not take payments, subscriptions or
          deposits in this build, so there is nothing to refund and no cancellation or billing
          policy applies. Do not send money to anyone claiming to sell Aetrix access.
        </p>
        <p>
          If paid plans are introduced, the price, billing terms, cancellation right and refund
          policy will be published before any charge is taken, and no payment will be requested
          under these terms.
        </p>
      </LegalSection>

      <LegalSection id="termination" number="17" title="Suspension and termination">
        <p>
          You may stop using Aetrix at any time. The workspace owner may remove members, and the
          operator may suspend or terminate an account, workspace or the pilot itself for breach
          of these terms, a security or legal risk, operational reasons, or the end of the pilot.
          Where practicable, we will give notice, but immediate suspension may be necessary to
          protect people or the service.
        </p>
        <p>
          On termination, access stops. Data is handled under the Privacy Policy and any separate
          agreement with the school. The pilot does not currently provide self-service export or
          deletion, so ask the operator about a copy before ending participation; the{' '}
          <Link to={LEGAL_DOCUMENTS['account-deletion'].path}>deletion and data requests page</Link>{' '}
          explains the process. Provisions that by their nature should survive termination —
          including ownership, disclaimers, liability limits and governing law — continue to
          apply.
        </p>
      </LegalSection>

      <LegalSection id="disclaimers" number="18" title="Disclaimers">
        <p>
          To the maximum extent permitted by law, Aetrix is provided “as is” and “as available”.
          The operator disclaims all express and implied warranties, including warranties of
          accuracy, completeness, fitness for a particular purpose, merchantability,
          non-infringement, uninterrupted operation and error-free operation.
        </p>
        <p>
          The operator does not warrant that AI output will be correct, consistent or suitable
          for any examination, moderation, appeal or high-stakes decision; that uploaded content
          will be preserved or recoverable; that the service will be available without
          interruption; or that the service complies with any particular law, examination rule or
          institutional policy. Aetrix is not endorsed by an examination board.
        </p>
        <p>
          Nothing in these terms excludes or limits any right or liability that cannot lawfully
          be excluded or limited.
        </p>
      </LegalSection>

      <LegalSection id="liability" number="19" title="Limitation of liability">
        <p>
          To the maximum extent permitted by law, the operator is not liable for indirect,
          incidental, special, consequential or punitive loss, or for loss of profits, revenue,
          goodwill, opportunity or data, arising from or connected with Aetrix. The operator is
          not liable for a decision made by a teacher, school, reviewer or other person in
          reliance on AI output, or for the acts of Google, Supabase, Cloudflare, Tailscale or
          another third party.
        </p>
        <p>
          To the maximum extent permitted by law, the operator’s total aggregate liability
          arising from or connected with these terms or the service is limited to{' '}
          <LegalPlaceholder>LIABILITY CAP — TO BE CONFIRMED BY COUNSEL</LegalPlaceholder>. The
          pilot is currently provided without charge. This cap has not been agreed and must be
          settled before the terms are treated as final.
        </p>
        <p>
          Nothing in these terms limits liability for fraud, wilful misconduct, death or personal
          injury caused by negligence, or any other liability that cannot lawfully be limited.
        </p>
      </LegalSection>

      <LegalSection id="indemnity" number="20" title="Indemnity">
        <p>
          These terms do not currently impose an indemnity on an individual user. Before real
          student data is processed at scale, the operator and the institution are expected to
          address indemnity, insurance and liability allocation in a separate institutional
          agreement.
        </p>
        <p>
          If an institutional agreement applies to your use, its indemnity terms apply instead of
          this section. Any indemnity that is added to these terms will be lawful in scope, will
          not require you to indemnify the operator for the operator’s own negligence or
          misconduct, and will be reviewed by counsel before it takes effect.
        </p>
      </LegalSection>

      <LegalSection id="changes" number="21" title="Changes to these terms">
        <p>
          We may update these terms as the pilot develops. The version and “Last updated” date
          will change. If a change is material, we will take reasonable steps to notify workspace
          administrators, for example by a notice on the site or by email to the account address
          on record. Continued use after the effective date means you accept the updated terms.
          If you do not agree, stop using the service and ask about deletion.
        </p>
      </LegalSection>

      <LegalSection id="law" number="22" title="Governing law and dispute resolution">
        <p>
          The operator’s legal circumstances have not been established, so no governing law or
          forum has been chosen. These terms are intended to be governed by the laws of{' '}
          <LegalPlaceholder>GOVERNING LAW — TO BE CONFIRMED</LegalPlaceholder>, and disputes are
          intended to be brought in the courts of{' '}
          <LegalPlaceholder>JURISDICTION — TO BE CONFIRMED</LegalPlaceholder>. This is an
          unresolved legal decision, not a final choice of law.
        </p>
        <p>
          Before starting proceedings, the parties should try in good faith to resolve the
          dispute through discussion and written notice to{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>. Nothing in this
          section prevents either party from seeking urgent protective relief or exercising a
          mandatory consumer right available in their local law.
        </p>
      </LegalSection>

      <LegalSection id="contact" number="23" title="Contact">
        <p>
          Questions about these terms, legal notices and complaints can be sent to{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>, or by post to{' '}
          <LegalPlaceholder>REGISTERED ADDRESS — TO BE CONFIRMED</LegalPlaceholder>.
        </p>
        <p>
          These terms are a responsible technical and product draft. They are not legal advice
          and should be reviewed by qualified counsel before they are relied on as final. The
          complete set of documents is in the <Link to="/legal">legal centre</Link>.
        </p>
      </LegalSection>
    </LegalPage>
  )
}
