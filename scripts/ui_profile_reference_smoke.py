"""Profile reference checks with disposable data, never production accounts."""
import logging
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import ui_browser_smoke as ui


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    ui.reset_database()
    user_id = ui.create_user('profile_review')
    ui.create_user('profile_other')
    ui.create_user('profile_limited', verified=False)
    for _ in range(4):
        ui.create_public_post(user_id)
    with patch('socket.getfqdn', return_value='localhost'):
        server = ui.start_local_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(base_url=server.base_url, service_workers='block')
            page = context.new_page()
            ui.login_for_layout(page, 'profile_review', 'Password123')
            page.goto('/user/profile_review')
            expect(page.locator('.profile-name')).to_have_text('profile_review')
            for width in [1440, 1024, 768, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(500)
                ui.assert_no_horizontal_overflow(page, f'profile {width}')
                expect(page.locator('.grid-item')).to_have_count(4)
                if width <= 600:
                    toggle = page.locator('#activityToggle')
                    expect(toggle).to_have_attribute('aria-expanded', 'false')
                    toggle.click()
                    expect(toggle).to_have_attribute('aria-expanded', 'true')
                    expect(page.locator('#activityPanel')).to_have_attribute('aria-hidden', 'false')
                    toggle.click()
                page.screenshot(path=str(ui.SCREENSHOT_DIR / f'profile-{width}.png'), full_page=True)
            page.locator('.grid-delete-btn').first.click()
            expect(page.locator('#profileDeleteModal')).to_be_visible()
            page.get_by_role('button', name='Cancelar', exact=True).click()
            expect(page.locator('#profileDeleteModal')).to_be_hidden()
            page.locator('.publish-button').click()
            expect(page.locator('#postCreateModal')).to_be_visible()
            page.evaluate('window.PostCreateModal.close()')
            page.goto('/user/profile_other')
            expect(page.locator('.profile-name')).to_have_text('profile_other')
            expect(page.locator('.publish-button')).to_have_count(0)
            expect(page.locator('.avatar-camera')).to_have_count(0)
            expect(page.locator('.profile-empty-state')).to_be_visible()
            ui.login_for_layout(page, 'profile_limited', 'Password123')
            page.goto('/user/profile_limited')
            expect(page.locator('.profile-trust-card--limited')).to_be_visible()
            expect(page.locator('.grid-item')).to_have_count(0)
            page.goto('/user/profile_review')
            expect(page).to_have_url(__import__('re').compile('/verify'))
            browser.close()
    finally:
        server.close()
    print('Profile checks passed:', ui.SCREENSHOT_DIR)


if __name__ == '__main__':
    main()
