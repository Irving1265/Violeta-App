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

Violeta should feel modern, protective, social, trustworthy, and mobile-first. It should not feel governmental, generic, or bureaucratic.

Use:
- Background: #13111C
- Cards/surfaces: #1E1B2E
- Primary violet: #8B5CF6
- Secondary violet: #A78BFA
- Text primary: #FFFFFF
- Text secondary: #9CA3AF
- Risk/alert: #EF4444
- Safe/location: #22C55E

When changing UI:
- Avoid clutter.
- Keep primary actions obvious.
- Ensure no horizontal overflow.
- Ensure modals are usable on mobile.
- Ensure tap targets are comfortable.
- Ensure bottom navigation and floating buttons do not overlap content.
- Use subtle, fast animations only when helpful.
- Respect accessibility and reduced motion where possible.

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
