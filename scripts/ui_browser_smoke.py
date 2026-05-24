#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(tempfile.mkdtemp(prefix='violeta-ui-smoke-'))
DB_PATH = TEMP_ROOT / 'violeta_ui.sqlite3'
UPLOAD_DIR = TEMP_ROOT / 'uploads'
SCREENSHOT_DIR = TEMP_ROOT / 'screenshots'

os.environ['SECRET_KEY'] = 'violeta-ui-smoke-secret'
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = f'sqlite:///{DB_PATH}'
os.environ['DATABASE_REQUIRE_SSL'] = 'false'
os.environ['UPLOAD_BACKEND'] = 'local'
os.environ['REDIS_URL'] = ''
os.environ['SUPABASE_URL'] = ''
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = ''
os.environ['SUPABASE_STORAGE_BUCKET'] = 'uploads'
os.environ['RESEND_API_KEY'] = ''
os.environ['RESEND_FROM'] = ''
os.environ['RESEND_REPLY_TO'] = ''
os.environ['MAIL_DELIVERY_METHOD'] = 'smtp'
os.environ['MAIL_SERVER'] = ''
os.environ['MAIL_PORT'] = '587'
os.environ['MAIL_USE_TLS'] = 'false'
os.environ['MAIL_USERNAME'] = ''
os.environ['MAIL_PASSWORD'] = ''
os.environ['MAIL_DEFAULT_SENDER'] = ''
os.environ['TWILIO_ACCOUNT_SID'] = ''
os.environ['TWILIO_AUTH_TOKEN'] = ''
os.environ['TWILIO_FROM_NUMBER'] = ''
os.environ['TWILIO_WHATSAPP_FROM_NUMBER'] = ''
os.environ['PUBLIC_LOCATION_APPROX_METERS'] = '25'
os.environ['SAFETY_PUBLISH_MIN_DELAY_MINUTES'] = '15'
os.environ['SAFETY_PUBLISH_DISTANCE_METERS'] = '200'
os.environ['SAFETY_PUBLISH_FALLBACK_MINUTES'] = '60'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app_module = importlib.import_module('app')

app = app_module.app
db = app_module.db
User = app_module.User
SafetyContact = app_module.SafetyContact
Post = app_module.Post
PostMeta = app_module.PostMeta
PanicEvent = app_module.PanicEvent
ROLE_SUPER_ADMIN = getattr(app_module, 'ROLE_SUPER_ADMIN', 'super_admin')

app.config.update(
    TESTING=True,
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    SUPABASE_URL='',
    SUPABASE_SERVICE_ROLE_KEY='',
    SUPABASE_STORAGE_BUCKET='uploads',
    RESEND_API_KEY='',
    RESEND_FROM='',
    RESEND_REPLY_TO='',
    MAIL_SERVER='',
    MAIL_USERNAME='',
    MAIL_PASSWORD='',
    MAIL_DEFAULT_SENDER='',
)


@dataclass
class LocalServer:
    server: object
    thread: threading.Thread
    base_url: str

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def start_local_server() -> LocalServer:
    port = allocate_port()
    server = make_server('127.0.0.1', port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return LocalServer(server=server, thread=thread, base_url=f'http://127.0.0.1:{port}')


def reset_database() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for child in UPLOAD_DIR.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    app_module._RATE_LIMIT_BUCKETS.clear()
    with app.app_context():
        db.session.remove()
        db.drop_all()
        app_module.ensure_startup_schema()


def create_user(
    username: str,
    *,
    verified: bool = True,
    password: str = 'Password123',
    roles: list[str] | None = None,
) -> int:
    with app.app_context():
        user = User(username=username, email=f'{username}@example.com')
        user.set_password(password)
        user.is_verified = verified
        if roles:
            user.set_roles(roles)
        db.session.add(user)
        db.session.commit()
        return int(user.id)


def create_safety_contact(user_id: int, *, name: str, phone: str) -> int:
    with app.app_context():
        contact = SafetyContact(user_id=user_id, name=name, phone=phone, is_primary=True)
        db.session.add(contact)
        db.session.commit()
        return int(contact.id)


def create_seed_image(filename: str = 'ui-smoke-feed.jpg') -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    image_path = UPLOAD_DIR / filename
    image = Image.new('RGB', (720, 720), color=(45, 27, 64))
    image.save(image_path, format='JPEG', quality=82)
    return filename


def create_public_post(user_id: int, *, filename: str | None = None) -> int:
    image_filename = filename or create_seed_image()
    with app.app_context():
        post = Post(
            caption='Reporte visual para smoke responsive.',
            image_filename=image_filename,
            user_id=user_id,
            latitude=25.6866,
            longitude=-100.3161,
            location_name='Monterrey, México',
            city='Monterrey',
            country='México',
            categories=json.dumps(['Banquetas en mal estado', 'Terrenos baldíos']),
            publish_at=datetime.now(),
        )
        db.session.add(post)
        db.session.flush()
        db.session.add(PostMeta(post_id=post.id, show_public=True, allow_likes=True, allow_comments=True))
        db.session.commit()
        return int(post.id)


def wait_for(predicate, *, timeout: float = 15.0, interval: float = 0.2, error_message: str = 'Condition not met'):
    deadline = time.time() + timeout
    last_value = None
    while time.time() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval)
    raise AssertionError(f'{error_message}. Last value: {last_value!r}')


def get_latest_post(user_id: int):
    with app.app_context():
        return (
            Post.query.filter_by(user_id=user_id)
            .order_by(Post.id.desc())
            .first()
        )


def get_post_meta(post_id: int):
    with app.app_context():
        return PostMeta.query.filter_by(post_id=post_id).first()


def get_open_panic_event(user_id: int):
    with app.app_context():
        return (
            PanicEvent.query.filter_by(user_id=user_id, status='open')
            .order_by(PanicEvent.id.desc())
            .first()
        )


def login(page, username: str, password: str) -> None:
    page.goto('/login', wait_until='domcontentloaded')
    page.locator('input[name="login"]').fill(username)
    page.locator('input[name="password"]').fill(password)
    page.locator('form.auth-form button[type="submit"]').click()
    page.wait_for_url('**/')
    expect(page.locator('.floating-create-btn')).to_be_visible(timeout=10000)


def login_for_layout(page, username: str, password: str) -> None:
    page.goto('/login', wait_until='domcontentloaded')
    page.locator('input[name="login"]').fill(username)
    page.locator('input[name="password"]').fill(password)
    page.locator('form.auth-form button[type="submit"]').click()
    page.wait_for_url('**/', timeout=10000)
    expect(page.locator('body')).to_be_visible(timeout=10000)


def assert_visible_any(page, selectors: list[str], label: str) -> None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state='visible', timeout=3000)
            return
        except PlaywrightTimeoutError:
            continue
    raise AssertionError(f'{label}: no se encontro ningun selector visible: {selectors!r}')


def assert_no_horizontal_overflow(page, label: str) -> None:
    metrics = page.evaluate(
        """
        () => {
          const root = document.documentElement;
          const body = document.body;
          const scrollWidth = Math.max(root.scrollWidth, body ? body.scrollWidth : 0);
          const overflowing = Array.from(document.querySelectorAll('body *'))
            .filter((node) => {
              const rect = node.getBoundingClientRect();
              return rect.width > 0 && (rect.right > window.innerWidth + 8 || rect.left < -8);
            })
            .slice(0, 5)
            .map((node) => ({
              tag: node.tagName.toLowerCase(),
              id: node.id || '',
              className: String(node.className || '').slice(0, 120),
              right: Math.round(node.getBoundingClientRect().right),
              left: Math.round(node.getBoundingClientRect().left)
            }));
          return {scrollWidth, innerWidth: window.innerWidth, overflowing};
        }
        """
    )
    allowed = int(metrics['innerWidth']) + 8
    if int(metrics['scrollWidth']) > allowed:
        raise AssertionError(
            f'{label}: overflow horizontal {metrics["scrollWidth"]} > {allowed}; '
            f'elementos={metrics["overflowing"]!r}'
        )


def add_browser_guards(context) -> None:
    context.add_init_script(
        """
        (() => {
          window.alert = (message) => {
            window.__violetaAlerts = window.__violetaAlerts || [];
            window.__violetaAlerts.push(String(message));
          };
          const originalSetTimeout = window.setTimeout.bind(window);
          window.setTimeout = (handler, timeout, ...args) => {
            if (typeof handler === 'function') {
              const source = Function.prototype.toString.call(handler);
              if (source.includes('window.location.href') && source.includes('tel:')) {
                window.__violetaSuppressedTelNavigation = true;
                return 0;
              }
            }
            return originalSetTimeout(handler, timeout, ...args);
          };
        })();
        """
    )
    context.route('**/tile.openstreetmap.org/**', lambda route: route.fulfill(status=204, body=''))


def check_layout_route(page, path: str, selectors: list[str], label: str) -> None:
    page.goto(path, wait_until='domcontentloaded')
    assert_visible_any(page, selectors, label)
    assert_no_horizontal_overflow(page, label)


def run_responsive_layout_checks(
    browser,
    server: LocalServer,
    *,
    username: str,
    password: str,
    admin_username: str,
    admin_password: str,
) -> None:
    viewport_specs = [
        {
            'name': 'telefono',
            'viewport': {'width': 390, 'height': 844},
            'is_mobile': True,
            'has_touch': True,
        },
        {
            'name': 'web',
            'viewport': {'width': 1440, 'height': 1100},
            'is_mobile': False,
            'has_touch': False,
        },
    ]

    user_routes = [
        ('/', ['.violeta-header', '.post-card', '#posts-container'], 'feed'),
        (f'/user/{username}', ['.profile-header', '.profile-hero-card', '.profile-avatar-lg'], 'perfil'),
        ('/safety', ['body'], 'centro de seguridad'),
        ('/chat', ['body'], 'chat'),
    ]
    admin_routes = [
        ('/admin', ['.admin-ops-page', '.admin-tabs-panel', '#adminOverviewSkeleton'], 'admin'),
        (
            '/admin/background-jobs',
            ['.admin-background-diagnostics-page', '.admin-background-filter-card'],
            'diagnostico background',
        ),
    ]

    for spec in viewport_specs:
        context = browser.new_context(
            base_url=server.base_url,
            geolocation={'latitude': 25.6866, 'longitude': -100.3161},
            permissions=['geolocation', 'camera'],
            viewport=spec['viewport'],
            is_mobile=spec['is_mobile'],
            has_touch=spec['has_touch'],
        )
        add_browser_guards(context)
        page = context.new_page()
        try:
            login_for_layout(page, username, password)
            for path, selectors, route_label in user_routes:
                check_layout_route(page, path, selectors, f'{spec["name"]}: {route_label}')
        finally:
            context.close()

        context = browser.new_context(
            base_url=server.base_url,
            geolocation={'latitude': 25.6866, 'longitude': -100.3161},
            permissions=['geolocation', 'camera'],
            viewport=spec['viewport'],
            is_mobile=spec['is_mobile'],
            has_touch=spec['has_touch'],
        )
        add_browser_guards(context)
        page = context.new_page()
        try:
            login_for_layout(page, admin_username, admin_password)
            for path, selectors, route_label in admin_routes:
                check_layout_route(page, path, selectors, f'{spec["name"]}: {route_label}')
        finally:
            context.close()


def maybe_click_crop_apply(page) -> None:
    crop_apply = page.locator('#pcApplyCropBtn')
    try:
        crop_apply.wait_for(state='visible', timeout=4000)
    except PlaywrightTimeoutError:
        return
    crop_apply.click()


def run_publish_flow(page, user_id: int) -> None:
    page.locator('.floating-create-btn').click(force=True)
    expect(page.locator('#postCreateModal')).to_be_visible(timeout=10000)

    page.evaluate('window.Cropper = undefined;')
    page.locator('#pcCameraStartBtn').click()
    expect(page.locator('#pcCameraCaptureBtn')).to_be_enabled(timeout=10000)
    page.locator('#pcCameraCaptureBtn').click()
    maybe_click_crop_apply(page)

    expect(page.locator('#pcPhotoPreviewCard')).to_be_visible(timeout=10000)
    expect(page.locator('#postCreateNextBtn')).to_be_enabled(timeout=10000)
    page.locator('#postCreateNextBtn').click()

    page.locator('#pcCaptionInput').fill('Reporte UI smoke: zona insegura con poca iluminacion.')
    page.locator('.pc-category-option', has_text='Zona insegura').click()
    expect(page.locator('#postCreateNextBtn')).to_be_enabled(timeout=10000)
    page.locator('#postCreateNextBtn').click()

    wait_for(
        lambda: page.locator('#pcLatInput').input_value() and page.locator('#pcLocationNameInput').input_value(),
        timeout=15,
        error_message='La UI no detecto la ubicacion',
    )
    expect(page.locator('#postCreateNextBtn')).to_be_enabled(timeout=10000)
    page.locator('#postCreateNextBtn').click()

    post = wait_for(
        lambda: get_latest_post(user_id),
        timeout=15,
        error_message='No se guardo el post desde la UI',
    )
    meta = wait_for(
        lambda: get_post_meta(int(post.id)),
        timeout=10,
        error_message='El post no genero PostMeta',
    )
    assert meta.location_visibility == 'exact', f'location_visibility inesperado: {meta.location_visibility!r}'
    assert post.location_name, 'El post no guardo location_name'
    assert post.latitude is not None and post.longitude is not None, 'El post no guardo coordenadas'
    assert post.publish_at is not None, 'El post no guardo publish_at'


def run_emergency_flow(page, user_id: int) -> None:
    page.goto('/emergency', wait_until='domcontentloaded')
    expect(page.locator('#emergencyHoldBtn')).to_be_visible(timeout=10000)

    hold_btn = page.locator('#emergencyHoldBtn')
    hold_btn.dispatch_event('pointerdown')
    page.wait_for_timeout(5200)
    hold_btn.dispatch_event('pointerup')

    wait_for(
        lambda: page.locator('#emergencyStatus').text_content()
        and 'Alerta registrada' in (page.locator('#emergencyStatus').text_content() or ''),
        timeout=10,
        error_message='La UI de emergencia no actualizo el estado',
    )
    event = wait_for(
        lambda: get_open_panic_event(user_id),
        timeout=10,
        error_message='No se registro el PanicEvent desde la UI',
    )
    assert event.latitude is not None and event.longitude is not None, 'El PanicEvent no guardo coordenadas'


def main() -> int:
    reset_database()
    user_id = create_user('ui_smoke', verified=True)
    create_user('ui_admin', verified=True, roles=[ROLE_SUPER_ADMIN])
    create_safety_contact(user_id, name='Contacto UI', phone='+528112345678')
    create_public_post(user_id)

    server = start_local_server()
    browser = None
    context = None
    page = None

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                '--use-fake-ui-for-media-stream',
                '--use-fake-device-for-media-stream',
                '--allow-file-access-from-files',
            ],
        )
        context = browser.new_context(
            base_url=server.base_url,
            geolocation={'latitude': 25.6866, 'longitude': -100.3161},
            permissions=['geolocation', 'camera'],
            viewport={'width': 1440, 'height': 1200},
        )
        add_browser_guards(context)
        page = context.new_page()

        login(page, 'ui_smoke', 'Password123')
        run_publish_flow(page, user_id)
        run_emergency_flow(page, user_id)
        context.close()
        context = None
        page = None

        run_responsive_layout_checks(
            browser,
            server,
            username='ui_smoke',
            password='Password123',
            admin_username='ui_admin',
            admin_password='Password123',
        )

        print('UI smoke OK')
        print(f'Base URL: {server.base_url}')
        print(f'DB temporal: {DB_PATH}')
        print(f'Capturas temporales: {SCREENSHOT_DIR}')
        return 0
    except Exception as exc:
        screenshot_path = SCREENSHOT_DIR / 'ui-browser-smoke-failure.png'
        if page is not None:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
                print(f'Fallo UI capturado en: {screenshot_path}')
            except Exception:
                pass
        print(f'UI smoke FAILED: {exc}')
        return 1
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        try:
            playwright.stop()
        except Exception:
            pass
        server.close()


if __name__ == '__main__':
    raise SystemExit(main())
