"""Phase 1 visual regression checks using the existing isolated UI fixtures.

Run with ./.venv/bin/python scripts/ui_shared_visual_smoke.py.
No session injection, permission overrides, or production database access.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

import ui_browser_smoke as ui


def capture(page, name: str) -> None:
    page.wait_for_timeout(600)
    page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{name}.png'), full_page=True)


def dismiss_notices(page) -> None:
    for selector in ('#betaPublicModal button', '#limitedAccessModal button'):
        for button in page.locator(selector).all():
            if button.is_visible():
                button.click()
                break


def control_style(control) -> dict:
    return control.evaluate('''el => {
        const s = getComputedStyle(el), r = el.getBoundingClientRect();
        return {background: s.backgroundColor, image: s.backgroundImage,
            radius: s.borderRadius, shadow: s.boxShadow, font: s.fontSize,
            outline: s.outlineStyle, height: r.height, width: r.width,
            transform: s.transform};
    }''')


def check_auth(page, label: str) -> None:
    page.goto('/login', wait_until='domcontentloaded')
    page.wait_for_timeout(900)
    button = page.locator('form.auth-form button[type="submit"]')
    field = page.locator('input[name="password"]')
    style = control_style(button)
    assert style['background'] == 'rgb(124, 58, 237)', style
    assert style['image'] == 'none' and style['shadow'] == 'none', style
    assert style['radius'] == '8px' and style['height'] >= 48, style
    assert control_style(field)['font'] == '16px'
    capture(page, f'{label}-login')
    page.locator('input[name="login"]').focus()
    page.keyboard.press('Tab')
    assert control_style(field)['outline'] == 'solid'
    capture(page, f'{label}-focus')
    field.fill('Password123')
    toggle = page.locator('[data-password-toggle]')
    toggle.click()
    expect(field).to_have_attribute('type', 'text')
    assert control_style(toggle)['width'] >= 44
    toggle.click()
    expect(field).to_have_attribute('type', 'password')
    button.hover()
    page.wait_for_timeout(200)
    assert control_style(button)['background'] == 'rgb(109, 40, 217)'
    assert control_style(button)['transform'] == 'none'
    page.locator('input[name="login"]').fill('not-a-real-account')
    button.click()
    expect(page.locator('.alert-danger').first).to_be_visible()
    capture(page, f'{label}-login-error')
    ui.assert_no_horizontal_overflow(page, f'{label} login')


def check_staff(page, post_id: int, label: str) -> None:
    ui.login_for_layout(page, 'ui_admin', 'Password123')
    dismiss_notices(page)
    capture(page, f'{label}-feed')
    ui.assert_no_horizontal_overflow(page, f'{label} feed')
    # The fixture is a solid-color image, not real user evidence.
    expect(page.locator('.post-card').first).to_be_visible()
    page.goto(f'/post/{post_id}', wait_until='domcontentloaded')
    capture(page, f'{label}-post')
    page.locator('.report-btn').first.click()
    dialog = page.locator('#reportPostModal')
    expect(dialog).to_be_visible()
    expect(page.locator('#reportPostSubmitBtn')).to_be_disabled()
    capture(page, f'{label}-dialog-disabled')
    dialog.locator('summary').first.click()
    reason = dialog.locator('input[name="report_reason"]').first
    dialog.locator('label.report-post-choice').first.click()
    expect(reason).to_be_checked()
    expect(page.locator('#reportPostSubmitBtn')).to_be_enabled()
    capture(page, f'{label}-dialog-selected')
    dialog.get_by_role('button', name='Cancelar', exact=True).click()
    expect(dialog).not_to_be_visible()
    # Use an existing form instead of adding a visual-only component gallery.
    page.goto('/profile/edit', wait_until='domcontentloaded')
    expect(page.locator('form').first).to_be_visible()
    capture(page, f'{label}-form')
    ui.assert_no_horizontal_overflow(page, f'{label} profile form')


def main() -> None:
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    ui.reset_database()
    staff_id = ui.create_user('ui_admin', roles=[ui.ROLE_SUPER_ADMIN])
    ui.create_user('ui_limited', verified=False)
    post_id = ui.create_public_post(staff_id)
    # Avoid a workstation reverse-DNS stall; only affects test-server naming.
    with patch('socket.getfqdn', return_value='localhost'):
        server = ui.start_local_server()
    print(f'Screenshots: {ui.SCREENSHOT_DIR}', flush=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for label, width, height in [('desktop', 1440, 1000), ('mobile', 390, 844)]:
                    context = browser.new_context(
                        base_url=server.base_url,
                        viewport={'width': width, 'height': height},
                        service_workers='block',
                    )
                    try:
                        page = context.new_page()
                        page.set_default_timeout(12000)
                        check_auth(page, label)
                        check_staff(page, post_id, label)
                        page.goto('/logout')
                        ui.login_for_layout(page, 'ui_limited', 'Password123')
                        expect(page.locator('#limitedAccessModal')).to_be_visible()
                        capture(page, f'{label}-restricted')
                        dismiss_notices(page)
                        page.goto('/admin', wait_until='domcontentloaded')
                        assert page.url != f'{server.base_url}/admin', 'Restricted account entered admin'
                        print(f'{label}: passed', flush=True)
                    finally:
                        context.close()
            finally:
                browser.close()
        print(json.dumps({'status': 'passed', 'screenshots': str(ui.SCREENSHOT_DIR)}))
    finally:
        server.close()


if __name__ == '__main__':
    main()
