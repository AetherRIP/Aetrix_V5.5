/**
 * The public legal documents, in one place.
 *
 * Every legal route, the footer, the legal centre and the sign-in
 * acknowledgement read from here, so a version bump or a corrected date changes
 * one value rather than eight pages. The version is the ISO date the document
 * was last changed; it is shown to the reader and is what the acknowledgement
 * refers to.
 */

export type LegalDocumentId =
  | 'terms'
  | 'privacy'
  | 'cookies'
  | 'acceptable-use'
  | 'ai-disclosure'
  | 'copyright'
  | 'security'
  | 'account-deletion'

export type LegalDocumentPath =
  | '/terms'
  | '/privacy'
  | '/cookies'
  | '/acceptable-use'
  | '/ai-disclosure'
  | '/copyright'
  | '/security'
  | '/account-deletion'

export type LegalDocument = {
  id: LegalDocumentId
  path: LegalDocumentPath
  title: string
  shortTitle: string
  summary: string
  updated: string
  updatedIso: string
  version: string
}

export const LEGAL_UPDATED = '13 November 2026'
export const LEGAL_UPDATED_ISO = '2026-11-13'
export const LEGAL_VERSION = '2026-11-13'

export const LEGAL_DOCUMENTS: Record<LegalDocumentId, LegalDocument> = {
  terms: {
    id: 'terms',
    path: '/terms',
    title: 'Terms of Service',
    shortTitle: 'Terms',
    summary:
      'The agreement for using the pilot: eligibility, roles, acceptable use, AI marking limits, intellectual property, liability and governing law.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
  privacy: {
    id: 'privacy',
    path: '/privacy',
    title: 'Privacy Policy',
    shortTitle: 'Privacy',
    summary:
      'What Aetrix collects, why it is processed, the legal bases relied on, the providers involved, retention, transfers and your rights.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
  cookies: {
    id: 'cookies',
    path: '/cookies',
    title: 'Cookie Policy',
    shortTitle: 'Cookies',
    summary:
      'Every cookie and browser-storage key the site actually uses, why it exists, how long it lasts and how to remove it.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
  'acceptable-use': {
    id: 'acceptable-use',
    path: '/acceptable-use',
    title: 'Acceptable Use Policy',
    shortTitle: 'Acceptable use',
    summary:
      'The conduct that is prohibited on the service, including access abuse, malicious uploads, content misuse and attempts to manipulate AI output.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
  'ai-disclosure': {
    id: 'ai-disclosure',
    path: '/ai-disclosure',
    title: 'AI Use Disclosure',
    shortTitle: 'AI use',
    summary:
      'Which features use AI, what content is sent to a provider, what the output can get wrong, and why a human must review it.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
  copyright: {
    id: 'copyright',
    path: '/copyright',
    title: 'Intellectual Property and Copyright Policy',
    shortTitle: 'Copyright & IP',
    summary:
      'Who owns the platform and the uploaded content, the licence needed to operate the service, and how to report infringing material.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
  security: {
    id: 'security',
    path: '/security',
    title: 'Security and Vulnerability Disclosure Policy',
    shortTitle: 'Security',
    summary:
      'The controls the pilot actually implements, the limitations it does not hide, and how to report a vulnerability responsibly.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
  'account-deletion': {
    id: 'account-deletion',
    path: '/account-deletion',
    title: 'Account Deletion and Data Requests',
    shortTitle: 'Deletion & requests',
    summary:
      'How to ask for access, correction or deletion while self-service controls do not exist, and what the pilot can and cannot remove.',
    updated: LEGAL_UPDATED,
    updatedIso: LEGAL_UPDATED_ISO,
    version: LEGAL_VERSION,
  },
}

/** Registry order, used by the legal centre, the footer and the policy sidebar. */
export const LEGAL_DOCUMENT_LIST: readonly LegalDocument[] = [
  LEGAL_DOCUMENTS.terms,
  LEGAL_DOCUMENTS.privacy,
  LEGAL_DOCUMENTS.cookies,
  LEGAL_DOCUMENTS['acceptable-use'],
  LEGAL_DOCUMENTS['ai-disclosure'],
  LEGAL_DOCUMENTS.copyright,
  LEGAL_DOCUMENTS.security,
  LEGAL_DOCUMENTS['account-deletion'],
]
