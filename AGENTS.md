# Violeta Agent Instructions

Violeta is a citizen safety social app. Treat privacy, location safety, verification, mobile UX, and store readiness as critical.

## Always follow

- If requirements are unclear, ask a clarifying question before implementing.
- Before important changes, review three times:
  1. Functionality
  2. Security/privacy
  3. User experience
- Do not push to GitHub unless explicitly requested.
- Do not expose sensitive user data in HTML, JSON, data attributes, srcset, scripts, public media URLs, map payloads, or API responses.
- Backend authorization is required; frontend hiding is not enough.
- Keep mobile-first UX.
- Preserve Violeta’s dark violet visual identity.
- Use clear Spanish copy and avoid accusatory language.
- Do not implement ML gender classification.
- Do not classify gender from face, voice, appearance, or video.
- For verification evidence, require consent, private access, admin-only review, and retention/deletion rules.

## Violeta unverified user rules

For unverified, pending_review, rejected, or suspended users:

- Do not expose real usernames of normal users.
- Display protected usernames as "********************".
- Do not expose real profile photos of normal users.
- Use default avatar for protected users.
- Do not expose original post image URLs of normal users.
- Use protected placeholder or backend-generated blur.
- Do not expose captions/details from normal users.
- Do not expose likes count.
- Do not expose comments count.
- Do not expose comments.
- Do not expose exact coordinates after the 3-location trial limit.
- Do not expose private profile data.
- Do not expose chat content.
- Do not expose verification evidence URLs.

Admin/super_admin posts are the exception and may be shown fully.

## UX/UI rules

[design.md](design.md) is the visual and interaction source of truth for this repository. It governs public pages, authentication, verification, staff tools, and offline/error screens. Do not maintain a separate competing palette or component specification here. Visual rules do not override security, privacy, or authorization requirements.

1. Always read `design.md` before modifying frontend UI.
2. Preserve existing working functionality, including permissions, form validation, navigation, and data handling. Do not remove behavior to simplify a layout.
3. Reuse existing components, templates, styles, and interaction patterns instead of creating unnecessary duplicates. Inspect reusable implementations before adding another variant.
4. Follow the design tokens and visual rules in `design.md`. Map its semantic roles to existing styles; do not assume every documented token already exists in code.
5. Prioritize UX, task completion, and information hierarchy over decoration. Keep primary actions obvious and secondary details subordinate.
6. Avoid generic AI-generated UI patterns. Follow the entire "Avoid AI-looking UI" section in `design.md`, including its restrictions on gradients, cards, pills, shadows, glassmorphism, and generic SaaS layouts.
7. Never introduce arbitrary colors, spacing, shadows, or border radii. Use the documented system; document a justified, task-relevant system extension in `design.md` rather than silently adding one-off values.
8. Every new screen must work on mobile and desktop. Existing screens must retain responsive behavior when changed. Prevent horizontal overflow and overlap from fixed navigation or floating buttons; keep dialogs usable on small and short viewports.
9. Maintain accessibility and semantic HTML. Follow the accessibility standards in `design.md`, including keyboard operation, visible focus, labels, contrast, accessible names, readable zoom, and reduced motion. Never shrink text to cancel the user's zoom preference.
10. Include hover, focus, active, loading, empty, and error states when relevant. Also handle disabled and success states where needed, with clear feedback and recovery actions rather than decorative placeholders.
11. Before implementing a major visual change, inspect the existing templates, styles, scripts, shared components, and affected user flows. Inspect the rendered interface when available; identify what works and preserve it instead of redesigning from assumptions.
12. After implementing UI changes, visually review the finished interface at mobile and desktop sizes, including relevant interaction states, zoom, and overflow. Automated checks supplement rather than replace this review.
13. Fix visual inconsistencies before considering the task complete. Check typography, alignment, spacing, colors, component states, and consistency with adjacent screens. If visual review cannot be performed, explicitly report the limitation and remaining verification; do not claim visual approval.
14. Do not change backend functionality unless the task requires it. A visual task is not authorization to change permissions, privacy policies, data models, or API behavior.
15. Keep the UI simple, intentional, and professional. Preserve Violeta's protective, trustworthy, community-oriented identity and clear Spanish copy; avoid clutter and unnecessary animation.

## Verification flow rules

Verification must not be just a button.

The user must submit visual evidence:
- Prefer short video captured in-app.
- Allow selfie/photo fallback.
- Require explicit consent checkbox.
- Keep evidence private.
- Show evidence only to admin/super_admin.
- Do not use ML to classify gender.
- Add retention/deletion rules or TODOs.

## Validation

Before finalizing, run relevant checks:

- git status
- git diff --check
- ./.venv/bin/python scripts/ci_checks.py

For UI changes:

- ./.venv/bin/python scripts/ui_browser_smoke.py

For logic/security changes:

- ./.venv/bin/python scripts/smoke_test_cases.py

For mobile changes, when appropriate:

- cd mobile
- npm run run:ios
- npm run run:android

## Final response format

When reporting back, include:

- What changed
- Files touched
- Validation run
- Risks/TODOs
- Whether commit was created
- Whether push was NOT done
