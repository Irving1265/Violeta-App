"""Login visual/interaction checks using isolated local accounts and storage."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import ui_browser_smoke as ui


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    ui.reset_database()
    ui.create_user('login_design')
    with patch('socket.getfqdn', return_value='localhost'):
        server = ui.start_local_server()
    print('Screenshots:', ui.SCREENSHOT_DIR, flush=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, height in [(1440, 1000), (1024, 768), (768, 1024), (390, 844), (320, 700), (844, 390)]:
                context = browser.new_context(base_url=server.base_url, viewport={'width': width, 'height': height}, service_workers='block')
                page = context.new_page()
                page_errors = []
                page.on('pageerror', lambda error: page_errors.append(str(error)))
                page.goto('/login')
                page.wait_for_timeout(1500)
                try:
                    page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{width}-login.png'), full_page=True)
                    if args.reference:
                        source = Path(args.reference).read_text()
                        page.set_content(source, wait_until='networkidle')
                        page.wait_for_timeout(1000)
                        page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{width}-reference.png'), full_page=True)
                    if args.baseline:
                        continue
                    ui.assert_no_horizontal_overflow(page, 'login')
                    expect(page.locator('.login-auth .brand-logo')).to_have_count(1)
                    expect(page.locator('.login-auth .brand-logo__meta')).to_have_text('Beta v1.2')
                    expect(page.locator('.login-auth .avatar-ilu')).to_have_count(0)
                    if height >= 700:
                        assert page.evaluate('document.documentElement.scrollHeight <= innerHeight + 1'), 'Normal login should fit without scrolling'
                    expect(page.locator('#loginForm input[name="csrf_token"]')).to_have_count(1)
                    expect(page.locator('#googleLoginForm input[name="csrf_token"]')).to_have_count(1)
                    expect(page.get_by_role('button', name='Continuar con Google')).to_be_disabled()
                    expect(page.get_by_label('Usuaria o correo', exact=True)).to_be_visible()
                    password = page.locator('#password')
                    password.focus()
                    page.locator('#login').focus()
                    expect(page.locator('#passwordError')).to_be_visible()
                    button = page.get_by_role('button', name='Mostrar contraseña')
                    field_box, button_box = password.bounding_box(), button.bounding_box()
                    assert abs(field_box['y'] + field_box['height'] / 2 - button_box['y'] - button_box['height'] / 2) < 2
                    assert button_box['width'] >= 44 and button_box['height'] >= 44
                    button.click()
                    expect(password).to_have_attribute('type', 'text')
                    page.get_by_role('button', name='Ocultar contraseña').click()
                    expect(password).to_have_attribute('type', 'password')
                    page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{width}-error.png'), full_page=True)
                    expect(page.get_by_role('link', name='Crear cuenta nueva')).to_have_attribute('href', '/register')
                    expect(page.get_by_role('link', name='¿Olvidaste tu contraseña?')).to_have_attribute('href', '/forgot-password')
                    if width <= 992:
                        expect(page.locator('#loginMap')).to_have_count(0)
                    else:
                        expect(page.locator('#loginMap')).to_be_visible()
                        page.get_by_role('button', name='Banquetas', exact=True).click()
                        expect(page.get_by_role('button', name='Banquetas', exact=True)).to_have_attribute('aria-pressed', 'true')
                        page.get_by_role('button', name='Siguiente lugar').click()
                        expect(page.locator('#landmarkTitle')).to_have_text('Parque Fundidora')
                        page.route('**/api/hotspots?*', lambda route: route.fulfill(json={'hotspots': [{'lat': 25.6866, 'lng': -100.3161, 'count': 3}]}))
                        page.get_by_role('button', name='Todos', exact=True).click()
                        expect(page.locator('.hotspot-dot')).to_have_text('3')
                        page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{width}-map-fixture.png'))
                        page.unroute('**/api/hotspots?*')
                        page.route('**/api/hotspots?*', lambda route: route.fulfill(status=503, json={'error': 'test-unavailable'}))
                        page.get_by_role('button', name='Banquetas', exact=True).click()
                        expect(page.locator('#loginMapStatus')).to_contain_text('No pudimos cargar')
                        expect(page.locator('.hotspot-dot')).to_have_count(0)
                        expect(page.get_by_role('button', name='Iniciar sesión', exact=True)).to_be_enabled()
                    assert not page_errors, page_errors
                    print(width, 'passed', flush=True)
                except Exception:
                    page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{width}-failure.png'), full_page=True)
                    raise
                finally:
                    context.close()
            if not args.baseline:
                context = browser.new_context(base_url=server.base_url, viewport={'width': 390, 'height': 844}, service_workers='block')
                page = context.new_page()
                page.goto('/login')
                page.locator('#login').fill('login_design')
                page.locator('#password').fill('incorrect-password')
                page.get_by_role('button', name='Iniciar sesión', exact=True).click()
                expect(page).to_have_url(server.base_url + '/login')
                expect(page.locator('#login')).to_have_value('login_design')
                page.locator('#password').fill('Password123')
                page.get_by_role('button', name='Iniciar sesión', exact=True).click()
                expect(page).to_have_url(server.base_url + '/')
                context.close()
                # Exercise the enabled Google control without real credentials or external login.
                from flask import redirect
                ui.app.config.update(GOOGLE_CLIENT_ID='visual-test', GOOGLE_CLIENT_SECRET='visual-test',
                                     GOOGLE_REDIRECT_URI=server.base_url + '/auth/google/callback')
                google = ui.app.extensions['violeta_google_client']
                for width, height in [(320, 700), (1440, 1000)]:
                    context = browser.new_context(base_url=server.base_url, viewport={'width': width, 'height': height}, service_workers='block')
                    page = context.new_page()
                    page.goto('/login')
                    expect(page.get_by_role('button', name='Continuar con Google')).to_be_enabled()
                    page.wait_for_timeout(1500)
                    page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{width}-google-enabled.png'), full_page=True)
                    with patch.object(google, 'authorize_redirect', side_effect=lambda *a, **k: redirect('/login?google-started=1')):
                        page.get_by_role('button', name='Continuar con Google').click()
                        expect(page).to_have_url(server.base_url + '/login?google-started=1')
                    with patch.object(google, 'authorize_access_token', return_value={
                        'id_token': 'validated-fixture', 'userinfo': {'sub': f'visual-{width}',
                        'email': f'visual-{width}@example.com', 'email_verified': True},
                    }):
                        page.goto('/auth/google/callback')
                    expect(page).to_have_url(server.base_url + '/auth/google/complete')
                    page.wait_for_timeout(1500)
                    ui.assert_no_horizontal_overflow(page, 'Google registration')
                    page.screenshot(path=str(ui.SCREENSHOT_DIR / f'{width}-google-registration.png'), full_page=True)
                    page.get_by_role('checkbox').check()
                    page.get_by_role('button', name='Crear mi cuenta').click()
                    expect(page).to_have_url(server.base_url + '/')
                    context.close()
            browser.close()
        print('Login review passed', flush=True)
    finally:
        server.close()


if __name__ == '__main__':
    main()
