import { Link, createFileRoute } from '@tanstack/react-router'
import {
  LegalPage,
  LegalPlaceholder,
  LegalSection,
  type LegalTocItem,
} from '../components/legal/LegalPage'
import { LEGAL_DOCUMENTS } from '../lib/legal'

const TOC: LegalTocItem[] = [
  { id: 'capability', label: 'What the pilot supports today' },
  { id: 'requesting', label: 'How to make a request' },
  { id: 'deleted', label: 'What can be deleted' },
  { id: 'retained', label: 'What may remain' },
  { id: 'timing', label: 'Timing' },
  { id: 'school', label: 'Data controlled by a school' },
  { id: 'correction', label: 'Correcting information' },
  { id: 'export', label: 'Getting a copy' },
  { id: 'browser', label: 'Clearing this device' },
  { id: 'contact', label: 'Contact' },
]

export const Route = createFileRoute('/_marketing/account-deletion')({
  head: () => ({
    meta: [
      { title: 'Account Deletion and Data Requests — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'How to request access, correction or deletion of Aetrix account and workspace data while self-service controls do not exist, and what the pilot can and cannot remove.',
      },
      { property: 'og:title', content: 'Account Deletion and Data Requests — Aetrix V5.5' },
      { property: 'og:type', content: 'article' },
    ],
  }),
  component: AccountDeletion,
})

function AccountDeletion() {
  return (
    <LegalPage
      doc={LEGAL_DOCUMENTS['account-deletion']}
      eyebrow="Deletion and data requests"
      title="Asking for your data, a correction, or deletion."
      lede="There is no self-service delete button in this build. This page explains the request process that does exist, who has to authorise it, and what deletion can and cannot reach."
      toc={TOC}
    >
      <LegalSection id="capability" number="01" title="What the pilot supports today">
        <p>
          The authenticated application has no account-deletion, workspace-deletion, data-export
          or correction screen. No button on this site claims to complete a request, because
          none does; a control that appeared to work while only sending an email would mislead
          the person relying on it.
        </p>
        <p>
          Requests are handled manually by the operator. Some of them depend on the workspace
          owner or the school, because the workspace, not the individual account, is usually
          the record holder.
        </p>
        <p>
          Signing out is separate from deletion. It removes the session from this browser and
          leaves the account and workspace records in place; see section 9.
        </p>
      </LegalSection>

      <LegalSection id="requesting" number="02" title="How to make a request">
        <p>
          Send the request to <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>.
          A monitored address has not been published in this build; until one is, raise the
          request with your workspace owner, who can pass it to the operator.
        </p>
        <p>Please include:</p>
        <ul>
          <li>the email address and, if known, the user id of the account concerned;</li>
          <li>the workspace name or identifier, if the request concerns workspace data;</li>
          <li>whether you want access, correction, deletion, or a combination;</li>
          <li>
            the records concerned, if the request is limited — an assignment, submission, job
            or date range helps;
          </li>
          <li>
            your relationship to the data: account holder, workspace owner, school
            representative, student or guardian; and
          </li>
          <li>any authority document, if you are acting for someone else.</li>
        </ul>
        <p>
          Do not send student scripts or identity documents in the first message. The operator
          will ask for the minimum needed to verify identity and authority.
        </p>
      </LegalSection>

      <LegalSection id="deleted" number="03" title="What can be deleted">
        <p>
          The operator can remove live records: the account row and its workspace membership,
          and, where the request and authority support it, submissions, page images, extracted
          text, question results, review decisions, approvals and the stored files behind them.
          A whole workspace can be closed where the workspace owner or school instructs it.
        </p>
        <p>
          Deletion is performed against the production database and the file store directly.
          It is not a soft-delete flag that leaves the content readable.
        </p>
      </LegalSection>

      <LegalSection id="retained" number="04" title="What may remain">
        <p>Deletion cannot currently reach everything:</p>
        <ul>
          <li>
            <strong>Append-only audit and usage records</strong> — approvals, administrative
            actions and provider usage are written as an audit trail. Removing the audit trail
            would defeat its purpose, so entries may be retained with identifiers that no
            longer resolve to a live account.
          </li>
          <li>
            <strong>Backups</strong> — the database vendor keeps backups under its own terms.
            The pilot has no tested process for removing one record from a backup, and no
            approved backup-expiry schedule.
          </li>
          <li>
            <strong>Provider logs</strong> — Cloudflare, Supabase, Google and Tailscale keep
            their own request and system logs for periods they set. Aetrix cannot delete those.
          </li>
          <li>
            <strong>AI provider content</strong> — material sent for marking is processed under
            the provider’s terms. Aetrix has not recorded a deletion mechanism for it and cannot
            promise that the provider deletes it on request.
          </li>
          <li>
            <strong>Records the operator must keep</strong> — where law, a court order or a
            school’s instruction requires retention, that obligation prevails over the request
            and the requester will be told which category applies.
          </li>
        </ul>
      </LegalSection>

      <LegalSection id="timing" number="05" title="Timing">
        <p>
          The pilot promises no fixed deletion deadline and no fixed response time. There is no
          automated retention job and no request-tracking system, so each request is scheduled
          by hand. The operator will confirm when the work is done, and will say what could not
          be removed. If you need a deadline you can rely on, obtain it in writing from the
          operator or the school before uploading material.
        </p>
        <p>
          This is deliberate: a published “we delete within 30 days” promise would be false
          while backups and append-only records exist without an expiry process.
        </p>
      </LegalSection>

      <LegalSection id="school" number="06" title="Data controlled by a school">
        <p>
          Where Aetrix holds a script on a school’s instructions, the school decides what
          happens to it. Students and guardians should ask the school or teacher first: it can
          usually act faster, and it may have its own obligations about retaining assessment
          records for moderation or appeals.
        </p>
        <p>
          The operator will not delete a workspace’s records on an individual’s request where
          the school is the controller, unless the school authorises it or the law requires it.
          Whether Aetrix is a controller or a processor for a given deployment has not been
          finally determined; that is an open item in the legal review.
        </p>
      </LegalSection>

      <LegalSection id="correction" number="07" title="Correcting information">
        <p>
          Account details such as display name and email come from the Google or Supabase
          account used to sign in; correcting them at the identity provider corrects them here
          on the next sign-in. Workspace, class and student-reference records are edited by the
          workspace owner.
        </p>
        <p>
          A marking record should not be silently rewritten. The review and override mechanism
          exists so a wrong mark is corrected with an actor, a reason and a time, and the
          approval record reflects who approved the change. Where information is factually
          wrong rather than a marking judgement, ask the workspace owner to correct it and tell
          the operator if that is not possible.
        </p>
      </LegalSection>

      <LegalSection id="export" number="08" title="Getting a copy">
        <p>
          There is no self-service export and no export package format. Ask the operator before
          requesting deletion if you need a copy, because deletion may leave nothing to copy
          from once it is done. The operator can provide the records it holds in a readable
          form, subject to identity and authority checks and to the rights of other people in
          the same records.
        </p>
      </LegalSection>

      <LegalSection id="browser" number="09" title="Clearing this device">
        <p>
          Signing out from the account menu or the settings page removes the session and the
          sign-in flow keys from this browser. The theme, the navigation preference and the list
          of accounts seen on this device remain until you clear site data; the{' '}
          <Link to={LEGAL_DOCUMENTS.cookies.path}>Cookie Policy</Link> lists every key and how to
          remove it.
        </p>
        <p>
          Clearing browser data is not a deletion request. It changes nothing in the service.
        </p>
      </LegalSection>

      <LegalSection id="contact" number="10" title="Contact">
        <p>
          Requests and questions go to{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>. The{' '}
          <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link> explains the data
          concerned and the rights that may be available; the{' '}
          <Link to="/legal">legal centre</Link> lists every document.
        </p>
        <p>
          This page is a technical and product draft. It is not legal advice and should be
          reviewed by qualified counsel before it is treated as final.
        </p>
      </LegalSection>
    </LegalPage>
  )
}
