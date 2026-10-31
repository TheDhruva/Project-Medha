# MEDHA Frontend Design System — Persistent AI Instructions

> **Purpose:** Establish MEDHA's visual and UX direction before redesigning the frontend. Treat this file as the source of truth for future UI work. These rules guide presentation, not product behavior.

## Instruction to the coding agent

Before making any UI changes, read this file completely and inspect the existing frontend architecture. Follow the applicable frontend/design skills already available in the environment. If a skill manager or skill directory is available, search for and use relevant, compatible skills for:

- React and Next.js frontend best practices
- UI/UX design and visual hierarchy
- Accessible component design
- Frontend testing and safe refactoring

Prefer established, maintained skills and official documentation. Do not claim a skill is installed or used unless you have verified it. Do not blindly install multiple overlapping skills. If no suitable skill is available, continue using the design rules in this file and clearly state that no additional skill was used.

Useful references:
- Vercel Agent Skills: https://github.com/vercel-labs/agent-skills
- shadcn/ui: https://ui.shadcn.com
- Geist font: https://vercel.com/font
- Linear: https://linear.app
- Vercel: https://vercel.com

Use these as references, not as templates to copy. Preserve MEDHA's product identity and existing information architecture unless a requested change explicitly requires otherwise.

---

## 1. Product design direction

**Design language:** Swiss minimalism + refined developer-tool SaaS + restrained, functional data visualization.

MEDHA is an engineering product for repository analysis, code/security assessment, verification, and deployment workflows. It must feel trustworthy, precise, calm, and operational—not like a marketing landing page.

Priorities, in order:

1. Correct information and clear system state
2. Readability and fast scanning
3. Actionable findings and diagnostics
4. Consistency and accessibility
5. Visual polish and subtle motion

Avoid visual noise, decorative gradients, excessive shadows, glassmorphism, neon colors, oversized headings, gratuitous animation, and generic AI-generated dashboard patterns.

## 2. Color tokens

Use these as the default light-theme palette. First inspect the existing theme/token setup and consolidate it rather than introducing conflicting CSS variables.

| Token | Hex | Purpose |
|---|---|---|
| App background | `#F8F9FB` | Main page background |
| Surface | `#FFFFFF` | Cards, panels, dialogs |
| Primary text | `#17191F` | Headings and key values |
| Secondary text | `#686D78` | Supporting text and metadata |
| Border | `#E5E7EB` | Dividers, outlines, separators |
| Primary accent | `#635BFF` | Primary actions and active navigation |
| Accent hover | `#5145E5` | Hover/pressed states |
| Success | `#16803D` | Passed checks and successful operations |
| Warning | `#B76E00` | Warnings and items needing attention |
| Critical | `#D92D3A` | Failed checks and critical findings |
| Informational | `#2878C8` | Neutral informational states |

Guidelines:
- Keep the interface predominantly neutral; color should communicate meaning, not decorate every component.
- Use semantic colors consistently. Do not use color alone to communicate status; include a label or icon.
- **Deployment state and security severity are different concepts.** A successful deployment may still have security findings. Represent them separately.
- Check contrast and readability, especially for small text, badges, chart labels, and disabled controls.
- Do not recolor every existing component independently. Define/reuse shared design tokens.

## 3. Typography

**Primary typeface:** Geist Sans.  
**Monospace typeface:** Geist Mono for code, commands, logs, commit hashes, and technical identifiers.

Before adding fonts or dependencies, check whether they are already installed and how fonts are loaded. Reuse existing compatible setup where possible. Provide sensible system fallbacks.

Suggested scale:

| Use | Size | Weight |
|---|---:|---:|
| Page title | 24px | 600 |
| Section title | 16px | 600 |
| Card title | 14px | 600 |
| Body / controls | 14px | 400–500 |
| Metadata | 12px | 400 |
| Key metric | 28–32px | 600 |
| Code / logs | 12–13px | 400 |

Use a compact, consistent type scale. Do not create a new font size or weight for every component. Maintain readable line height and responsive behavior.

## 4. Content-first UI — remove unnecessary copy

**Default hierarchy: Title → useful content → explanation only when it adds information.**

MEDHA should not read like a marketing website or an AI-generated template. Users should be able to scan the page and understand the state quickly.

Rules:
- Do not add eyebrow labels above every heading.
- Do not add subtitles that merely restate the title.
- Do not repeat the same information in a page title, card title, badge, and paragraph.
- Do not add introductory paragraphs to dashboards unless they communicate a decision-critical fact.
- Do not add decorative labels such as “OVERVIEW,” “INTELLIGENCE,” or “SYSTEM STATUS” just to fill space.
- Prefer concise, specific titles and show the actual data immediately.
- Use tooltips for genuinely secondary explanations.
- Use expandable sections for detailed logs, scoring methodology, raw diagnostics, and advanced technical information.
- Explain important decisions: scorecards need a clear basis when requested; security findings need evidence and remediation; failures need a useful cause and next action.
- Empty, loading, error, and success states must be concise and informative—not generic filler.
- Never remove text that is necessary for accessibility, context, safety, or understanding a non-obvious action merely to make the UI shorter.

Example:

**Avoid**
- “REPOSITORY HEALTH”
- “Your repository's overall health and quality metrics”
- “Repository Health Overview”
- “Your codebase is performing well.”

**Prefer**
- “Repository Health”
- Show the relevant metrics directly.

Every visible text element should either identify something, show useful information, guide an action, or explain a meaningful result. If it does none of these, remove it.

## 5. Layout and components

- Prefer clear alignment, consistent spacing, restrained borders, and predictable component behavior.
- Use whitespace to establish hierarchy, not to hide a lack of content.
- Keep information density appropriate for an engineering dashboard.
- Make critical issues and failed workflows easy to locate without making the whole UI visually alarming.
- Keep controls visually and behaviorally consistent.
- Use responsive layouts and avoid horizontal overflow at supported viewport widths.
- Reuse existing components and design tokens where reasonable; do not create parallel component systems.
- Use accessible semantic HTML, keyboard support, visible focus states, and appropriately labeled controls.
- Avoid adding dependencies for visual effects that can be implemented safely with existing tools.

### Preserve MEDHA's existing scorecards

The four existing scorecards are:
- Code Quality
- Security Posture
- Verification Confidence
- Deployment Readiness

**Keep their semicircular fill-up indicators. Do not replace them with generic circular charts, plain numbers, or a new layout unless explicitly requested.** Refine their typography, spacing, track, indicator, labels, and accessibility while preserving their purpose and existing data contracts.

## 6. Motion and interaction

- Prefer subtle, short transitions that improve feedback or orientation.
- Respect `prefers-reduced-motion`.
- Avoid decorative motion, continuous animations, scroll hijacking, and heavy effects.
- Never delay important information behind an animation.
- Analysis progress must reflect real backend/task state, not simulated progress.
- Errors and completed states must appear promptly and remain understandable.
- Loading, retry, disabled, success, and failure states must be explicitly designed.

## 7. Non-negotiable engineering safeguards

A visual redesign must not silently change product behavior.

Before editing:
1. Inspect the repository structure, package scripts, current component system, design tokens, routing, API client, and existing tests.
2. Identify the exact pages/components involved and their dependencies.
3. Record the relevant baseline test/build status when feasible.
4. Check the installed framework and library versions before choosing APIs or copying examples.

During implementation:
- Treat backend behavior, API contracts, request/response shapes, scoring logic, repository analysis, orchestration, deployment behavior, and persistence as out of scope for a visual redesign.
- Do not modify backend files unless the task explicitly requires it and the reason is explained.
- Do not replace real API data with mock, hardcoded, or fabricated data.
- Do not remove features, actions, error details, accessibility labels, or diagnostic states to simplify the appearance.
- Do not rewrite entire pages or the component architecture when a smaller targeted refactor will work.
- Avoid unrelated cleanup and opportunistic refactoring.
- Preserve existing routing, query parameters, state transitions, and user workflows.
- Do not add dependencies without explaining why they are needed.
- If a visual request conflicts with existing behavior or the codebase's architecture, explain the trade-off before taking a risky approach.

Work in small, reviewable increments. Prefer one page or component group at a time.

## 8. Verification requirements

After each meaningful change:
1. Run the most relevant existing tests.
2. Run lint/type checks and a production build when available and practical.
3. Fix regressions introduced by the change; do not conceal failures.
4. Verify loading, success, empty, and error states for affected workflows.
5. Check responsive layout, keyboard interaction, focus visibility, and text contrast.
6. Confirm that real data and existing actions still work.

Do not claim a test passed unless it was actually run. Report any command that could not be run and any known pre-existing failures separately from regressions.

## 9. Required workflow before a full redesign

Do not start a sweeping redesign immediately.

**Phase A — Audit**
- Map the frontend routes and major components.
- Identify shared layout, navigation, cards, scorecards, tables, dialogs, status indicators, and error views.
- Identify existing tokens and component libraries.
- Note functional risks and test coverage.
- Report the findings briefly.

**Phase B — Plan**
- Propose a small, ordered implementation plan.
- Identify which components will change and which must remain behaviorally unchanged.
- Confirm the design tokens and typography can be introduced without conflicting with existing styles.

**Phase C — Implement**
- Make focused, incremental changes.
- Keep the existing semicircular scorecards.
- Remove redundant copy and improve hierarchy.
- Preserve functional behavior and real data.

**Phase D — Verify**
- Run tests, type checks, lint, and build as available.
- Inspect changed states and responsive behavior.
- Summarize changed files, visual improvements, verification results, and unresolved issues.

If the user asks only for an audit or plan, do not implement changes until asked.

## 10. Definition of done

A UI change is complete only when:
- It follows this design system.
- It removes redundant copy without losing necessary meaning.
- It preserves existing functionality and real data.
- It keeps the semicircular scorecards.
- It has no knowingly introduced TypeScript, lint, test, or build regressions.
- Relevant loading, empty, success, and failure states remain usable.
- The implementation is consistent with existing architecture and accessible interaction patterns.
- The final response lists the main changes, files touched, checks actually run, and any outstanding risks.

**Standing principle:** If a piece of UI does not improve comprehension, decision-making, or task completion, question whether it belongs. Make MEDHA feel like a precise engineering instrument—not a marketing page.
