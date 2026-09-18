# Login Reference Integration

## Scope

Implemented the supplied HTML reference in the existing Flask login, not a standalone preview. Navigation, permissions, backend authentication and registration/recovery routes are unchanged. No commit, push or deployment was performed.

The composition uses the dark auth panel, circular Violeta illustration, labeled fields, violet submit button, desktop map, landmark preview and bottom category filters. Mobile/touch requests retain the existing exclusion of map assets. The CSS is scoped to `.login-page`; its approved reference exceptions are documented in design.md.

## Production Differences From the Preview

- The form uses the existing POST action and CSRF token, preserves the entered username after an unsuccessful attempt and never repopulates passwords. Submission has a loading state that resets on browser back.
- Google is visibly disabled with an explanation because this repository has no Google OAuth integration. There is no fake success or demonstration login handler.
- The map requests the existing public hotspot endpoint. No invented incidents are shipped. Loading, empty and failed requests have distinct messages; failed refreshes clear stale markers.
- Registration and password recovery are real links. Privacy copy links to the actual policy rather than promising absolute location privacy.
- Landmark images use the supplied external Wikimedia URLs with a labeled local-image fallback. Switching is manual rather than an automatic carousel. Remote imagery and map tiles still depend on third-party availability.
- Inputs remain 16px, interactive targets at least 44px, and errors have accessible associations and Spanish text. The eye button stays anchored to the input even when error messages appear.

## Files

- `templates/login.html`: composition, native field validation, actual submission and existing map integration.
- `static/css/login_page.css`: isolated reference styles and responsive behavior.
- `static/js/app_core.js`: skip generic validation only for explicitly native-validation forms; guard navigation event targets that are not elements.
- `templates/base.html`: cache version for the updated core script only.
- `scripts/ui_login_design_smoke.py`: isolated browser checks and screenshots, including test-only mocked marker/error responses.
- `scripts/smoke_test_cases.py`: password-toggle regression now checks the extracted login stylesheet.
- `design.md`: scoped reference exceptions.

## Verification and Limits

The browser suite covers 1440x1000, 1024x768, 768x1024, 390x844, 320x700 and 844x390, field errors, password visibility, horizontal overflow, real login success/failure, recovery/registration destinations, map filters, empty/failed/populated map states and client-side exceptions. Populated map fixture data exists only in the test process, not the application.

The final six-size suite passed after guarding captured non-element navigation events and hiding outdated landmark imagery during image loading. Final captures: `/var/folders/ds/vblgzp7j15g7ct4dxscy8rth0000gn/T/violeta-ui-smoke-2i56rcny/screenshots`; the final desktop login was visually reviewed alongside the earlier mobile captures.

The 51 functional checks passed in 20.476 seconds. Python compilation and Bandit completed with no High/Medium severity findings. The overall CI preflight remains blocked by intentionally missing SMTP configuration in the isolated test environment, with expected SQLite/local-upload warnings.

The legacy `ui_browser_smoke.py` still fails when its ordinary-user fixture tries to open the composer with inconsistent verification fields, as in the preceding work. This login-specific suite tests actual authentication independently without changing production permission checks.

Reference/baseline screenshots: `/var/folders/ds/vblgzp7j15g7ct4dxscy8rth0000gn/T/violeta-ui-smoke-75qze4p3/screenshots`.
Reviewed desktop, mobile and compact-desktop screenshots: `/var/folders/ds/vblgzp7j15g7ct4dxscy8rth0000gn/T/violeta-ui-smoke-jrqt35fc/screenshots`.
Logs: `/tmp/violeta-login-ci.log`, `/tmp/violeta-login-legacy.log`, `/tmp/violeta-login-final.log`.

Real-device Safari, screen-reader verification and live Google OAuth are not covered. Local browser checks are not a claim of complete accessibility conformance.
