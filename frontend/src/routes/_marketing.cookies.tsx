import { Link, createFileRoute } from '@tanstack/react-router'
import {
  LegalPage,
  LegalPlaceholder,
  LegalSection,
  type LegalTocItem,
} from '../components/legal/LegalPage'
import { LEGAL_DOCUMENTS } from '../lib/legal'

const TOC: LegalTocItem[] = [
  { id: 'summary', label: 'Summary' },
  { id: 'what', label: 'Cookies and similar technologies' },
  { id: 'cookies', label: 'Cookies Aetrix sets' },
  { id: 'storage', label: 'Browser storage used instead' },
  { id: 'third-parties', label: 'Third-party cookies' },
  { id: 'analytics', label: 'Analytics and advertising' },
  { id: 'consent', label: 'Consent and why there is no banner' },
  { id: 'retention', label: 'How long storage lasts' },
  { id: 'managing', label: 'Managing and clearing storage' },
  { id: 'changes', label: 'Changes to this policy' },
  { id: 'contact', label: 'Contact' },
]

export const Route = createFileRoute('/_marketing/cookies')({
  head: () => ({
    meta: [
      { title: 'Cookie Policy — Aetrix V5.5' },
      {
        name: 'description',
        content:
          'Aetrix sets no cookies. This page lists every browser-storage key the site does use, why it exists, how long it lasts and how to remove it.',
      },
      { property: 'og:title', content: 'Cookie Policy — Aetrix V5.5' },
      { property: 'og:type', content: 'article' },
    ],
  }),
  component: CookiePolicy,
})

function CookiePolicy() {
  return (
    <LegalPage
      doc={LEGAL_DOCUMENTS.cookies}
      eyebrow="Cookie Policy"
      title="No cookies. Here is exactly what the browser stores."
      lede="Aetrix writes no cookies at all. It does keep a small number of values in local and session storage to keep you signed in and remember your display preferences. This page lists every one of them."
      toc={TOC}
    >
      <LegalSection id="summary" number="01" title="Summary">
        <p>
          The public site and the authenticated workspace set no cookies. The application
          never calls <code>document.cookie</code>. Nothing is stored for advertising, and no
          third-party analytics, tag manager, pixel or session-recording script is loaded.
        </p>
        <p>
          What the browser does store is listed in section 4: a Supabase session so you stay
          signed in, the identity fields of accounts you have already used on this device,
          your theme choice, and a collapsed-navigation preference. Every key is first-party,
          readable only by this origin, and none is sent automatically with requests the way a
          cookie is.
        </p>
      </LegalSection>

      <LegalSection id="what" number="02" title="Cookies and similar technologies">
        <p>
          A cookie is a small value a site asks the browser to store and to send back with
          later requests. Local storage and session storage are similar in that they hold
          values for a site, but they are not sent with HTTP requests and are only read by
          scripts running on the site’s own origin. This policy covers both, because the
          privacy question — what is stored on your device and why — is the same.
        </p>
      </LegalSection>

      <LegalSection id="cookies" number="03" title="Cookies Aetrix sets">
        <p>
          None. There is no first-party cookie on the marketing pages, the sign-in page, the
          callback route or the authenticated workspace. Sign-in is a PKCE OAuth exchange
          brokered by Supabase Auth, and the resulting session is persisted through the
          storage adapter described below rather than in a cookie.
        </p>
      </LegalSection>

      <LegalSection id="storage" number="04" title="Browser storage used instead">
        <div className="legal__table-wrap">
          <table className="legal__table">
            <caption className="sr-only">
              Every browser-storage key written by the Aetrix frontend, with its purpose and
              lifetime
            </caption>
            <thead>
              <tr>
                <th scope="col">Key</th>
                <th scope="col">Store</th>
                <th scope="col">Purpose</th>
                <th scope="col">Lifetime</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">
                  <code>aetrix:auth</code>
                </th>
                <td>Local</td>
                <td>
                  The Supabase session — access and refresh token — so you remain signed in
                  across refreshes. Necessary for the service to work.
                </td>
                <td>Until sign-out, revocation, or the refresh token expires.</td>
              </tr>
              <tr>
                <th scope="row">
                  <code>aetrix:auth-accounts</code>
                </th>
                <td>Local</td>
                <td>
                  The identity only — user id, email, name, avatar URL — of up to five accounts
                  used on this device, so the account switcher can list them. It holds no
                  token or password.
                </td>
                <td>Until an account is forgotten or site data is cleared.</td>
              </tr>
              <tr>
                <th scope="row">
                  <code>aetrix:theme</code>
                </th>
                <td>Local</td>
                <td>Your light or dark theme choice.</td>
                <td>Until you change it or clear site data.</td>
              </tr>
              <tr>
                <th scope="row">
                  <code>aetrix:rail</code>
                </th>
                <td>Local</td>
                <td>Whether the navigation rail is collapsed, in the authenticated shell.</td>
                <td>Until you change it or clear site data.</td>
              </tr>
              <tr>
                <th scope="row">
                  <code>aetrix:platform-overview-changed-at</code>
                </th>
                <td>Local</td>
                <td>
                  A timestamp written only for platform-operator accounts, used to refresh the
                  platform overview in other tabs of the same browser.
                </td>
                <td>Until replaced or cleared.</td>
              </tr>
              <tr>
                <th scope="row">
                  <code>aetrix:auth-next</code>
                </th>
                <td>Session</td>
                <td>
                  The page you were trying to reach, so sign-in can return you there. It is
                  removed once it has been used.
                </td>
                <td>Until the tab closes or the value is consumed.</td>
              </tr>
              <tr>
                <th scope="row">
                  <code>aetrix:auth-add</code>
                </th>
                <td>Session</td>
                <td>
                  A marker for an in-progress “add another account” round trip, so the callback
                  can tell it apart from a fresh sign-in.
                </td>
                <td>Discarded after ten minutes or when the round trip finishes.</td>
              </tr>
              <tr>
                <th scope="row">
                  <code>aetrix:platform-overview-stale</code>
                </th>
                <td>Session</td>
                <td>
                  A one-shot flag telling another tab that the platform overview changed.
                </td>
                <td>Until consumed or the tab closes.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          Local-storage values persist until they are removed, so a value written months ago
          can still be present. Signing out clears the session and the flow keys; the theme
          and rail preferences remain until you change them. Clearing site data in your
          browser removes all of them.
        </p>
      </LegalSection>

      <LegalSection id="third-parties" number="05" title="Third-party cookies">
        <p>
          Aetrix does not embed third-party content that sets cookies. When you sign in with
          Google, your browser leaves this site for Google’s and Supabase’s own domains;
          any cookies set during that exchange belong to those services and are governed by
          their policies, not this one.
        </p>
        <p>
          Cloudflare serves the site and may process request metadata, including the IP
          address and user agent, for delivery, caching, abuse prevention and network
          security. Depending on how the Cloudflare zone is configured, its edge may set a
          security cookie that the application never reads. Cloudflare’s handling is governed
          by its own terms.
        </p>
      </LegalSection>

      <LegalSection id="analytics" number="06" title="Analytics and advertising">
        <p>
          There are none. This build contains no Google Analytics, no advertising pixel, no
          heat-map or session-replay script and no A/B testing service. The authenticated
          application has an analytics screen, but it is a product view computed from marking
          records inside your own workspace; it is not a tracking service and it does not
          profile visitors.
        </p>
        <p>
          This is a statement about the code in this build. If analytics or any other
          non-essential technology is added later, this policy will change and the consent
          position in section 7 will change with it.
        </p>
      </LegalSection>

      <LegalSection id="consent" number="07" title="Consent and why there is no banner">
        <p>
          Rules such as the EU ePrivacy Directive require consent before storing or reading
          information on a device unless the storage is strictly necessary to provide a
          service the user requested, or is used only to transmit a communication. In this
          build every key in section 4 is first-party and serves the requested service:
          keeping a signed-in session, completing a sign-in round trip, or remembering a
          display preference the user chose. None tracks a person across sites or feeds an
          advertising profile.
        </p>
        <p>
          A consent banner that asked you to approve essential sign-in storage would be
          misleading, and a banner with nothing optional to switch off would be decoration.
          The site therefore shows no cookie banner and offers no preference toggles, and it
          says so here rather than presenting controls that do nothing.
        </p>
        <p>
          Where consent is required for something else — for example marketing email or
          optional analytics — it will be collected separately, explicitly, without
          preselected boxes, and it will be as easy to refuse as to accept. Acknowledging the
          Terms of Service or the Privacy Policy is not consent to optional processing.
        </p>
      </LegalSection>

      <LegalSection id="retention" number="08" title="How long storage lasts">
        <p>
          Session storage is discarded when the tab or browser window closes. Local storage
          has no automatic expiry: a session lasts until sign-out, revocation, or the refresh
          token expiring; identities, theme and rail preferences last until you remove them or
          clear site data. The operator cannot remotely clear storage on your device, because
          it holds no such mechanism; signing out is the supported way to remove a session.
        </p>
      </LegalSection>

      <LegalSection id="managing" number="09" title="Managing and clearing storage">
        <p>
          You can inspect and delete this data in your browser’s developer tools or site-data
          settings, and you can block storage entirely. Blocking local storage will stop
          sign-in from persisting: the session cannot be kept, so you will have to sign in
          again on each visit, and the theme will fall back to its default. It does not
          prevent the public legal pages from being read.
        </p>
        <ul>
          <li>Chrome and Edge: Settings → Privacy and security → Third-party cookies → See all site data and permissions.</li>
          <li>Firefox: Settings → Privacy &amp; Security → Cookies and Site Data → Manage Data.</li>
          <li>Safari: Settings → Privacy → Manage Website Data.</li>
        </ul>
        <p>
          Signing out from the account menu, or from the settings page, clears the active
          session on this device. It does not delete your account or the workspace records
          held by the service; see the{' '}
          <Link to="/account-deletion">deletion and data requests page</Link>.
        </p>
      </LegalSection>

      <LegalSection id="changes" number="10" title="Changes to this policy">
        <p>
          This policy names the keys the build actually writes, so it changes whenever that
          list changes. The version and date at the top of the page are updated at the same
          time. If a change introduces non-essential storage, consent will be requested before
          it is written and this policy will explain what it is for.
        </p>
      </LegalSection>

      <LegalSection id="contact" number="11" title="Contact">
        <p>
          Questions about cookies or browser storage can be sent to{' '}
          <LegalPlaceholder>CONTACT EMAIL — TO BE CONFIRMED</LegalPlaceholder>. The full set
          of documents is listed in the <Link to="/legal">legal centre</Link>, and the{' '}
          <Link to={LEGAL_DOCUMENTS.privacy.path}>Privacy Policy</Link> explains the wider
          data processing that this policy does not cover.
        </p>
        <p>
          This policy is a technical and product draft. It is not legal advice and should be
          reviewed by qualified counsel before it is treated as final.
        </p>
      </LegalSection>
    </LegalPage>
  )
}
