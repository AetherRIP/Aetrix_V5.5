# Information Architecture

**Status:** RECOMMENDED. Optimised for two different tasks: *do the marking* (assistant) and *know the
state of the marking* (supervisor). Everything else is reachable but not competing.

## 1. Sitemap

```
/                                  marketing: landing
/pricing  /features  /use-cases  /security  /faq  /contact
/docs  /docs/[slug]                public documentation / help centre
/legal/terms  /legal/privacy  /legal/dpa  /legal/cookies
/status  /changelog                public status + release notes

/auth/signup  /auth/login  /auth/verify  /auth/forgot  /auth/reset
/auth/mfa  /auth/invite/[token]    acceptance and step-up

/onboarding/workspace  /onboarding/checklist
/workspaces                        workspace picker (multi-membership)

/w/[workspaceSlug]/                authenticated app
  home                             dashboard (state of the workspace)
  inbox                            what needs me: reviews, failures, mentions
  assignments
    /new  /[assignmentId]          overview
      /scheme                      mark scheme + blueprint review
      /submissions                 table of scripts
      /queue                       marking queue
      /review/[submissionId]       the review canvas
      /results                     marks table / grade matrix
      /report                      class report
      /settings                    assignment config, allocation, archive
  classes  /[classId]  /[classId]/students  /[classId]/performance
  students /[studentId]
  reports                          cross-assignment reporting
  activity                         workspace activity + audit (permission-gated)
  members  /invites
  settings
    /general  /branding  /academic  /corrections  /notifications  /retention
    /integrations/classroom  /credentials  /usage  /danger
  help                             in-app help, shortcuts, support

/admin                             platform (operator only, MFA + step-up)
  /workspaces  /workspaces/[id]  /accounts  /health  /queues  /usage
  /security  /audit  /support-grants  /config  /releases
```

## 2. Navigation model

**Left rail (232 px), grouped by task — not by database table:**

| Group | Items |
|---|---|
| *Now* | Home · Inbox (badge = items needing me) |
| *Marking* | Assignments · Queue · Review |
| *Records* | Classes · Students · Reports |
| *Workspace* | Members · Activity · Settings |

Rationale: "Queue" and "Review" are top-level because they are the product; "Results" lives inside an
assignment because a mark only means something relative to its assignment. "Inbox" exists so the supervisor
does not have to tour every assignment to find what is stuck.

**Top bar (56 px):** workspace switcher · breadcrumb · global search (`⌘K`) · job activity indicator ·
notifications · account menu. The job indicator is always present when any job is running, because "is it
working?" must never require navigation.

**Workspace switcher** lists memberships with role labels and a "create workspace" action. Switching is a
full context change: the rail, permissions and cached data all reset (no stale cross-workspace data in
memory).

**Mobile:** rail collapses into a bottom bar with Now / Marking / Records / More. Review is read-only.

## 3. URL and identity rules

- Slugs are workspace-scoped and stable; ids in URLs are UUIDv7 (never sequential).
- Object routes always carry their workspace prefix: `/w/{slug}/assignments/{id}`. There is no
  workspace-free object URL, so a copied link cannot be replayed into another tenant.
- A route that resolves to a non-member object returns **404** (not 403) — existence is not leaked.
- Deep links must survive session expiry: after login the user returns to the exact URL.

## 4. Content hierarchy per area

| Area | Primary object | Secondary | Tertiary |
|---|---|---|---|
| Home | Exceptions (reviews, failures) | Throughput and workload | Recent activity |
| Inbox | Items needing me, newest first | Filters: type, assignment, age | Snooze/mark read |
| Assignment | State (draft → marking → review → published) | Submissions table | Settings, scheme, allocation |
| Queue | Next script to mark | Filters (unassigned, mine, review) | Bulk start/cancel |
| Review | The script | Per-question marks + explanation | Comments, history |
| Results | Grade matrix | Distribution chart | Export |
| Students | Roster | Per-student history | Notes |

## 5. Search, filters, and saved views

- **Global search** (`⌘K`): assignments, students, classes, submissions by script id; scoped to the active
  workspace only. Cross-workspace search is deliberately impossible in the UI.
- **Filters are URL state** (`?status=review&assignee=me`) so a filtered view can be shared and bookmarked.
- **Saved views** per user per list (e.g. "My unapproved reviews"), stored server-side, no PII in the name.
- Filter vocabulary is shared across lists: `status`, `assignee`, `assignment`, `class`, `date`, `has_review`.

## 6. Wayfinding rules

1. Every screen answers: *where am I* (breadcrumb + H1), *what is this* (one-sentence description where
   ambiguous), *what can I do* (primary action), *what changed* (state chips and timestamps).
2. Counts in navigation are live but throttle to 30 s; a stale badge is better than a broken page.
3. No modal deeper than one level; complex tasks are routes, not dialogs (a dialog cannot be linked,
   refreshed or restored).
4. Destructive actions live only in `/settings/danger`, never in a list row menu.

## 7. Label glossary (one name per concept, everywhere)

| Concept | Use | Never |
|---|---|---|
| A unit of work to mark | **Assignment** | task, project |
| One student's uploaded script | **Submission** | paper, file, attempt |
| The AI+human mark set for a submission | **Result** | output, grading |
| A queued/running AI attempt | **Job** | task, process, run |
| The official question/max-mark structure | **Mark scheme** (blueprint after locking) | rubric, key |
| A mark a human changed | **Override** | edit, correction |
| Items needing a human | **Review** | flag, exception, issue |
| Publishing to Classroom | **Publish** | sync, push, upload (grades) |
