import { Link, createFileRoute } from '@tanstack/react-router'
import {
  LegalPage,
  LegalPlaceholder,
  LegalSection,
  type LegalTocItem,
} from '../components/legal/LegalPage'
import { LEGAL_DOCUMENTS } from '../lib/legal'

const TOC: LegalTocItem[] = [
  { id: 'operator', label: 'Who operates Aetrix' },
  { id: 'scope', label: 'Scope of this policy' },
  { id: 'information', label: 'Information we collect' },
  { id: 'google', label: 'Google authentication and Classroom' },
  { id: 'educational-records', label: 'Educational records' },
  { id: 'uploads', label: 'Uploaded documents and images' },
  { id: 'legal-bases', label: 'Why we process it, and on what basis' },
  { id: 'ai', label: 'AI processing and providers' },
  { id: 'storage', label: 'Storage and infrastructure' },
  { id: 'sharing', label: 'Sharing and disclosure' },
  { id: 'cookies', label: 'Cookies and browser storage' },
  { id: 'retention', label: 'Retention' },
  { id: 'deletion', label: 'Deletion and requests' },
  { id: 'security', label: 'Security practices and limits' },
  { id: 'rights', label: 'Your rights' },
  { id: 'children', label: 'Children and student data' },
  { id: 'transfers', label: 'International transfers' },
  { id: 'automated', label: 'Automated decisions' },
  { id: 'changes', label: 'Changes to this policy' },
  { id: 'contact', label: 'Contact' },
]

export const Route = createFileRoute('/_marketing/privacy')({
  head: () => ({
    meta: [
      { title: 'Privacy Policy — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'How the pre-release Aetrix mathematics-marking pilot collects, uses, stores and shares account, workspace and student-script information, including Google sign-in and Gemini processing.',
      },
      { property: 'og:title', content: 'Privacy Policy — Aetrix V5.5' },
      { property: 'og:type', content: 'article' },
    ],
  }),
  component: PrivacyPolicy,
})

function PrivacyPolicy() {
  return (
    <LegalPage
      doc={LEGAL_DOCUMENTS.privacy}
      eyebrow="Privacy Policy"
      title="What Aetrix does with your information."
      lede="A plain-language account of the data the Aetrix pilot collects, why it is processed, where it is stored, and the limits of what this pre-release service can currently promise."
      toc={TOC}
    >
      <LegalSection id="operator" number="01" title="Who operates Aetrix">
        <p>
          Aetrix is a pre-release, invitation-only mathematics-marking service for Edexcel IGCSE
          4MA1. It is operated by{' '}
          <LegalPlaceholder>OPERATOR LEGAL ENTITY — TO BE CONFIRMED</LegalPlaceholder>, of{' '}
          <LegalPlaceholder>REGISTERED ADDRESS — TO BE CONFIRMED</LegalPlaceholder> (“Aetrix”,
          “we”, “us”).
        </p>
        <p>
          This policy describes the pilot service available through aetrix.pages.dev, the
          authenticated workspace, and the Aetrix application programming interface (API). It
          does not describe a general-availability product. Aetrix does not claim affiliation
          with, sponsorship by, or endorsement by Pearson Edexcel, Google, or any examination
          board.
        </p>
        <p>
          The operator’s legal identity and contact details have not yet been established in the
          project. They are shown as placeholders rather than invented. Until they are confirmed
          and this notice is removed, this policy is a pre-release draft.
        </p>
      </LegalSection>

      <LegalSection id="scope" number="02" title="Scope of this policy">
        <p>This policy applies to information processed when you:</p>
        <ul>
          <li>visit the public Aetrix website, including this page;</li>
          <li>sign in to or use an Aetrix workspace;</li>
          <li>upload scripts, mark schemes, blueprints or other teaching material;</li>
          <li>review, correct, approve or comment on marking results; or</li>
          <li>contact the operator about the pilot.</li>
        </ul>
        <p>
          It does not apply to third-party websites or services, including Google, Supabase,
          Cloudflare, Tailscale or your school’s own systems. Those services have their own
          privacy notices. If your school or employer uses Aetrix, its notice and policies may
          also apply to your information.
        </p>
        <p>
          Aetrix is a pilot. Features, providers and data flows may change as the service
          develops. Material changes to this policy are described in section 19.
        </p>
      </LegalSection>

      <LegalSection id="information" number="03" title="Information we collect">
        <p>
          We collect the information needed to operate an invitation-only marking workspace. We
          do not operate advertising or behavioural-tracking services, and we do not sell
          personal information.
        </p>

        <div className="legal__table-wrap">
          <table className="legal__table">
            <caption className="sr-only">
              Categories of information processed by Aetrix, with examples and sources
            </caption>
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col">Examples</th>
                <th scope="col">Where it comes from</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Account and workspace</th>
                <td>
                  Google account identifier, email address, display name, account role;
                  workspace name and identifier; invitations and their status.
                </td>
                <td>Google sign-in and workspace administrators.</td>
              </tr>
              <tr>
                <th scope="row">Educational records</th>
                <td>
                  Exam and assignment names; mark schemes and blueprints; class and year group; a
                  student reference and optional display name; submissions; question-level
                  answers, working summaries, marks, confidence, evidence, review decisions and
                  approvals.
                </td>
                <td>
                  Teachers and workspace administrators; generated by the marking service;
                  entered by human reviewers.
                </td>
              </tr>
              <tr>
                <th scope="row">Uploaded files</th>
                <td>
                  PDF, PNG and JPEG files up to 25 MiB and up to 80 pages; the original filename,
                  MIME type, size, checksum and page count; rendered page images and extracted
                  text excerpts.
                </td>
                <td>Teachers and workspace administrators.</td>
              </tr>
              <tr>
                <th scope="row">Operational records</th>
                <td>
                  Request, tenant and job identifiers; timestamps; action and audit events; HTTP
                  status and error codes; provider token counts and estimated cost; service logs.
                </td>
                <td>
                  Generated by the service. Network providers may also process standard request
                  metadata such as IP address and user agent.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p>
          An Aetrix workspace also contains a performance-analytics view computed from marking
          records. That is a product feature, not a third-party marketing or behavioural-analytics
          service.
        </p>
      </LegalSection>

      <LegalSection id="google" number="04" title="Google authentication and Classroom access">
        <p>
          Sign-in is brokered by Supabase Auth using Google OAuth with the PKCE flow. When you
          choose “Continue with Google”, Google asks you to select an account and confirm access.
          Aetrix requests the basic profile and email information needed to identify your
          account. Sign-in does not request access to Gmail, Google Drive, Google Classroom,
          Google Calendar or other Google content.
        </p>
        <p>From Google we receive:</p>
        <ul>
          <li>a Google account identifier (the subject identifier);</li>
          <li>your email address;</li>
          <li>your name; and</li>
          <li>a profile-image URL, if your Google account has one.</li>
        </ul>
        <p>
          The Aetrix engine stores the account identifier, email address and display name,
          together with your workspace role. The profile-image URL is available to the browser
          session through Supabase; it is not stored in the Aetrix database. Google sign-in
          tokens are handled by Supabase Auth and are not written into the Aetrix application
          database by the frontend.
        </p>
        <p>
          Separately, a workspace owner or administrator may connect Google Classroom so the
          workspace can list its courses. That authorisation is held by the Aetrix engine, not by
          Supabase: the access and refresh tokens are encrypted with the engine’s credential key,
          are never returned to the browser, and are deleted when Google rejects the grant or the
          workspace disconnects it. The only permission requested is read-only access to course
          names and sections (<code>classroom.courses.readonly</code>). Coursework, submissions,
          student rosters and grades are not read, and nothing is written to Classroom.
        </p>
        <p>
          The browser stores the Supabase session in local storage under the key{' '}
          <code>aetrix:auth</code> so you remain signed in across refreshes. The browser build
          contains only Supabase’s publishable (anonymous) key; the service-role key is not
          shipped to the browser. If email-and-password sign-in is enabled for an account,
          Supabase Auth handles the password; Aetrix does not store the password itself. The{' '}
          <Link to={LEGAL_DOCUMENTS.cookies.path}>Cookie Policy</Link> lists every key the browser
          stores.
        </p>
        <p>
          Google’s own handling of your Google account information is governed by Google’s
          privacy policy and the permissions you grant there. You can revoke Aetrix’s access from
          your Google account settings, though doing so may prevent you from signing in.
        </p>
      </LegalSection>

      <LegalSection id="educational-records" number="05" title="Educational records and student submissions">
        <p>
          Aetrix is designed for teachers and authorised workspace administrators to upload
          examination scripts and related teaching material. The workspace owner or teacher
          decides what is uploaded, why it is uploaded and who can see it. Aetrix processes that
          content on their instructions. Whether Aetrix is a “processor”, “controller” or
          something else for a particular deployment depends on the contract with the school or
          institution and has not been finally determined for the pilot.
        </p>
        <p>Teachers, schools and workspace administrators are responsible for:</p>
        <ul>
          <li>
            ensuring they have the authority, notices and consents needed to upload student work
            and personal information;
          </li>
          <li>
            telling students and guardians what is uploaded and who can see it, where the law or
            school policy requires that;
          </li>
          <li>
            uploading only what is necessary for marking, and avoiding unnecessary names, contact
            details, health information or other sensitive identifiers;
          </li>
          <li>using a pseudonymous student reference where possible instead of a full name; and</li>
          <li>
            responding to student or guardian requests in the first instance, unless the school
            asks Aetrix to handle them.
          </li>
        </ul>
        <p>
          Students do not have Aetrix accounts in the pilot. A student entry is a roster record
          containing a student reference and an optional display name. The service does not
          verify a student’s identity, age or consent.
        </p>
      </LegalSection>

      <LegalSection id="uploads" number="06" title="Uploaded documents and images">
        <p>
          The pilot accepts PDF, PNG and JPEG files up to 25 MiB, with a configured maximum of 80
          pages per document. The service checks the declared type and size, stores the original
          file, renders page images for marking, and records extracted text excerpts, checksums
          and page counts.
        </p>
        <p>
          Uploaded scripts may contain a student’s name, handwriting, candidate number, answers,
          working, teacher annotations, marks or grades. Aetrix treats these as educational
          records and does not publish them. Files are stored on a filesystem controlled by the
          operator, not in a public bucket, and page images and documents are served through
          authenticated API routes rather than public URLs.
        </p>
        <p>
          The pilot does not currently scan uploads for malware. Do not upload unrelated
          documents, executables or material you are not authorised to process. See section 14
          for the security limitations of the pilot.
        </p>
      </LegalSection>

      <LegalSection id="legal-bases" number="07" title="Why we process it, and on what basis">
        <p>
          The table below states the purpose of each processing activity and the legal basis the
          operator relies on where the EU or UK GDPR applies. Where another law applies, the
          equivalent basis must still be identified by the operator; this table is not a claim
          that either regime governs the pilot.
        </p>

        <div className="legal__table-wrap">
          <table className="legal__table">
            <caption className="sr-only">
              Processing purposes and the legal basis relied on where EU or UK GDPR applies
            </caption>
            <thead>
              <tr>
                <th scope="col">Purpose</th>
                <th scope="col">Information involved</th>
                <th scope="col">Basis relied on</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Provide the workspace and marking</th>
                <td>Account, workspace, uploads, results and approvals.</td>
                <td>
                  Performance of the contract with the account holder or institution, or steps
                  taken at its request.
                </td>
              </tr>
              <tr>
                <th scope="row">Authenticate and secure access</th>
                <td>Sign-in identity, session, role, request and audit records.</td>
                <td>
                  Legitimate interests in keeping the service and its records secure; legal
                  obligation for records that must be kept. The balancing assessment has not been
                  written down and is an open item.
                </td>
              </tr>
              <tr>
                <th scope="row">Send material to the AI provider</th>
                <td>Page images, prompt, mark scheme and blueprint content.</td>
                <td>
                  Performance of the contract, on the institution’s instructions; the provider
                  processes the content to return the marking output.
                </td>
              </tr>
              <tr>
                <th scope="row">Resolve a request, complaint or dispute</th>
                <td>Contact details and the records concerned.</td>
                <td>
                  Legal obligation where a right must be answered; otherwise legitimate interests
                  in resolving the matter.
                </td>
              </tr>
              <tr>
                <th scope="row">Keep audit and usage records</th>
                <td>Approvals, administrative actions, provider usage and cost.</td>
                <td>
                  Legitimate interests in accountability, and legal obligation where retention is
                  required.
                </td>
              </tr>
              <tr>
                <th scope="row">Marketing email</th>
                <td>Email address.</td>
                <td>
                  Not used. No marketing email is sent in this build. If it is introduced, it will
                  rely on separate, explicit, non-preselected consent that can be withdrawn.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p>
          Consent is not the basis for the core service: an account cannot function without the
          processing described above, and acknowledging the privacy notice on the sign-in page is
          not consent to optional processing. Where special-category data is involved — for
          example, health information visible on a script — the pilot does not seek it and the
          institution must identify its own condition for processing it.
        </p>
      </LegalSection>

      <LegalSection id="ai" number="08" title="AI processing and third-party providers">
        <p>
          When a marking job runs, Aetrix sends the relevant page images and the associated
          prompt, mark-scheme and blueprint content to Google’s Gemini API at{' '}
          <code>generativelanguage.googleapis.com</code>. The pilot is configured with{' '}
          <code>gemini-3.6-flash</code> as the primary model and{' '}
          <code>gemini-3.1-pro-preview</code> for review. The live provider is currently enabled
          in the pilot environment, so uploaded scripts can be sent to Google when a teacher
          starts marking.
        </p>
        <p>
          Google processes that content under its own terms and privacy policy. Aetrix has not
          independently verified Google’s retention period for this content, whether Google uses
          it to improve or train models, or whether Google deletes it on a particular schedule.
          This policy therefore does not promise that Google never retains, reviews or uses the
          content. The operator must obtain and document the relevant contractual commitments
          before representing otherwise.
        </p>
        <p>
          Aetrix stores the outputs of the marking process: per-question answers, working
          summaries, awarded marks, confidence values, concerns, evidence, verification records,
          review decisions and approvals. These outputs are provisional until a human reviewer
          resolves every flagged question and an authorised approver approves the result. The
          gradebook records whether a result is approved.
        </p>
        <p>
          Aetrix does not use workspace content to train its own models and does not sell it. The
          service may change models or providers; if a change materially affects how content is
          processed, this policy and the service will be updated. AI marking can be unavailable,
          incomplete or wrong; it is not an official examination result. The{' '}
          <Link to={LEGAL_DOCUMENTS['ai-disclosure'].path}>AI Use Disclosure</Link> explains the
          failure modes and the human-review requirement.
        </p>
      </LegalSection>

      <LegalSection id="storage" number="09" title="Data storage and infrastructure providers">
        <p>
          The pilot uses the following service providers. They process information on the
          operator’s behalf or as independent providers under their own terms.
        </p>

        <div className="legal__table-wrap">
          <table className="legal__table">
            <caption className="sr-only">
              Infrastructure providers used by the Aetrix pilot and the information they process
            </caption>
            <thead>
              <tr>
                <th scope="col">Provider</th>
                <th scope="col">Purpose</th>
                <th scope="col">Information involved</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Supabase</th>
                <td>Authentication and PostgreSQL database.</td>
                <td>
                  Account identity, email, display name, workspace membership, educational
                  records, marking outputs, audit and usage records. The database for this pilot
                  is hosted in the AWS eu-west-2 region; Supabase may process data in other
                  locations.
                </td>
              </tr>
              <tr>
                <th scope="row">Google</th>
                <td>Google OAuth sign-in, optional Classroom course listing, and Gemini API marking.</td>
                <td>
                  Basic Google profile information for sign-in; read-only course names for
                  Classroom; page images, prompts, mark schemes and blueprints for marking.
                </td>
              </tr>
              <tr>
                <th scope="row">Cloudflare</th>
                <td>Static site hosting, content delivery and network security.</td>
                <td>Public site requests and standard request metadata.</td>
              </tr>
              <tr>
                <th scope="row">Tailscale</th>
                <td>Private network tunnel that exposes the engine API.</td>
                <td>Network connection metadata for API requests.</td>
              </tr>
              <tr>
                <th scope="row">Operator-controlled host</th>
                <td>Local filesystem storage for uploaded documents and page images.</td>
                <td>
                  Original files, rendered page images and derived text excerpts, under the
                  configured storage directory.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p>
          The pilot does not use Supabase Storage, Cloudflare R2, Cloudflare D1 or a queue service
          for application data. Uploaded files are stored on the operator’s filesystem. The
          application database is PostgreSQL accessed directly by the engine.
        </p>
      </LegalSection>

      <LegalSection id="sharing" number="10" title="Data sharing and disclosure">
        <p>
          We do not sell, rent or trade personal information. We do not share it for advertising.
          In the pilot, information may be shared only:
        </p>
        <ul>
          <li>
            with members of your own workspace, according to their role and the permissions the
            service enforces;
          </li>
          <li>
            with the infrastructure and AI providers listed in section 9, to the extent needed to
            provide the service;
          </li>
          <li>
            with the operator and authorised administrators who need access to operate, secure,
            support or investigate the service;
          </li>
          <li>
            when required by law, legal process or a regulatory request, or when necessary to
            protect the safety, rights or security of a person or the service; or
          </li>
          <li>with your direction or consent.</li>
        </ul>
        <p>
          Aetrix does not share one workspace’s student records with another workspace.
          Platform-level administration is limited to the operator accounts needed to run the
          service; there is no consented, time-limited support-access feature in the pilot. Do not
          upload information you would not want the operator’s authorised personnel to see while
          resolving a support or security issue.
        </p>
      </LegalSection>

      <LegalSection id="cookies" number="11" title="Cookies and browser storage">
        <p>
          Aetrix sets no cookies. The browser does store a small number of first-party values to
          keep you signed in and remember display preferences, including the session under{' '}
          <code>aetrix:auth</code>. There is no advertising or analytics script, so there is no
          consent banner: the storage is limited to what the service needs.
        </p>
        <p>
          The <Link to={LEGAL_DOCUMENTS.cookies.path}>Cookie Policy</Link> lists every key, its
          purpose and its lifetime, and explains how to clear it.
        </p>
      </LegalSection>

      <LegalSection id="retention" number="12" title="Data retention">
        <p>
          Aetrix does not currently enforce an automated retention schedule. Workspace,
          educational, file and marking records are retained while the workspace is active and
          for as long as needed to operate and audit the pilot. Audit events and provider-usage
          records are append-only by design.
        </p>
        <p>
          Uploaded files remain on the operator’s filesystem until they are deleted through an
          operator process. Supabase maintains backups of the database under its own terms; the
          pilot does not have a tested restore or expiry schedule for those backups. Cloudflare,
          Supabase, Google and Tailscale may retain their own logs for periods set by their terms.
        </p>
        <p>
          Because no fixed retention periods have been approved, this policy does not promise that
          any category of information is deleted after a specific number of days. A retention and
          legal-hold policy must be established before wider use.
        </p>
      </LegalSection>

      <LegalSection id="deletion" number="13" title="Deletion and data requests">
        <p>
          The pilot does not provide self-service account deletion or data export. The{' '}
          <Link to={LEGAL_DOCUMENTS['account-deletion'].path}>
            account deletion and data requests page
          </Link>{' '}
          explains how to ask, what can be removed, and what may remain in audit records, backups
          and provider logs. Requests go to{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder> once the operator
          publishes a monitored address.
        </p>
        <p>
          Deletion is performed by the operator. Live database records and stored files can be
          removed, but some records may remain in append-only audit and usage logs, database
          backups or provider logs. There is no guaranteed deletion deadline in the pilot, and
          this policy does not promise one. If you need a copy of your data, request it before
          asking for deletion or ending your participation.
        </p>
      </LegalSection>

      <LegalSection id="security" number="14" title="Security practices and limitations">
        <p>The pilot implements the following controls, verified in the source code:</p>
        <ul>
          <li>HTTPS for the public site, the API, Supabase and Google;</li>
          <li>
            verification of Supabase-issued JSON Web Tokens, with the tenant resolved from the
            verified claim rather than from a request body;
          </li>
          <li>server-side tenant scoping and role checks on workspace and administrative routes;</li>
          <li>provider credentials encrypted with Fernet and never returned to the browser;</li>
          <li>
            upload type and size checks, page and pixel limits, checksums, and a path-traversal
            guard on local storage; and
          </li>
          <li>
            structured logs that redact bearer tokens, API keys, JSON Web Tokens, long hexadecimal
            values and sensitive field names, and that do not record request bodies or prompts.
          </li>
        </ul>
        <p>The pilot also has material limitations:</p>
        <ul>
          <li>uploads are not scanned for malware;</li>
          <li>there is no application-level rate limiting;</li>
          <li>
            database row-level security is not relied on; tenant isolation is enforced by the
            application;
          </li>
          <li>stored files are not independently encrypted by Aetrix and rely on the host’s disk controls;</li>
          <li>there has been no independent penetration test, security certification or audit;</li>
          <li>
            multi-factor authentication is not enforced by Aetrix and depends on the user’s Google
            account;
          </li>
          <li>
            monitoring, incident response and disaster recovery are operated on a best-effort
            pilot basis, not 24/7; and
          </li>
          <li>
            the service is operated by a small team, so access to production systems is not
            separated across many people.
          </li>
        </ul>
        <p>
          No method of transmission or storage is completely secure. Aetrix does not claim
          compliance with ISO 27001, SOC 2 or any other security standard. The{' '}
          <Link to={LEGAL_DOCUMENTS.security.path}>Security and Vulnerability Disclosure
          Policy</Link> covers reporting a vulnerability and the incident position.
        </p>
      </LegalSection>

      <LegalSection id="rights" number="15" title="Your rights">
        <p>
          Depending on where you live and which law applies, you may have rights to access,
          correct, delete, restrict or object to the processing of your personal information, or
          to receive a portable copy. These rights are not absolute and may be limited by law or
          by the rights of others.
        </p>
        <p>
          To make a request, contact{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>. Please identify
          the workspace and the information concerned. We may ask for proof of identity and, for
          student or workspace data, proof that you are authorised to act. We do not currently
          charge for requests. Response times depend on the applicable law and the complexity of
          the request; the pilot aims to respond promptly but does not promise a fixed statutory
          deadline.
        </p>
        <p>
          Students and guardians should contact the school or teacher that uploaded the
          information first, because the school usually controls the workspace and can resolve the
          request faster. If you are not satisfied with our response, you may have the right to
          complain to a data-protection authority in your country. The competent authority has not
          been determined for this operator; this is recorded as an open item.
        </p>
        <p>
          This section describes rights that may be available. It is not a claim that Aetrix is
          subject to, or compliant with, the UK GDPR, EU GDPR, Egypt’s Personal Data Protection Law
          No. 151 of 2020, FERPA, COPPA or any other specific regime.
        </p>
      </LegalSection>

      <LegalSection id="children" number="16" title="Children and student data">
        <p>
          Aetrix is a professional and institutional tool, not a child-directed service. Accounts
          are created by invitation for teachers, reviewers and administrators; students do not
          sign in and Aetrix does not create student accounts. Aetrix does not verify the age of
          users or students.
        </p>
        <p>
          Student scripts and roster entries are uploaded by teachers or schools. Those
          organisations are responsible for deciding whether they may upload a child’s
          information, for providing any required notices and obtaining any required consents or
          authorisations, and for complying with their own child-protection and education-records
          obligations. Do not upload a child’s information if you do not have the authority to do
          so.
        </p>
        <p>
          If you believe a child’s information has been uploaded without proper authority, contact{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder> and we will
          investigate. Aetrix does not claim compliance with COPPA, FERPA, the UK Children’s Code
          or any other children’s-data regime; the operator must establish the applicable
          obligations before wider deployment.
        </p>
      </LegalSection>

      <LegalSection id="transfers" number="17" title="International data transfers">
        <p>
          The providers used by the pilot may process information outside the country where you
          live. The Supabase database for this pilot is hosted in the AWS eu-west-2 region, but
          Supabase, Google, Cloudflare and Tailscale operate global infrastructure and may process
          data in other countries. AI prompts and page images are sent to Google’s Gemini API,
          which may process them outside your country.
        </p>
        <p>
          The operator has not yet completed a transfer assessment, put in place standard
          contractual clauses or another transfer mechanism, or verified the safeguards used by
          each provider for this pilot. This policy therefore does not promise a particular
          transfer mechanism or adequacy finding. This is an open item that must be resolved before
          the service is offered more widely.
        </p>
      </LegalSection>

      <LegalSection id="automated" number="18" title="Automated decisions">
        <p>
          Aetrix proposes marks and flags uncertainty, but it does not make the final decision
          about a student. A human reviewer must resolve every flag, and an authorised approver
          must approve the result before it is treated as final. The service therefore is not
          intended to produce solely automated decisions with legal or similarly significant
          effects.
        </p>
        <p>
          An institution that uses Aetrix output in a significant decision about a student is
          responsible for that decision and for any human review, transparency or explanation it
          requires. The <Link to={LEGAL_DOCUMENTS['ai-disclosure'].path}>AI Use Disclosure</Link>{' '}
          explains the limits of the output in more detail.
        </p>
      </LegalSection>

      <LegalSection id="changes" number="19" title="Changes to this policy">
        <p>
          We may update this policy as the pilot changes. The version and “Last updated” date at
          the top of the page will change. If a change materially affects how personal information
          is processed, we will take reasonable steps to notify workspace administrators, for
          example by a notice on the site or by email to the account address on record.
        </p>
        <p>
          Because this is a pre-release service, the policy may change frequently. If you do not
          agree with an updated policy, you should stop using the service and ask the workspace
          owner or operator about deletion.
        </p>
      </LegalSection>

      <LegalSection id="contact" number="20" title="Contact">
        <p>
          Questions, requests and complaints about privacy can be sent to{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>, or by post to{' '}
          <LegalPlaceholder>REGISTERED ADDRESS — TO BE CONFIRMED</LegalPlaceholder>.
        </p>
        <p>
          A data-protection contact, an EU or UK representative (if one is required) and a
          supervisory authority have not been appointed or confirmed. These are recorded as
          unresolved legal decisions in the project’s legal review notes.
        </p>
        <p>
          This policy is a responsible technical and product draft. It is not legal advice and
          should be reviewed by qualified counsel before it is relied on as final. The complete set
          of documents is in the <Link to="/legal">legal centre</Link>.
        </p>
      </LegalSection>
    </LegalPage>
  )
}
