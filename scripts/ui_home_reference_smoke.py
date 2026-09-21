"""Home layout and live interaction checks with isolated, disposable test data."""
import logging
import re
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import ui_browser_smoke as ui


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    ui.reset_database()
    user_id = ui.create_user('home_review')
    ui.create_user('home_limited', verified=False)
    ui.create_user('home_admin', roles=[ui.ROLE_SUPER_ADMIN])
    for _ in range(5):
        ui.create_public_post(user_id)
    with patch('socket.getfqdn', return_value='localhost'):
        server = ui.start_local_server()
    print('Screenshots:', ui.SCREENSHOT_DIR, flush=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, height in [(1440, 1000), (1024, 900), (768, 900), (390, 844), (320, 700)]:
                username = f'home_review_{width}'
                ui.create_user(username)
                context = browser.new_context(base_url=server.base_url, viewport={'width': width, 'height': height},
                    geolocation={'latitude': 25.6866, 'longitude': -100.3161}, permissions=['geolocation'], service_workers='block')
                page = context.new_page()
                ui.login_for_layout(page, username, 'Password123')
                notice = page.get_by_role('button', name='Entendido', exact=True)
                if notice.is_visible():
                    notice.click()
                page.wait_for_timeout(1000)
                ui.assert_no_horizontal_overflow(page, 'home')
                if width > 1000:
                    expect(page.locator('.weather-card')).to_have_css('flex-direction', 'row')
                    expect(page.locator('.activity-count').first).to_be_visible()
                    page.locator('#reportsToggleBtn').click()
                    expect(page.locator('#reportsToggleBtn')).to_have_attribute('aria-pressed', 'true')
                    page.locator('#reportsToggleBtn').click()
                    page.wait_for_timeout(800)
                if width < 768:
                    expect(page.locator('.bottom-nav .center')).to_have_css('width', '56px')
                card = page.locator('.post-card').first
                expect(card.locator('.post-content-container [data-post-map-label]')).to_have_text('Ver mapa')
                caption = card.locator('.post-caption-block').bounding_box()
                media = card.locator('.post-content-container').bounding_box()
                assert caption['y'] < media['y']
                page.screenshot(path=str(ui.SCREENSHOT_DIR / f'home-{width}.png'), full_page=True)
                card.get_by_role('button', name='Ver mapa', exact=True).click()
                expect(card.locator('[data-post-map-label]')).to_have_text('Ver imagen')
                expect(card.locator('.post-map-wrapper')).to_be_visible()
                card.get_by_role('button', name='Ver imagen', exact=True).click()
                expect(card.locator('.post-image-wrapper')).to_be_visible()
                like = card.locator('.like-btn')
                if 'active' in (like.get_attribute('class') or '').split():
                    like.click()
                    expect(like).not_to_have_class(re.compile(r'\bactive\b'))
                card.get_by_role('button', name='Me gusta', exact=True).click()
                expect(card.locator('.like-btn')).to_have_class(re.compile(r'\bactive\b'))
                card.get_by_role('button', name='Ver comentarios', exact=True).click()
                expect(card.locator('.post-comment-form')).to_be_visible()
                card.locator('.post-comment-input').fill('Comentario de prueba del nuevo home')
                card.get_by_role('button', name='Publicar comentario').click()
                expect(card.locator('.comments-list')).to_contain_text('Comentario de prueba del nuevo home')
                page.locator('#openAdvancedFilters').click()
                expect(page.locator('#advancedModal')).to_have_attribute('aria-hidden', 'false')
                page.get_by_role('button', name='Cerrar filtros', exact=True).click()
                page.evaluate('window.scrollTo(0, 350)')
                expect(page.locator('#mainHeader')).to_have_class(re.compile('header-scrolled'))
                page.screenshot(path=str(ui.SCREENSHOT_DIR / f'home-{width}-scroll.png'))
                print(width, 'passed', flush=True)
                context.close()
            for username in ['home_limited', 'home_admin']:
                context = browser.new_context(base_url=server.base_url, viewport={'width': 390, 'height': 844}, service_workers='block')
                page = context.new_page()
                ui.login_for_layout(page, username, 'Password123')
                notice = page.get_by_role('button', name='Entendido', exact=True)
                if notice.is_visible():
                    notice.click()
                page.wait_for_timeout(1000)
                ui.assert_no_horizontal_overflow(page, username)
                page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{username}.png'), full_page=True)
                if username == 'home_limited':
                    expect(page.locator('.post-image--protected').first).to_be_visible()
                    expect(page.locator('[data-post-caption]')).to_have_count(0)
                    expect(page.locator('.post-card .likes-count')).to_have_count(0)
                else:
                    expect(page.locator('.post-caption-edit-btn').first).to_be_visible()
                context.close()
            browser.close()
    finally:
        server.close()
    print('Home reference review passed', flush=True)


if __name__ == '__main__':
    main()
