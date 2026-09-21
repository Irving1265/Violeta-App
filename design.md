# Violeta Design System

## Purpose and Scope

This document is the visual and interaction source of truth for future work on Violeta: a community safety platform for women to report hazards, understand nearby conditions, communicate, and manage journeys.

It governs the website, its responsive views, and the web interface inside the mobile wrapper. It also applies to authentication, verification, staff tools, support, and offline/error screens.

These are design requirements, not a claim that the current implementation already meets them. Preserve the existing dark violet identity. Apply these rules incrementally when a change is requested; this document does not authorize a redesign, new functionality, or changes to privacy and permission policies. Proposed token names describe design roles and do not imply that CSS variables already exist.

## Product Personality

- Protective: make privacy, visibility, and action consequences understandable.
- Trustworthy: describe actual capabilities and confirmed states, not aspirations.
- Calm: reduce visual noise, especially during urgent or stressful tasks.
- Community-oriented: use familiar social patterns without making popularity the main measure of safety.
- Capable: provide useful feedback and a clear way forward when something fails.
- Human: use clear, respectful Spanish and avoid blame, bureaucracy, or exaggerated reassurance.

Do not make Violeta feel like a generic SaaS dashboard, a government portal, or an alarm screen during ordinary browsing.

## Design Principles

1. Put the user's task first. Every screen must have an identifiable purpose and primary action.
2. Prefer clarity over decoration. Color, type, spacing, and grouping should explain the interface.
3. Tell the truth about safety. Recording a route, sending a notification, sharing a location, and confirming receipt are different states.
4. Use progressive disclosure. Reveal advanced filters, technical coordinates, and staff controls only where relevant.
5. Reuse patterns. A familiar action should look and behave consistently across pages.
6. Design mobile-first, then use desktop space for useful context rather than additional decoration.
7. Preserve user control. Support dismissal, cancellation, error recovery, readable zoom, and keyboard access.
8. Keep protected data protected. Visual changes must preserve backend authorization and existing data-visibility restrictions.

User-facing terminology must be consistent. Use "publicacion" for a community post and "reportar contenido" for a moderation complaint when the distinction matters. Production Spanish must include correct accents. Avoid internal labels such as "Vista usuaria comun," prototype commentary, and unexplained terms such as "ETA" or "Safety score."

## Color System

Use semantic color roles. Do not introduce a new palette for a page or override global status tokens in a page-specific stylesheet.

| Role | Value | Use |
| --- | --- | --- |
| Canvas | `#13111C` | Main application background |
| Surface | `#1E1B2E` | Cards, sheets, dialogs, navigation surfaces |
| Raised surface | `#282236` | Nested controls or raised elements that genuinely need separation |
| Subtle divider | `#2D2438` | Decorative separation; not the sole boundary of an interactive control |
| Control boundary | `#766B82` | Input and control outlines when a visible boundary is necessary |
| Brand violet | `#8B5CF6` | Brand accents, selection indicators, progress |
| Action violet | `#7C3AED` | Primary button background with white text |
| Action hover | `#6D28D9` | Hover/pressed emphasis for primary actions |
| Light violet | `#A78BFA` | Links, focus rings, small accent text on dark surfaces |
| Primary text | `#E9E3EF` | Main body text and headings |
| Secondary text | `#948B9C` | Supporting text on canvas/surface; verify on other backgrounds |
| On-action text | `#FFFFFF` | Text and icons on action-violet fills |
| Success | `#22C55E` | Confirmed completion and current-location markers, with labels |
| Warning | `#F59E0B` | Pending conditions and recoverable cautions |
| Danger | `#EF4444` | Destructive actions, critical errors, emergency access |
| Information | `#60A5FA` | Neutral informational status when violet would imply an action |
| Modal scrim | `rgba(0, 0, 0, 0.60)` | Background dimming for modal dialogs |

White on brand violet is approximately 4.23:1; do not use that pairing for normal-size text. White on action violet is approximately 5.70:1. Use action violet for ordinary filled primary buttons.

Status colors are accents, not automatically approved text/background combinations. Verify contrast in every actual state, including hover, selected, error, and disabled appearances. Never communicate status through color alone.

Reserve red for danger and destructive actions. Creating a publication is a violet action, not a red action. A green map marker identifies the user's location only when labeled; it must not imply that a place is verified safe.

## Typography Hierarchy

Use the current system sans-serif stack consistently:

`system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`

Do not declare Inter or another font on one isolated screen. A future font change must be an explicit system-wide decision with loading, fallback, and performance verification.

| Role | Size | Weight | Line height |
| --- | --- | --- | --- |
| Page title | `1.75rem` mobile; up to `2rem` desktop | 700 | 1.2 |
| Section title | `1.25rem` | 600-700 | 1.3 |
| Card/dialog title | `1.125rem` | 600-700 | 1.35 |
| Body, inputs | `1rem` | 400 | 1.5 |
| Buttons and navigation | `0.9375rem` to `1rem` | 600 | 1.4 |
| Labels and supporting text | `0.875rem` | 400-600 | 1.45 |
| Brief metadata | `0.8125rem` minimum | 400-500 | 1.4 |

Keep essential instructions and errors at least `0.875rem`. Input text remains at least `1rem`, including on mobile. Do not shrink typography to compensate for browser zoom or screen density.

Use sentence case for headings and actions. Avoid long uppercase labels and excessive letter spacing. Use tabular numerals for timers and counts; reserve monospace for technical data. Keep reading text near 60-70 characters per line. Do not truncate essential instructions, errors, or consent copy.

## Spacing System

Use a shared 4px-based scale, expressed in rem where appropriate:

| Token | Size | Typical use |
| --- | --- | --- |
| Space 1 | 4px / `0.25rem` | Closely related icon/text details |
| Space 2 | 8px / `0.5rem` | Label-to-control spacing, compact item gaps |
| Space 3 | 12px / `0.75rem` | Related controls, compact list padding |
| Space 4 | 16px / `1rem` | Mobile page gutters and card padding |
| Space 6 | 24px / `1.5rem` | Desktop card padding and section gaps |
| Space 8 | 32px / `2rem` | Major page sections |
| Space 12 | 48px / `3rem` | Separation between distinct tasks on spacious layouts |

Default form-field separation is 16-24px. Default button-group gap is 8-12px. Use 16px mobile gutters and 24-32px desktop gutters. Safe-area insets are additional constraints, not substitutes for gutters.

Use proximity to establish groups before adding borders or containers. Avoid arbitrary values such as `0.55rem` and `0.85rem` unless a documented optical adjustment is needed.

## Border Radius Rules

| Role | Radius |
| --- | --- |
| Small badges and thumbnails | 4-8px |
| Inputs and ordinary buttons | 8px |
| Cards and grouped panels | 12px |
| Dialogs and mobile sheet top corners | 16px |
| Avatars and emergency control | Circular |
| Filter chips | Full radius only for short, selectable filters |

Do not make every label a pill or every section a rounded container. Nested elements must not repeatedly create new rounded frames. Large radii are not a substitute for hierarchy.

## Shadows

Use borders and surface contrast before shadows. Most cards and navigation items need no shadow.

- Low elevation: `0 2px 8px rgba(0, 0, 0, 0.16)` for a floating contextual control.
- Overlay elevation: `0 12px 32px rgba(0, 0, 0, 0.32)` for a dialog or sheet above content.
- Use a single elevation treatment per component. Avoid colored glow, stacked shadows, and animated shadow growth.
- Emergency access may have restrained elevation for discoverability, without pulsing or glowing continuously.

## Buttons

- Primary: action-violet fill, white text, one primary action per task region.
- Secondary: neutral surface or transparent fill with a clear boundary and readable text.
- Tertiary: text or icon/text for low-emphasis actions; maintain a full hit area.
- Destructive: explicitly labeled, separated from routine actions, and red where appropriate. Confirm consequential deletion with the item and consequence stated.
- Icon-only: allowed for familiar utilities when space is limited; always provide an accessible name. Tooltips supplement rather than replace labels.

Use a minimum 44 by 44 CSS px target, with 48px height preferred for mobile primary actions. The icon can be smaller than its hit area. Keep sibling actions aligned and use consistent padding.

Use verbs that describe the result: "Publicar reporte," "Guardar cambios," or "Verificar mi cuenta." "Siguiente" is acceptable inside a clearly labeled sequence. Explain disabled actions beside the control; do not rely on hover.

Loading buttons retain their dimensions, prevent duplicate submission, and show a short action-specific label. Success must follow confirmation, not a simulated timer. Do not enlarge buttons on hover.

## Forms

- Give every field a persistent visible label. Placeholders provide examples, not labels.
- Distinguish required and optional information in text. Use appropriate input types, autocomplete, and mobile input modes.
- Group related choices with a fieldset and legend. Selected choices must expose their state programmatically.
- Place help and errors next to the relevant field and connect them with `aria-describedby`. Mark invalid fields with `aria-invalid`.
- Preserve entered information after recoverable failures. Validate without interrupting ordinary typing; focus the first invalid field after a failed submission.
- Keep password visibility controls anchored to the input row even when error text expands below it.
- Multi-step forms show the current step and total, support going back without losing work, and move focus to a meaningful heading or control.
- Request camera, microphone, and location access at the relevant moment, with a clear reason and recovery path if denied.
- If video capture falls back to silent recording, explain the changed requirement. Provide a support-assisted path when the normal verification method cannot be used, subject to the verification policy.

## Cards

Use cards for independent entities or meaningful task groups: a publication, a verification request, or an active journey. Use ordinary sections or list rows for supporting text and simple settings.

Publication cards should prioritize the hazard/category, location, recency, evidence, and description. Author metadata and social counts must not overwhelm the report. Preserve privacy-safe placeholders for protected content.

Use 16px padding on compact cards and 24px where space allows. Full-width media may sit outside padded text regions. Avoid cards inside cards unless the inner element is independently actionable.

For unavailable images, preserve layout, explain the failure, and provide retry where possible. A broken-image icon or generic alt text is not an adequate user-facing state. Verification, capture, and account dialogs use the same dark surface family as the app unless a future exception is explicitly approved.

## Navigation

Keep names and destinations consistent:

- Inicio: the community feed; do not title this page "Explorar."
- Explorar: the map of nearby reports and route planning.
- Seguridad: journeys, trusted contacts, and journey history.
- Chat: conversations and community rooms.
- Perfil: the user's profile and account settings.

All five destinations must remain discoverable on mobile and desktop. Emergency access is a distinct action, not an unlabeled replacement for a destination. Staff workspaces appear only to authorized roles and must not crowd ordinary navigation.

Desktop navigation retains the existing 250px sidebar where it fits. Mobile navigation uses icons with short visible labels. Active destinations use both visual emphasis and `aria-current="page"`.

Provide a skip-to-main-content link. Preserve normal browser back behavior. Keep emergency access recognizable and reachable; calling must not depend on successful location lookup or notification delivery. Do not place it beneath overlays that prevent access during normal app use.

## Icons

Use the existing Font Awesome library with a consistent style for each role. Do not mix unrelated icon libraries, emoji, and custom drawings for the same action.

Use 16px icons beside compact text, 20px for ordinary controls, and 24px for primary navigation. Decorative icons use `aria-hidden="true"`; meaningful icon-only controls get a label on the control itself.

Reuse the same category icon in filters, publication creation, cards, and maps. An ellipsis opens an action menu; use a flag or explicit text for reporting content. Keep role badges visually distinct from identity-verification and moderation states, and explain their meanings.

## Layout and Grid

- Mobile: one primary column with 16px gutters.
- Tablet: retain one main task column unless two columns fit at readable sizes.
- Desktop: use a flexible grid with up to 12 columns, 24px gaps, and an approximately 1200px maximum content width excluding the navigation sidebar.
- Reading and feed content should generally remain within 640-720px. Forms should generally remain within 480-640px.
- Supplemental feed widgets appear only when the feed retains its usable width; hide or relocate them before compressing the main task.
- Chat may use a conversation list and message pane when both fit. Switch to list/detail navigation when they do not.
- Maps retain a usable visible area. Put detailed filters and route output into a collapsible panel rather than stacking floating cards over the map.
- Admin screens may be denser, but use the same tokens and controls. Put operational detail behind sections rather than increasing visual decoration.

Avoid horizontal page overflow. Keep necessary horizontal scrolling inside explicitly labeled regions such as data tables. Allocate space for fixed navigation, floating controls, sticky headers, and mobile safe areas. Keep emergency and publication hit areas separate from each other and from content actions.

## Responsive Breakpoints

These are shared target breakpoints for future consolidation, not a description of every current stylesheet.

| Range | Layout rule |
| --- | --- |
| Below 768px | Mobile navigation, single-column tasks, sheet or full-height dialog where needed |
| 768-1023px | Tablet; use the sidebar only where content remains usable, otherwise retain mobile navigation |
| 1024-1279px | Desktop sidebar and flexible main column; add secondary panes only if they fit |
| 1280px and above | Full desktop composition within content-width limits |

Use content fit to choose a layout within these ranges. Do not create a new breakpoint for each visual defect. Verify at 320, 375, 390, 768, 1024, and 1440 CSS px, plus landscape and short-window cases.

Do not infer browser zoom from `devicePixelRatio` or reduce font sizes to cancel zoom. Allow zoom to trigger natural reflow. Prefer `dvh`/`svh` with appropriate fallbacks for viewport-height layouts. Dialogs and croppers must scroll or resize so their actions remain reachable with an on-screen keyboard.

## Empty States

Distinguish an empty community, no matching filters, an empty conversation, missing permissions, and failed loading.

Use a short explanation and one relevant next action. For filtered results, show the active constraints and offer "Limpiar filtros." For an empty profile, explain how to create the first report only when the viewer owns that profile and can publish.

Do not fill empty states with oversized illustrations, large promotional headings, or multiple unrelated buttons. Do not describe unavailable or missing safety data as a safe result.

## Loading States

Use layout-matched skeletons for initial page content, a small spinner for a localized operation, and progress only when it can be measured. Preserve dimensions to reduce layout shifts.

Announce relevant loading states with `aria-busy` or an appropriate live region. Keep other usable content interactive. Give long-running or failed operations a recovery path. Do not leave a perpetual spinner after a failed request.

Cached, stale, recording, queued, sent, delivered, and reviewed are separate states. Label them accurately. Never imply successful sharing, publication, or delivery while the server has not confirmed it.

## Error States

Use clear Spanish: what failed, whether work was preserved, and what the user can do next. Avoid technical exceptions, blame, and generic "Error" messages without recovery.

- Field errors remain next to their field until resolved.
- Submission errors retain the user's work and offer retry when safe.
- Permission errors explain how to retry or use an approved alternative.
- Offline screens explain what is available and what cannot be submitted; do not imply a report was sent.
- Partial loading failures preserve successful sections.
- Critical errors and decisions never disappear automatically. Only nonessential confirmations may auto-dismiss.

Use inline errors for local problems and a page-level message for page-level failure. Avoid native browser `alert()` for ordinary application feedback. State-changing retries must not silently create duplicate reports or messages.

## Accessibility Standards

Target WCAG 2.2 AA. This is an implementation and verification requirement, not a claim of current compliance.

- Text contrast: at least 4.5:1 for normal text and 3:1 for qualifying large text. Essential control boundaries, state indicators, and meaningful graphics need at least 3:1 against adjacent colors.
- Maintain a 44px minimum product target size for interactive controls where feasible; use 48px for primary mobile actions.
- All actions must work with a keyboard, including emergency activation, filters, sheet toggles, and upload controls. No drag-only or pointer-only path to essential functionality.
- Provide a visible focus indicator, preferably a 2px light-violet outline with offset. Never remove the outline without an equally visible replacement.
- Modal dialogs move focus inside, contain tab navigation, support appropriate dismissal, make the background inert, and restore focus on close. Protect unsaved work when dismissal would discard it.
- Use semantic headings, landmarks, buttons, links, labels, and grouped controls. Do not apply tab or listbox roles without the associated keyboard behavior.
- Announce important validation and submission outcomes. Do not announce a timer on every animation frame or second when a milestone announcement is sufficient.
- Provide contextual alt text for useful images, respecting visibility restrictions. Decorative images have empty alt text.
- Support 200% text resizing and reflow at an effective 320 CSS px width, including high browser zoom. Maps and necessary data tables may scroll within their own regions; adjacent controls must remain usable.
- Offer a textual way to understand relevant map results. Do not rely solely on red/green markers or the map canvas.
- Verify keyboard-only use, VoiceOver and another appropriate screen reader, reduced motion, and real mobile devices before claiming accessibility conformance.

## Interaction and Animation Principles

Use motion only to explain a state change, spatial relationship, or action outcome.

- Hover/focus feedback: 120-160ms, primarily color or border changes.
- Small state changes: 160-200ms.
- Dialogs and sheets: 180-240ms, subtle opacity or short translation.
- Avoid elastic motion, large scale changes, continuous glow, and repeated decorative animation.
- Honor `prefers-reduced-motion` in both CSS and JavaScript; remove nonessential motion while keeping status visible.
- Use optimistic updates only for reversible actions with clear rollback. Do not optimistically confirm emergency delivery, verification approval, or publication.
- Preserve scroll and focus through asynchronous updates. Do not reload a page in a way that discards an active task merely to refresh a status.
- Clearly mark unavailable features before users try them. Avoid presenting a working-looking primary control that only reveals "Proximamente" after activation.

## Avoid AI-looking UI

The following are prohibited by default:

- Excessive gradients: no decorative gradient on every background, card, or button. Flat semantic surfaces are the default.
- Excessive cards: do not turn every paragraph, metric, or field group into a separate card.
- Excessive rounded containers: avoid multiple nested rounded frames and oversized radii on routine components.
- Excessive shadows: do not stack shadows or use glow to make every element prominent.
- Giant hero text without purpose: product tasks do not need landing-page-sized slogans.
- Random decorative icons: an icon must communicate an action, category, destination, or status.
- Unnecessary pills: reserve chips for genuine filters and compact state indicators, not ordinary labels.
- Excessive whitespace: spacing must clarify groups without hiding useful content or pushing actions away.
- Inconsistent spacing: use the shared scale instead of inventing gaps for each screen.
- Random colors: use the semantic palette; no unrelated palette per feature.
- Glassmorphism unless justified: translucent blur is permitted only when preserving context over a map or similar surface materially helps the task and contrast/performance are verified.
- Generic SaaS-looking layouts: no decorative KPI grids, repetitive feature tiles, marketing heroes, or dashboard ornaments unrelated to the community safety task. Real admin metrics are allowed when operationally useful.

Any exception must document the user benefit, affected component, and accessibility implications. Visual novelty alone is not a justification.

## Applying This Source of Truth

### Approved Home Reference (September 18, 2026)

The supplied HTML is the visual target for home only, scoped with `.home-page` and
`home_reference.css`. Use its flat #12101C canvas, #0F0D17 sidebar, #1A1825 cards,
#211D30 raised controls, 220px desktop navigation, 300px right rail (270px below
1150px), 1070px content limit and 26px column gap. The rail hides below 1001px;
the existing mobile navigation destinations remain unchanged below 768px.
Home retains the reference's "Explorar" heading as an explicit user exception.

Reports place their privacy-safe description before category labels and inset 4:3
media, followed by compact social actions. Use 18px desktop card corners, 15px
media corners and 14px mobile gutters; mobile posts are separated without outer
rounded cards. Reuse the existing caption, map, comments and protected-content
logic. Do not copy demonstration counts, coordinates, photos or fake interactions.
The real camera composer and its permissions must remain unchanged.

The supplied red create button and category colors are scoped reference exceptions:
#E54861 create/emergency controls, #F7BD56 lighting, #8EB9FF sidewalk, #FF8E9E
unsafe and #5BDEB1 vacant categories on their matching 13% tints. Nearby-map
distance colors use violet for the labeled current position, green/amber/red for
distance, never a safety score. No marker may call a fallback position the user's
location. The September 20 follow-up explicitly requests the reference's exact
visual sizing, colors, widgets and menus, including mobile navigation styling.
Use the supplied compact type scale (.58rem map legend, .65rem activity counts,
.71rem activity names, .89rem captions), #81798D muted text, 35/38px filters,
56px mobile emergency control and reference header blur. These are home-only
exceptions; smaller text and muted contrast are known accessibility tradeoffs,
not an accessibility compliance claim. Retain keyboard focus, reduced motion,
browser zoom, semantic labels and real permission checks. The weather is a
two-column compact row; activity uses category icons and count pills rather than
full sentences. These exceptions are not global tokens.

### Shared Desktop Menu

The September 20 shared-menu follow-up promotes the home desktop sidebar to all
pages using base.html, via sidebar.css: 220px width, reference typography,
colors and spacing, profile avatar, support and emergency actions. Preserve role
conditions, limited-access status and the configured version label. Authentication
pages without a sidebar remain unchanged; this change does not restyle mobile
navigation. Other home reference styles remain scoped to home.

### Approved Profile Reference

The supplied September 20 profile HTML governs profile content only. Preserve
the shared desktop and mobile menus. Reuse its exact cover/wellbeing SVG assets,
Caveat quotes, Inter typography, #10101A canvas, #171624 surfaces, 304px hero,
124px avatar (84px on phones), four-column report cards and 272px wellbeing rail.
At 600px, activity collapses into an accessible disclosure and reports use two
columns. Keep real identity, moderation, verification, pagination, delete and
camera publication behavior. Do not claim the profile is private or invent
monthly impact. Until supported, show impact as unavailable and replace the
unsupported cover editor with the real profile editor. Compact type and the
reference gradients are explicit user-directed exceptions, not global tokens.

### Approved Login Reference

The user-supplied September 2026 login reference is a scoped exception, implemented in `login_page.css` and `login.html`, not a new global theme. Preserve its 440px desktop auth column (410px below 1200px), dark `#12101C` canvas, `#1A1825` panel, `#211D30` inputs, 24px panel radius (22px mobile), 14px control radius and system font. The revised compact header uses the Violeta wordmark and Beta v1.2 inside the form panel instead of the circular illustration and duplicate exterior logo. Supporting text uses `#A9A1B3`; inputs retain the shared accessible boundary and 16px text instead of the reference's smaller size.

Use 8px form gaps, 4px label gaps, 16px header separation and 24px panel padding (20px vertical/16px horizontal on small phones). Remove the unused bottom-navigation clearance on login only. Fit the normal form into portrait phone and desktop viewports; allow scrolling for short landscape screens, errors, keyboard access and enlarged text rather than clipping content or suppressing zoom.

Desktop retains the reference's light map, dark text, geographic landmark card and bottom category filters. White/light-violet map controls, their category icon colors and the two map-edge fades are localized reference treatments, not permission to add gradients or light panels elsewhere. They preserve readable text over map tiles. On mobile/touch screens the existing map exclusion remains: only the scrollable login form is loaded. Keep 44px touch targets, keyboard focus and fixed input-row password toggle alignment when error copy expands.

Use real authentication, CSRF, registration/recovery routes and authorized hotspot data. Never copy the reference's fake login toasts or demonstration reports into production. Google is enabled only when server-side OAuth credentials and callback URL are configured; otherwise show its unavailable state. New Google accounts must complete the same eligibility declaration as local registration and remain unverified. Existing accounts require password confirmation before linking. Do not promise absolute location privacy through unverified marketing copy. Landmark changes are user-controlled, not an auto-advancing carousel. No navigation/menu changes are authorized by this login work.

When a UI change is requested, use existing components first and align touched components with these rules. Explicit task requirements and privacy/permission rules remain authoritative. Update this document when a deliberate design-system decision changes; do not silently create a parallel system in page-specific CSS.

Review the relevant loading, empty, error, restricted, and success states alongside the main state. Validate the changed flow at mobile and desktop sizes, with zoom and keyboard navigation. Record any exception or remaining verification gap.
