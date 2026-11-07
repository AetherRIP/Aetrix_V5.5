/**
 * Account roles, permissions and navigation.
 *
 * The role is read from Supabase's `app_metadata`, which only the identity
 * provider's admin API can write. `user_metadata` is user-writable and is never
 * consulted: a browser that edits its own profile cannot promote itself.
 *
 * This module decides what the interface *shows* and which routes it *opens*.
 * It is not the security boundary: the correction engine scopes every query by
 * the tenant and role in the verified token, and its authorisation is the one
 * that counts. See `docs/architecture/AETRIX_V5.5_SYSTEM.md`.
 */

export type AccountRole = 'platform_operator' | 'supervisor' | 'assistant'

export type Permission =
  | 'platform.users.read'
  | 'platform.users.manage'
  | 'platform.workspaces.read'
  | 'platform.workspaces.manage'
  | 'platform.allocations.manage'
  | 'platform.health.read'
  | 'platform.audit.read'
  | 'platform.providers.configure'
  | 'platform.settings.manage'
  | 'workspace.settings.manage'
  | 'workspace.assistants.manage'
  | 'workspace.classroom.connect'
  | 'students.read'
  | 'students.manage'
  | 'assignments.read'
  | 'assignments.manage'
  | 'submissions.read'
  | 'submissions.review'
  | 'gradebook.read'
  | 'gradebook.manage'
  | 'analytics.read'
  | 'tasks.read'
  | 'notifications.read'
  | 'own.progress.read'
  | 'own.submissions.read'

/** Explicit capability sets. A permission absent from a role is denied. */
const PERMISSIONS: Record<AccountRole, readonly Permission[]> = {
  platform_operator: [
    'platform.users.read',
    'platform.users.manage',
    'platform.workspaces.read',
    'platform.workspaces.manage',
    'platform.allocations.manage',
    'platform.health.read',
    'platform.audit.read',
    'platform.providers.configure',
    'platform.settings.manage',
    'notifications.read',
  ],
  supervisor: [
    'workspace.settings.manage',
    'workspace.assistants.manage',
    'workspace.classroom.connect',
    'students.read',
    'students.manage',
    'assignments.read',
    'assignments.manage',
    'submissions.read',
    'submissions.review',
    'gradebook.read',
    'gradebook.manage',
    'analytics.read',
    'tasks.read',
    'notifications.read',
  ],
  assistant: [
    'assignments.read',
    'submissions.read',
    'submissions.review',
    'gradebook.read',
    'analytics.read',
    'tasks.read',
    'notifications.read',
    'own.progress.read',
    'own.submissions.read',
  ],
}

export type RoleMeta = {
  role: AccountRole
  /** What the account is called in the interface. */
  label: string
  /** Who the account is, in one line, for the profile menu. */
  summary: string
  /** The scope every query is limited to. */
  scope: string
  /** Where the role lands after sign-in. */
  home: AppPath
}

/**
 * The engine's own role vocabulary (`backend/app/db/models.py`) is narrower than
 * the product's three account types. The mapping is stated here so the wire
 * contract can be added without guessing later.
 */
export const ENGINE_ROLE: Record<AccountRole, 'ADMIN' | 'OWNER' | 'REVIEWER'> = {
  platform_operator: 'ADMIN',
  supervisor: 'OWNER',
  assistant: 'REVIEWER',
}

export const ROLE_META: Record<AccountRole, RoleMeta> = {
  platform_operator: {
    role: 'platform_operator',
    label: 'Platform administrator',
    summary: 'Operates the platform, its workspaces and its accounts.',
    scope: 'Whole platform — no student records',
    home: '/platform',
  },
  supervisor: {
    role: 'supervisor',
    label: 'Teacher',
    summary: 'Owns one workspace and the teaching work inside it.',
    scope: 'Own workspace only',
    home: '/dashboard',
  },
  assistant: {
    role: 'assistant',
    label: 'Assistant',
    summary: 'Works inside a teacher’s workspace on assigned work.',
    scope: 'Assigned classes and submissions',
    home: '/assistant',
  },
}

const ROLES: readonly AccountRole[] = ['platform_operator', 'supervisor', 'assistant']

function isRole(value: unknown): value is AccountRole {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value)
}

/** The shape we read from a Supabase user without importing its type graph. */
type ClaimSubject = { app_metadata?: Record<string, unknown> | null } | null | undefined

/**
 * The account role, or `null` when none is assigned.
 *
 * Both spellings are accepted because a raw app-metadata write may use either;
 * nothing outside `app_metadata` is ever read.
 */
export function readRole(user: ClaimSubject): AccountRole | null {
  const meta = user?.app_metadata
  if (!meta) return null
  const direct = meta['aetrix_role']
  if (isRole(direct)) return direct
  const nested = meta['aetrix']
  if (nested && typeof nested === 'object') {
    const value = (nested as Record<string, unknown>)['role']
    if (isRole(value)) return value
  }
  return null
}

export function can(role: AccountRole | null, permission: Permission): boolean {
  if (!role) return false
  return PERMISSIONS[role].includes(permission)
}

export function permissionsOf(role: AccountRole | null): readonly Permission[] {
  return role ? PERMISSIONS[role] : []
}

export type AppPath =
  | '/dashboard'
  | '/workspace'
  | '/inbox'
  | '/queue'
  | '/assignments'
  | '/reports'
  | '/settings'
  | '/students'
  | '/gradebook'
  | '/analytics'
  | '/assistants'
  | '/classroom'
  | '/platform'
  | '/platform/workspaces'
  | '/platform/users'
  | '/platform/health'
  | '/platform/audit'
  | '/platform/integrations'
  | '/platform/settings'
  | '/assistant'
  | '/assistant/classes'
  | '/assistant/work'
  | '/assistant/tasks'
  | '/assistant/progress'

export type NavIcon =
  | 'chart'
  | 'classroom'
  | 'records'
  | 'pulse'
  | 'assignment'
  | 'blueprint'
  | 'lock'
  | 'shield'
  | 'server'
  | 'eye'
  | 'checkDouble'
  | 'pen'

export type NavItem = { to: AppPath; label: string; icon: NavIcon }

export type RoleNav = {
  /** The rail's main list. */
  primary: NavItem[]
  /** A named group under the main list (team, platform, work). */
  groupLabel: string
  secondary: NavItem[]
  /** One-tap destinations on a phone. */
  tabs: NavItem[]
}

const TEACHER_NAV: RoleNav = {
  primary: [
    { to: '/dashboard', label: 'Dashboard', icon: 'chart' },
    { to: '/inbox', label: 'Inbox', icon: 'records' },
    { to: '/students', label: 'Classes & students', icon: 'classroom' },
    { to: '/assignments', label: 'Assignments', icon: 'assignment' },
    { to: '/queue', label: 'Marking queue', icon: 'pulse' },
    { to: '/reports', label: 'Reports', icon: 'blueprint' },
    { to: '/gradebook', label: 'Gradebook', icon: 'checkDouble' },
  ],
  groupLabel: 'Team',
  secondary: [
    { to: '/assistants', label: 'Assistants', icon: 'eye' },
    { to: '/analytics', label: 'Analytics', icon: 'chart' },
    { to: '/classroom', label: 'Google Classroom', icon: 'classroom' },
    { to: '/workspace', label: 'Workspace', icon: 'lock' },
    { to: '/settings', label: 'Settings', icon: 'lock' },
  ],
  tabs: [
    { to: '/dashboard', label: 'Dashboard', icon: 'chart' },
    { to: '/assignments', label: 'Assignments', icon: 'assignment' },
    { to: '/queue', label: 'Queue', icon: 'pulse' },
    { to: '/inbox', label: 'Inbox', icon: 'records' },
  ],
}

const ASSISTANT_NAV: RoleNav = {
  primary: [
    { to: '/assistant', label: 'My overview', icon: 'chart' },
    { to: '/assistant/tasks', label: 'Tasks', icon: 'checkDouble' },
    { to: '/queue', label: 'Submission queue', icon: 'pulse' },
    { to: '/assistant/work', label: 'Marking workspace', icon: 'pen' },
    { to: '/reports', label: 'Results', icon: 'blueprint' },
    { to: '/assistant/classes', label: 'Assigned classes', icon: 'classroom' },
  ],
  groupLabel: 'Progress',
  secondary: [
    { to: '/assistant/progress', label: 'My progress', icon: 'chart' },
    { to: '/inbox', label: 'Notifications', icon: 'records' },
    { to: '/settings', label: 'Settings', icon: 'lock' },
  ],
  tabs: [
    { to: '/assistant', label: 'Overview', icon: 'chart' },
    { to: '/queue', label: 'Queue', icon: 'pulse' },
    { to: '/assistant/tasks', label: 'Tasks', icon: 'checkDouble' },
    { to: '/inbox', label: 'Inbox', icon: 'records' },
  ],
}

const PLATFORM_NAV: RoleNav = {
  primary: [
    { to: '/platform', label: 'Platform overview', icon: 'shield' },
    { to: '/platform/workspaces', label: 'Workspaces', icon: 'classroom' },
    { to: '/platform/users', label: 'Accounts', icon: 'eye' },
    { to: '/platform/health', label: 'System health', icon: 'server' },
    { to: '/platform/audit', label: 'Audit log', icon: 'records' },
  ],
  groupLabel: 'Platform',
  secondary: [
    { to: '/platform/integrations', label: 'AI providers', icon: 'blueprint' },
    { to: '/platform/settings', label: 'Settings', icon: 'lock' },
  ],
  tabs: [
    { to: '/platform', label: 'Overview', icon: 'shield' },
    { to: '/platform/workspaces', label: 'Workspaces', icon: 'classroom' },
    { to: '/platform/users', label: 'Accounts', icon: 'eye' },
    { to: '/platform/health', label: 'Health', icon: 'server' },
  ],
}

export const NAV_BY_ROLE: Record<AccountRole, RoleNav> = {
  platform_operator: PLATFORM_NAV,
  supervisor: TEACHER_NAV,
  assistant: ASSISTANT_NAV,
}

/** Every route an account type may open, as path prefixes. */
const ROUTES_BY_ROLE: Record<AccountRole, readonly string[]> = {
  platform_operator: ['/platform', '/settings'],
  supervisor: [
    '/dashboard',
    '/workspace',
    '/inbox',
    '/queue',
    '/assignments',
    '/reports',
    '/settings',
    '/students',
    '/gradebook',
    '/analytics',
    '/assistants',
    '/classroom',
  ],
  assistant: [
    '/assistant',
    '/queue',
    '/reports',
    '/inbox',
    '/settings',
    '/assignments',
    '/submissions',
  ],
}

export function allowsPath(role: AccountRole | null, path: string): boolean {
  if (!role) return false
  const normalised = path.replace(/\/+$/, '') || '/'
  return ROUTES_BY_ROLE[role].some(
    (allowed) => normalised === allowed || normalised.startsWith(`${allowed}/`),
  )
}

/**
 * Where a role belongs when it lands somewhere it may not open. It is always a
 * permitted destination, so a redirect can never loop.
 */
export function homeFor(role: AccountRole | null): AppPath {
  return role ? ROLE_META[role].home : '/settings'
}
