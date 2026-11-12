# SKILLS INDEX — design layer (2026-11-03)

> **Superseded scope note (2026-11-07).** This file documents the original 18-skill design
> layer only. The project skill set has since grown to 48 skills (25 external engineering
> skills + 5 Aetrix-specific skills). The current catalog, licensing, activation model and
> maintenance procedure live in [`docs/agent-skills/SKILL_CATALOG.md`](../docs/agent-skills/SKILL_CATALOG.md)
> and [`docs/agent-skills/INSTALLATION_REPORT.md`](../docs/agent-skills/INSTALLATION_REPORT.md),
> with per-task routing in [`AGENTS.md`](../AGENTS.md). Nothing below has been altered.

**Status:** 18 design skills installed and verified · **Installed:** 2026-11-03 · **Workspace:** `TEMP` (future `UI_V5.5`)

This directory prepares an AI agent to act as a **senior UI/UX designer, design-system architect and WPF desktop UI specialist** during brainstorming for the Aetrix V5.5 redesign. It contains **design intelligence and planning material only** — no application code, no .NET solution, no XAML, no UI libraries.

---

## 1. Skill discovery — verified location

Before installing anything, the Freebuff host was inspected rather than assumed. Extracting the skill-loader documentation from the installed app bundle (`%LOCALAPPDATA%\Programs\@codebufffreebuff-desktop\resources\app.asar`) gives the authoritative contract:

> Load skills from `.agents/skills` and `.claude/skills` directories. By default, searches PROJECT directories only (later overrides earlier): `{cwd}/.agents/skills/` (project, highest priority). The user's home directory is searched only with `includeHomeSkills: true` … Each skill must be in its own directory with a `SKILL.md` file: `.agents/skills/my-skill/SKILL.md`

**Conclusion:** `.agents/skills/` in the project root is the correct **highest-priority** project-level location. No alternate location was needed, and no project config file had to be created — discovery is directory-based and requires no manifest.

**Operational note:** skills are enumerated when a session's initial state is built. Start a **new session** (or reload the app) after editing this folder; skills are then exposed to the agent by name and description and loaded on demand, so 18 skills cost almost no context until one is actually used.

---

## 2. Inventory at a glance

| # | Skill | Priority | Source repo | Structure | License |
|---|-------|----------|-------------|-----------|---------|
| 1 | `frontend-design` | P1 | anthropics/skills | `SKILL.md`, `LICENSE.txt` | Apache-2.0 |
| 2 | `ui-ux-pro-max` | P1 | nextlevelbuilder/ui-ux-pro-max-skill | `SKILL.md`, `data/`, `references/`, `scripts/` | MIT |
| 3 | `impeccable` | P1 | pbakaus/impeccable | `SKILL.md`, `reference/`, `agents/`, `scripts/` | Apache-2.0 |
| 4 | `ui-visual-composition` | P1 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 5 | `design-systems-frontend-architecture` | P1 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 6 | `information-architecture-navigation` | P1 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 7 | `interaction-patterns-components` | P2 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 8 | `ux-usability-foundations` | P1 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 9 | `ux-research-discovery-testing` | P1 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 10 | `accessibility-inclusive-design` | P1 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 11 | `ux-writing-content-design` | P2 | hueyexe/frontend-agent-skills | `SKILL.md`, `references/` (4) | MIT |
| 12 | `design-system` | P1 | nextlevelbuilder/ui-ux-pro-max-skill | `SKILL.md`, `references/` (7), `templates/`, `data/` | MIT |
| 13 | `design-motion-design` | P2 | j4flmao/agent-skills | `SKILL.md`, `references/` (6) | MIT |
| 14 | `idea-refine` | P1 | addyosmani/agent-skills | `SKILL.md`, `frameworks.md`, `examples.md`, `refinement-criteria.md`, `scripts/` | MIT |
| 15 | `interview-me` | P1 | addyosmani/agent-skills | `SKILL.md` | MIT |
| 16 | `planning-and-task-breakdown` | P2 | addyosmani/agent-skills | `SKILL.md` | MIT |
| 17 | `desktop-wpf` | P3 | j4flmao/agent-skills | `SKILL.md`, `references/` (6) | MIT |
| 18 | `mvvm` | P3 | managedcode/dotnet-skills | `SKILL.md`, `references/` (2), `manifest.json` | MIT |

Priority key: **P1** core design thinking · **P2** visual/inspiration/planning · **P3** WPF & .NET engineering.

---

## 3. Skill detail

Every entry: source repository → original path → installed path. All installs preserve the upstream directory tree.

### 3.1 Aesthetic direction and design intelligence

#### `frontend-design`
- **Source:** `anthropics/skills` @ `ca45fc4` · **Original:** `skills/frontend-design/` · **Installed:** `.agents/skills/frontend-design/`
- **Capabilities:** the strongest available *design-direction* skill. Forces a compact token system before any drawing — 4–6 named hex values, typefaces and roles, a layout concept expressed in prose + ASCII wireframes, and explicit design principles. Documents the current "AI design tells" (cream/serif/terracotta, near-black + acid accent, SaaS card kit, all-caps eyebrows, `→` on every button) so they can be deliberately avoided, and requires a second pass that critiques the plan against the brief before building. Also carries real UX-writing guidance (active voice, one job per element, errors that state what happened and how to fix it).
- **Use for:** opening a brainstorming session, generating divergent visual directions, arguing for one direction over another, establishing typography and palette personality.
- **Framework fit:** written with the web in mind, but its content is discipline-level (hierarchy, type scale, line length <80ch, restraint). Transfers directly to a desktop app.

#### `ui-ux-pro-max`
- **Source:** `nextlevelbuilder/ui-ux-pro-max-skill` @ `713eef5` · **Original:** `.claude/skills/ui-ux-pro-max/` · **Installed:** `.agents/skills/ui-ux-pro-max/`
- **Capabilities:** the reference database of the environment. Local CSV data covering **79 UI styles** (with era, complexity, light/dark support, accessibility risk, framework compatibility, implementation checklists and design-system variables), **192 product palettes with reasoning profiles**, **74 font pairings**, **119 UX guidelines**, **105 icons**, **25 chart types** with accessibility fallbacks, and **22 stack guides — including `stacks/wpf.csv`, `winui.csv`, `uwp.csv`, `avalonia.csv`**.
- **Use for:** concretely naming and comparing design directions; justifying a palette or font pairing; selecting a table/chart pattern for data-heavy grading screens; checking a style against accessibility risk before committing to it.
- **Dependencies:** the optional `scripts/search.py` needs Python 3 (see §7). The data is plain CSV and fully readable without it — this is a lookup aid, not a prerequisite.
- **Modification (documented):** two edits to `SKILL.md`. (a) Host-specific `${CLAUDE_PLUGIN_ROOT}/.claude/skills/ui-ux-pro-max/scripts/` paths rewritten to `.agents/skills/ui-ux-pro-max/scripts/` so the commands resolve in this workspace. (b) One-line environment note stating Python is absent and the CSVs should be read directly. No design content was altered.

#### `impeccable`
- **Source:** `pbakaus/impeccable` @ `9fadc41` · **Original:** `.agents/skills/impeccable/` · **Installed:** `.agents/skills/impeccable/`
- **Capabilities:** the design *vocabulary* and the reviewer. 24 named moves (`shape`, `critique`, `audit`, `polish`, `bolder`, `quieter`, `distill`, `typeset`, `layout`, `animate`, `harden`, `onboard`, `colorize`, `document`, `extract`, …) each with a dedicated playbook in `reference/`. Defines four surface **modes** — **Persuade / Operate / Read / Experience** — where *Operate* ("the visitor completes a task: app UI, dashboards, editors, admin, settings, tools — scanability, consistency, native expectations") is exactly the Aetrix V5.5 mode. `reference/craft-floor.md` is a genuine quality floor, `reference/critique.md` scores against usability heuristics, `reference/operate.md` covers dashboard/app guidance, and the launcher bundles a 62-rule deterministic "AI slop" detector.
- **Use for:** critiquing a proposed layout, scoring alternatives, applying a single directional move ("quieter", "distill", "typeset") to one screen, documenting the existing visual system into `DESIGN.md`.
- **Dependencies:** the `scripts/impeccable` launcher downloads a self-contained engine on first run (network + executing a third-party binary). **It was not executed during this install and is not required** — every `reference/*.md` playbook is self-contained Markdown and works read-only. Treat the launcher as opt-in and inspect/approve before first use.

### 3.2 Visual composition, IA, interaction, systems

#### `ui-visual-composition`
- **Source:** `hueyexe/frontend-agent-skills` @ `2841c07` · **Original:** `ui-visual-composition/` · **Installed:** `.agents/skills/ui-visual-composition/`
- **Capabilities:** visual hierarchy, spacing rhythm, typography, color, depth/elevation, imagery and visual states, treated as functional communication ("what matters, what belongs together, what can be acted on, what changed"). Ships `anti-patterns.md`, `checklists.md`, `decision-prompts.md`, `principle-cards.md`.
- **Use for:** the craft layer of any mockup description — density, grouping, emphasis, alignment, states.

#### `design-systems-frontend-architecture`
- **Source:** same repo · **Original:** `design-systems-frontend-architecture/` · **Installed:** `.agents/skills/design-systems-frontend-architecture/`
- **Capabilities:** turning screens into a system — design tokens, component contracts, layout rules, state behaviour, documentation and governance; also reads mockups/screenshots and decomposes them into reusable components.
- **Use for:** deciding which Aetrix V5.5 surfaces are components vs. one-off screens; component inventories; preventing drift between the marking view and the assignment view.

#### `information-architecture-navigation`
- **Source:** same repo · **Original:** `information-architecture-navigation/` · **Installed:** `.agents/skills/information-architecture-navigation/`
- **Capabilities:** organization, labelling, taxonomy, hierarchy, navigation models, search, filters/facets, metadata, wayfinding, settings IA, dashboard IA. Explicitly covers "information-dense pages".
- **Use for:** the navigation system itself — how assignments, classes, students, submissions and marking results relate; sidebar vs. tabs vs. master-detail; label sets.

#### `interaction-patterns-components`
- **Source:** same repo · **Original:** `interaction-patterns-components/` · **Installed:** `.agents/skills/interaction-patterns-components/`
- **Capabilities:** pattern *selection* — navigation, menus, cards, tables, dashboards, modals, wizards, **split panes**, tabs, accordions, **toolbars**, hover tools, lists/grids, feedback states — plus component behaviour, state handling and selection heuristics based on task, user skill, data complexity and risk.
- **Use for:** the detailed marking/correction workspace (list → submission → rubrics/annotation panes), assignment tables, bulk actions, filter bars.

#### `ux-usability-foundations`
- **Source:** same repo · **Original:** `ux-usability-foundations/` · **Installed:** `.agents/skills/ux-usability-foundations/`
- **Capabilities:** affordances/signifiers, feedback, constraints, error prevention and recovery, recognition over recall, task clarity, empty/loading/success states.
- **Use for:** pressure-testing a workflow before drawing it — "can a teacher recover from a mis-scored item?".

#### `ux-research-discovery-testing`
- **Source:** same repo · **Original:** `ux-research-discovery-testing/` · **Installed:** `.agents/skills/ux-research-discovery-testing/`
- **Capabilities:** just-enough research design — discovery/stakeholder interviews, contextual inquiry, usability-test scripts and screeners, synthesis frameworks, journey maps, personas, opportunity maps, evidence-backed recommendations.
- **Use for:** deciding what to learn from teachers/markers before committing to a direction; writing a task-based usability script to compare two design directions.

#### `accessibility-inclusive-design`
- **Source:** same repo · **Original:** `accessibility-inclusive-design/` · **Installed:** `.agents/skills/accessibility-inclusive-design/`
- **Capabilities:** keyboard flows, focus management, screen-reader semantics, contrast, scalable type, inclusive defaults, resilience across zoom/device/user settings.
- **Use for:** making accessibility part of the design brief rather than a later QA pass; desktop keyboard-first operation is a real WPF requirement.

#### `ux-writing-content-design`
- **Source:** same repo · **Original:** `ux-writing-content-design/` · **Installed:** `.agents/skills/ux-writing-content-design/`
- **Capabilities:** microcopy, labels, CTAs, empty/error/success/loading text, onboarding, notifications, terminology, voice & tone, content patterns.
- **Use for:** the interface's actual words — "Regrade", "Publish marks", "12 submissions need review" instead of "Something went wrong".

#### `design-system`
- **Source:** `nextlevelbuilder/ui-ux-pro-max-skill` @ `713eef5` · **Original:** `.claude/skills/design-system/` · **Installed:** `.agents/skills/design-system/`
- **Capabilities:** three-layer token architecture (**primitive → semantic → component**), spacing and typography scales, component specifications, states and variants, plus `references/token-architecture.md`, `semantic-tokens.md`, `component-tokens.md`, `component-specs.md`, `states-and-variants.md`. (It also bundles slide-generation data — irrelevant here, harmless.)
- **Use for:** the single most important planning artefact for a WPF app: a token layer that maps 1:1 onto `ResourceDictionary` keys. Naming, aliasing and semantic layers can be designed here, before any XAML exists.

#### `design-motion-design`
- **Source:** `j4flmao/agent-skills` @ `5610797` · **Original:** `skills/design/motion-design/` · **Installed:** `.agents/skills/design-motion-design/`
- **Capabilities:** animation principles, a timing scale, micro-interaction patterns, view/page transitions, loading and progress motion, an "animation complexity budget", and reduced-motion requirements. References include `ui-animation-patterns.md`, `motion-accessibility.md`, `animation-principles.md`.
- **Use for:** deciding which interactions deserve motion (mark entry advancing to the next submission, a grade recalculation, a save confirmation) and which do not — before any Storyboard is written.

### 3.3 Brainstorming and planning

#### `idea-refine`
- **Source:** `addyosmani/agent-skills` @ `301b02b` · **Original:** `skills/idea-refine/` · **Installed:** `.agents/skills/idea-refine/`
- **Capabilities:** structured divergent-then-convergent refinement — restate, sharpen, generate variations; cluster, stress-test, surface hidden assumptions; converge into a concrete one-pager. Ships `frameworks.md`, `refinement-criteria.md`, `examples.md`.
- **Use for:** taking "make Aetrix V5.5 look modern" to a ranked set of distinct, defensible directions.

#### `interview-me`
- **Source:** same repo · **Original:** `skills/interview-me/` · **Installed:** `.agents/skills/interview-me/`
- **Capabilities:** one-question-at-a-time requirements extraction, with a best guess attached to each question, until the agent can predict the answer (~95% confidence) — targeting *who / why / what success looks like / binding constraint*.
- **Use for:** the very start — user roles, marking volume, hardware, offline constraints, existing workflow pain — instead of silently inventing requirements.

#### `planning-and-task-breakdown`
- **Source:** same repo · **Original:** `skills/planning-and-task-breakdown/` · **Installed:** `.agents/skills/planning-and-task-breakdown/`
- **Capabilities:** decomposing work into ordered, individually verifiable tasks with explicit acceptance criteria, dependency mapping and parallelisation.
- **Use for:** converting an approved design direction into a future implementation plan — the bridge between V5.5 brainstorming and eventual WPF work.

### 3.4 WPF and .NET (implementation-aware, for planning only)

#### `desktop-wpf`
- **Source:** `j4flmao/agent-skills` @ `5610797` · **Original:** `skills/desktop/wpf/` · **Installed:** `.agents/skills/desktop-wpf/`
- **Capabilities:** WPF architecture decision tree (MVVM / code-behind / hybrid), XAML and data binding, MVVM core with `RelayCommand`, validation, styling and theming, **custom controls and `ControlTemplate` / `Generic.xaml` / `TemplatePart`**, attached behaviours, routed commands, UI virtualization, Dispatcher threading, and MVVM-friendly dialog service / mediator patterns. References: `wpf-architecture.md`, `wpf-mvvm-patterns.md`, `wpf-performance.md`, `wpf-advanced.md`, `wpf-best-practices.md`, `wpf-fundamentals.md`.
- **Use for:** sanity-checking that a design direction is *buildable* in WPF — e.g. whether a dashboard's card grid implies virtualization, whether a consensus custom timeline needs a `ControlTemplate`, whether a drag-to-annotate marking canvas is an attached behaviour.

#### `mvvm`
- **Source:** `managedcode/dotnet-skills` @ `db0da0f` · **Original:** `catalog/Libraries/MVVM-Toolkit/skills/mvvm/` · **Installed:** `.agents/skills/mvvm/`
- **Capabilities:** CommunityToolkit.Mvvm specifics — `ObservableObject`, `RelayCommand`/async commands, `Messenger`, source generators, navigation ViewModel, dialog service, `IValueConverter` patterns, `INotifyDataErrorInfo` validation, master-detail and state patterns. References: `patterns.md`, `anti-patterns.md`.
- **Use for:** mapping screen state to ViewModel shape during planning, so a brainstorming doc doesn't propose UI that would force ugly code.

---

## 4. Activation strategy

### 4.1 Routing table

| When the task is… | Load first | Then bring in |
|---|---|---|
| Brainstorming a new interface | `interview-me` (if the ask is vague) → `frontend-design` | `ui-ux-pro-max`, `ui-visual-composition` |
| Exploring completely different design directions | `idea-refine` | `frontend-design`, `ui-ux-pro-max` (styles/palettes), `impeccable` (`shape`) |
| Evaluating a design reference / inspiration | `ui-visual-composition` | `ui-ux-pro-max` (style match), `impeccable` (`critique`) |
| Creating a design system | `design-system` (tokens) | `design-systems-frontend-architecture`, `ui-ux-pro-max` (font/palette data) |
| Planning dashboard layouts | `impeccable` (`operate`/`shape`) | `interaction-patterns-components`, `ui-ux-pro-max` (charts), `ui-visual-composition` |
| Designing data-heavy tables & grading interfaces | `interaction-patterns-components` | `ui-visual-composition`, `ui-ux-pro-max` (chart/table rules), `accessibility-inclusive-design` |
| Reviewing UI consistency | `impeccable` (`critique`/`audit`) | `design-systems-frontend-architecture`, `ui-visual-composition` |
| Planning future WPF implementation | `desktop-wpf` | `mvvm`, `planning-and-task-breakdown`, `design-system` |
| Navigation system / information architecture | `information-architecture-navigation` | `interaction-patterns-components` |
| Interaction & micro-interaction design | `design-motion-design` | `interaction-patterns-components`, `ux-usability-foundations` |
| Accessibility review | `accessibility-inclusive-design` | `ui-ux-pro-max` (contrast rules), `impeccable` (`audit`) |
| Copy, labels, empty & error states | `ux-writing-content-design` | `frontend-design` |
| Research or usability testing plan | `ux-research-discovery-testing` | `interview-me` |

### 4.2 Recipes for the mission's named scenarios

1. **Multiple completely different design directions.** `interview-me` → `idea-refine` (diverge to 5–7 named directions) → for each: `frontend-design` token plan + `ui-ux-pro-max` style/palette/font lookup → present as an ASCII-wireframed comparison → `impeccable critique` to rank them. Output: directions with a defensible reason to exist, not five border-radius variations.
2. **Professional desktop application layouts.** `impeccable` in *Operate* mode + `ui-ux-pro-max/stacks/wpf.csv` + `ui-visual-composition`. Anchor on desktop conventions (menu/menu-less, toolbars, resizable panes, status bar, keyboard-first) rather than responsive-web ones.
3. **Modern dashboards.** `impeccable` (`operate`) → `interaction-patterns-components` (dashboard + stat/KPI patterns) → `ui-ux-pro-max` chart selection with accessibility fallbacks → `ui-visual-composition` for density and hierarchy.
4. **Navigation systems.** `information-architecture-navigation` → `interaction-patterns-components` (pattern choice) → `accessibility-inclusive-design` (keyboard traversal, focus order).
5. **Assignment management.** `interaction-patterns-components` (table + master-detail + bulk actions) → `ux-usability-foundations` (error prevention on destructive actions) → `ui-visual-composition` (scan density).
6. **Student performance views.** `ui-ux-pro-max` chart selection → `interaction-patterns-components` → `accessibility-inclusive-design` (never encode a grade by hue alone) → `ux-writing-content-design` (what a trend label actually says).
7. **Detailed marking / correction interfaces.** `interaction-patterns-components` (split panes, toolbars, selection) → `design-motion-design` (focus transitions, next-item flow) → `accessibility-inclusive-design` → `desktop-wpf` (is this a `ControlTemplate`? does the canvas need virtualization?).
8. **Design system + typography + palettes.** `design-system` (three-layer tokens) → `ui-ux-pro-max` (font pairings, 192 palettes) → `frontend-design` (personality and restraint) → `design-systems-frontend-architecture` (contracts and governance).
9. **Interactions and workflows.** `ux-usability-foundations` → `design-motion-design` → `interaction-patterns-components` → `ux-writing-content-design`.
10. **Future WPF implementation planning.** `design-system` tokens → `desktop-wpf` architecture → `mvvm` state shape → `planning-and-task-breakdown` for ordered tasks. No code is produced at this stage.

### 4.3 Composition rules

- **Two to four skills per question is the useful range.** Loading everything at once produces mush; `frontend-design` and `ui-visual-composition` overlap and should not both drive the same pass.
- **Separate the phases.** Diverge (`idea-refine`, `frontend-design`), converge (`impeccable critique`), then specify (`design-system`). Do not critique while diverging.
- **Web → desktop translation is mandatory, not optional.** Never carry React/Next.js/Tailwind/shadcn instructions into WPF. Translate instead:
  - CSS custom properties → `ResourceDictionary` keys, primitive/semantic split preserved (`Color.Primitive.*` → `Brush.Surface.Card`).
  - utility/component CSS → `Style` + `ControlTemplate` + `Trigger`/`VisualState`.
  - responsive breakpoints → window-size ranges, pane min/max widths, DPI and text-scale resilience.
  - CSS transitions/GSAP → `Storyboard`/`VisualStateManager`, with a system "reduce motion" respect.
  - hover-only affordances → pointer **and** keyboard focus states (desktop users live on the keyboard).
- **Data-heavy means density is a feature.** For marking and grade tables: row height, tabular figures, right-aligned numerics, sticky headers, keyboard row navigation, and virtualization from day one.
- **Accessibility is a design input.** Contrast ≥ 4.5:1, never colour-only encoding, visible focus, full keyboard paths — decided during brainstorming, not repaired later.
- **Ask before inventing product facts.** Roles, marking volume, rubric structure and existing workflow are `interview-me` territory.

### 4.4 Session protocol

1. State the surface and the mode (`Operate` for Aetrix V5.5 app screens).
2. Ask only the questions that change the design (`interview-me`).
3. Produce 2–4 genuinely distinct directions, each with a token plan (palette hexes, type roles, layout concept, principles) and ASCII wireframes.
4. Critique them against usability heuristics and accessibility before recommending one.
5. Record the chosen system as tokens + component contracts, ready to become a `ResourceDictionary` later.

---

## 5. Source repositories — inspection results

All eight requested repositories exist, are public, and were cloned (shallow) to a temporary research directory outside the workspace.

| Repository | Commit | Last commit | License | Verdict |
|---|---|---|---|---|
| `anthropics/skills` | `ca45fc4` | 2026-10-28 | Apache-2.0 (examples); doc skills source-available | **Used** — `frontend-design` |
| `nextlevelbuilder/ui-ux-pro-max-skill` | `713eef5` | 2026-11-02 | MIT | **Used** — `ui-ux-pro-max`, `design-system` |
| `addyosmani/agent-skills` | `301b02b` | 2026-11-01 | MIT | **Used** — `idea-refine`, `interview-me`, `planning-and-task-breakdown` |
| `pbakaus/impeccable` | `9fadc41` | 2026-11-02 | Apache-2.0 (NOTICE.md for derived platform guidance) | **Used** — `impeccable` |
| `hueyexe/frontend-agent-skills` | `2841c07` | 2026-08-02 | MIT | **Used** — 8 of 9 skills |
| `dotnet/skills` | `5aac3c0` | 2026-11-03 | MIT | **Inspected, not used** — no WPF skill (see §6) |
| `managedcode/dotnet-skills` | `db0da0f` | 2026-11-03 | MIT | **Used** — `mvvm` (WPF skill rejected as duplicate) |
| `j4flmao/agent-skills` | `5610797` | 2026-11-03 | MIT | **Used** — `desktop-wpf`, `design-motion-design` (641-skill repo, installed selectively) |

No repository failed to clone or was abandoned. All are actively maintained within the last week except `hueyexe` (last commit 2026-08-02 — still recent enough, and its skills are largely timeless design fundamentals).

`dotnet/skills` deserves a specific note: it is the most authoritative .NET skill collection and its structure is excellent, but **it ships no WPF skill**. Its desktop offering is `dotnet-winforms/skills/winforms-expert`, whose own frontmatter says "DO NOT USE FOR: WPF or WPF XAML". Its `dotnet-blazor/skills/plan-ui-change` is Blazor-specific. Installing it would have added .NET skills with no design value for this mission.

---

## 6. Rejected candidates and why

| Candidate | Source | Reason not installed |
|---|---|---|
| `canvas-design` | anthropics | 5.6 MB of bundled TTFs for generating poster/art canvases; produces static artwork, not interface architecture. Redundant with `frontend-design` for direction work. |
| `theme-factory` | anthropics | Themes for slides/artifacts, not application design systems. |
| `brand-guidelines` | anthropics | Anthropic's own corporate identity — not applicable to Aetrix V5.5. |
| `skill-creator` | anthropics | Meta-tooling for authoring skills; useful later, no design value now. |
| `webapp-testing`, `web-artifacts-builder` | anthropics | Browser-testing harnesses and HTML artifact scaffolding; web-stack-specific. |
| `docx`, `pdf`, `pptx`, `xlsx`, `slack-gif-creator`, `internal-comms`, `mcp-builder`, `claude-api`, `algorithmic-art`, `academy-guide`, `discernment-nudge` | anthropics | Off-scope (documents, APIs, comms, art). |
| `ui-styling` | nextlevelbuilder | Hard-locked to shadcn/ui + Radix + Tailwind + React. Directly contradicts the WPF target. |
| `design` (umbrella) | nextlevelbuilder | Logo/CIP/banner/icon/social-photo generation via external AI image APIs — marketing assets, not product UI, and adds API dependencies. |
| `brand` | nextlevelbuilder | Brand-voice marketing guidance; its palette/typography duties are covered by `design-system`. |
| `banner-design`, `slides` | nextlevelbuilder | Presentation/social output; out of scope. |
| `winforms-expert` and the rest of `dotnet/skills` | dotnet | Wrong stack, explicitly excludes WPF; no design content. |
| WPF skill | managedcode | Duplicate of `desktop-wpf` with narrower coverage (no custom-control/`ControlTemplate`, virtualization or architecture references). Kept as a documented alternative in §9. |
| Other 200+ managedcode skills | managedcode | ASP.NET, MAUI, EF Core, Orleans, Blazor — out of scope. |
| `design/visual-design` (650 lines) | j4flmao | Duplicates `ui-visual-composition` + `frontend-design`; heavy repeated "Agent Protocol / Response Format / Max Response Length" boilerplate. |
| `design/design-systems` | j4flmao | Duplicates `design-systems-frontend-architecture` + `design-system`; centres on Figma variables → Style Dictionary, irrelevant to WPF. |
| `design/information-architecture`, `design/ux-research`, `design/accessibility` | j4flmao | Duplicates the hueyexe equivalents, which are cleaner and better structured. |
| `desktop/winui3`, `desktop/uwp`, `desktop/tauri`, `desktop/electron`, `desktop/qt`, `desktop/gtk`, `desktop/kde`, `desktop/gnome`, `desktop/swiftui`, `desktop/appkit`, `desktop/winforms` | j4flmao | Wrong UI stack. |
| Remaining 600+ j4flmao skills + `skill-advisor`, `bundles` | j4flmao | Backend/frontend/AI/DevOps/installer metadata; out of scope. |
| `forms-inputs-checkout` | hueyexe | Strong skill, but tuned to checkout/payment/commerce. Grading-input needs are covered by `interaction-patterns-components` + `ux-usability-foundations` + `accessibility-inclusive-design`. |
| `frontend-ui-engineering` | addyosmani | Web component file-structure/React-flavoured architecture; overlaps the hueyexe visual + interaction pair. |
| `code-review-and-quality`, `api-and-interface-design`, `test-driven-development`, etc. | addyosmani | Code-era lifecycle skills; not design brainstorming. |

**Duplication control:** only one skill was accepted per problem area. WPF appears once (`desktop-wpf`), MVVM-Toolkit once (`mvvm`), visual composition once (`ui-visual-composition`), token architecture once (`design-system`), IA once, interaction patterns once, usability once, accessibility once, UX writing once, research once, ideation once (`idea-refine`), requirements elicitation once (`interview-me`).

---

## 7. Dependencies and environment

| Item | State | Impact |
|---|---|---|
| Git | 2.56.0 | Used for cloning. |
| .NET SDK | 10.0.403 | Present; **not used** — no project was created. |
| Python 3 | **absent** | `ui-ux-pro-max/scripts/search.py` cannot run. Its CSV data and `references/quick-reference.md` are read directly instead. Optional: install Python 3 later to re-enable ranked search. |
| Node / npm / npx | absent | None needed. No `npx skills add` was used; nothing was installed from npm. |
| Third-party scripts executed | **none** | Installation was plain file copying. `impeccable`'s engine downloader was deliberately not run. |
| Application dependencies | **none introduced** | No NuGet packages, no csproj/sln, no UI libraries, no XAML, no C#. |

Total installed footprint: ~7 MB, 18 directories, Markdown + CSV + a few helper scripts.

---

## 8. Licensing and attribution

- Every installed skill carries its upstream license text at `<skill>/LICENSE` (or the upstream `LICENSE.txt` for `frontend-design`).
- MIT: `ui-ux-pro-max`, `design-system`, `impeccable`'s siblings' peers excluded, all eight hueyexe skills, `idea-refine`, `interview-me`, `planning-and-task-breakdown`, `design-motion-design`, `desktop-wpf`, `mvvm`.
- Apache-2.0: `frontend-design` (Anthropic), `impeccable` (© Peter Bakaus). Apache-2.0 requires retaining notices — both license files are preserved in place; `impeccable` additionally ships `NOTICE.md` inside its own tree referencing `ehmo/platform-design-skills` (MIT) for its iOS/Android reference files, which are retained unchanged.
- No license file was removed, renamed or edited. Attribution in each `SKILL.md` frontmatter (`author`, `license`, `version`) is untouched.
- MIT and Apache-2.0 are both permissive and compatible with commercial use inside this project. Source-available Anthropic document skills (docx/pdf/pptx/xlsx) were **not** installed.

---

## 9. Verification log

| Check | Result |
|---|---|
| All 18 directories contain a `SKILL.md` | ✅ 18/18 |
| Frontmatter valid (`---` on line 1, `name:` + `description:` present) | ✅ 18/18 |
| `name:` matches directory name (load-bearing for discovery) | ✅ 18/18 |
| Skill names unique | ✅ no duplicates |
| Supporting trees preserved (`references/`, `data/`, `scripts/`, `templates/`, `agents/`) | ✅ intact |
| `diff -rq` against upstream | Only expected deltas: added `LICENSE`, plus the documented `ui-ux-pro-max/SKILL.md` path fix |
| License present per skill | ✅ 18/18 |
| Existing files overwritten | ❌ none — `.agents/` did not exist beforehand |
| Application artefacts created | ❌ none — workspace root holds only `.agents/` and `.freebuff/` |
| Discovery location matches host loader | ✅ `.agents/skills/` confirmed from `app.asar` loader docs |
| Workspace renamed | ❌ not renamed (still `TEMP`) |

**To activate:** start a new Freebuff session in this workspace. The 18 skills will be listed by name and description; ask for a design task and the relevant ones load on demand.

### Alternative WPF skill (not installed)

If `desktop-wpf` proves too architecture-heavy later, `managedcode/dotnet-skills` → `catalog/Frameworks/WPF/skills/wpf/` is the vetted alternative: more Microsoft-docs-anchored, explicit .NET 10 guidance, with `references/patterns.md` and `references/anti-patterns.md`. Do not install both — they cover the same ground.
