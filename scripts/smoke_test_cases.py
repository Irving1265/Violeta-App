#!/usr/bin/env python3
from __future__ import annotations

import io
import importlib
import importlib.util
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.error import URLError
from urllib.parse import parse_qs
from uuid import uuid4

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(tempfile.mkdtemp(prefix='violeta-smoke-'))
DB_PATH = TEMP_ROOT / 'violeta_smoke.sqlite3'
UPLOAD_DIR = TEMP_ROOT / 'uploads'

os.environ['SECRET_KEY'] = 'violeta-smoke-secret'
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = f"sqlite:///{DB_PATH}"
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
os.environ['AUDIT_LOG_RETENTION_DAYS'] = '365'
os.environ['BACKGROUND_JOB_EVENT_RETENTION_DAYS'] = '30'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app_module = importlib.import_module('app')

app = app_module.app
db = app_module.db
User = app_module.User
SafetyContact = app_module.SafetyContact
PanicEvent = app_module.PanicEvent
Post = app_module.Post
PostMeta = app_module.PostMeta
Comment = app_module.Comment
Like = app_module.Like
Report = app_module.Report
CommentReport = app_module.CommentReport
ChatRoom = app_module.ChatRoom
ChatParticipant = app_module.ChatParticipant
ChatMessage = app_module.ChatMessage
ChatMessageReport = app_module.ChatMessageReport
ModerationStrike = app_module.ModerationStrike
VerificationRequest = app_module.VerificationRequest
AuditLog = app_module.AuditLog
BackgroundJobEvent = app_module.BackgroundJobEvent
LocationViewAudit = app_module.LocationViewAudit
ROLE_SUPER_ADMIN = getattr(app_module, 'ROLE_SUPER_ADMIN', 'super_admin')

app.config.update(
    TESTING=True,
    WTF_CSRF_ENABLED=False,
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    MAIL_SERVER='',
    MAIL_USERNAME='',
    MAIL_PASSWORD='',
    MAIL_DEFAULT_SENDER='',
    RESEND_API_KEY='',
    RESEND_FROM='',
    RESEND_REPLY_TO='',
)


class VioletaSmokeTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
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
        if hasattr(app_module, 'invalidate_user_snapshot_cache'):
            app_module.invalidate_user_snapshot_cache()
        clear_runtime_caches = app.extensions.get('violeta_clear_runtime_caches')
        if clear_runtime_caches:
            clear_runtime_caches()

    def tearDown(self):
        with app.app_context():
            db.session.remove()

    @classmethod
    def tearDownClass(_cls):
        if TEMP_ROOT.exists():
            shutil.rmtree(TEMP_ROOT)

    def client_for(self, user_id: int | None = None):
        client = app.test_client()
        if user_id is not None:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user_id)
                sess['_fresh'] = True
        return client

    def create_user(self, username: str, *, verified: bool = True, password: str = 'Password123', roles: list[str] | None = None) -> int:
        with app.app_context():
            user = User(username=username, email=f'{username}@example.com')
            user.set_password(password)
            user.is_verified = verified
            user.verification_status = 'verified' if verified else 'unverified'
            user.trial_location_views_limit = 3
            assigned_roles = list(roles or [])
            if not assigned_roles and username.strip().lower() == 'admin':
                assigned_roles = [ROLE_SUPER_ADMIN]
            if assigned_roles:
                user.set_roles(assigned_roles)
            db.session.add(user)
            db.session.commit()
            return int(user.id)

    def save_seed_image(self, filename: str | None = None, *, color=(126, 43, 215)) -> str:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        name = filename or f'{uuid4().hex}.jpg'
        path = UPLOAD_DIR / name
        image = Image.new('RGB', (64, 64), color)
        image.save(path, format='JPEG')
        return name

    def image_upload(self, filename: str = 'reporte.jpg', *, color=(126, 43, 215), with_exif: bool = False):
        buffer = io.BytesIO()
        image = Image.new('RGB', (64, 64), color)
        if with_exif:
            exif = Image.Exif()
            exif[274] = 6
            exif[315] = 'violeta-smoke'
            exif[36867] = '2026:03:26 20:00:00'
            image.save(buffer, format='JPEG', exif=exif)
        else:
            image.save(buffer, format='JPEG')
        buffer.seek(0)
        return buffer, filename

    def capture_fields(
        self,
        *,
        lat: float = 25.6866,
        lng: float = -100.3161,
        location_name: str = 'Av. Morelos y Escobedo',
        city: str = 'Monterrey',
        country: str = 'México',
        motion_state: str = 'walking',
        speed_mps: float = 1.3,
        accuracy: float = 8.0,
    ) -> dict[str, str]:
        return {
            'capture_latitude': str(lat),
            'capture_longitude': str(lng),
            'capture_location_name': location_name,
            'capture_city': city,
            'capture_country': country,
            'capture_motion_state': motion_state,
            'capture_speed_mps': str(speed_mps),
            'capture_accuracy': str(accuracy),
            'capture_taken_at': '2026-03-26T20:00:00Z',
        }

    def create_public_post(
        self,
        user_id: int,
        *,
        caption: str,
        location_name: str = 'Av. Morelos y Escobedo',
        city: str = 'Monterrey',
        country: str = 'México',
        latitude: float = 25.6866,
        longitude: float = -100.3161,
        created_at: datetime | None = None,
        publish_at: datetime | None = None,
        show_public: bool = True,
        location_visibility: str = 'exact',
        categories: list[str] | None = None,
    ) -> int:
        filename = self.save_seed_image()
        with app.app_context():
            post = Post(
                caption=caption,
                image_filename=filename,
                user_id=user_id,
                latitude=latitude,
                longitude=longitude,
                location_name=location_name,
                city=city,
                country=country,
                categories=json.dumps(categories) if categories else None,
                created_at=created_at or app_module.utc_now_naive() - timedelta(minutes=30),
                publish_at=publish_at or app_module.utc_now_naive() - timedelta(minutes=1),
            )
            db.session.add(post)
            db.session.commit()
            meta = PostMeta(
                post_id=post.id,
                show_public=show_public,
                allow_likes=True,
                allow_comments=True,
                location_visibility=location_visibility,
            )
            db.session.add(meta)
            db.session.commit()
            return int(post.id)

    def create_comment(self, user_id: int, post_id: int, content: str) -> int:
        with app.app_context():
            comment = Comment(content=content, user_id=user_id, post_id=post_id)
            db.session.add(comment)
            db.session.commit()
            return int(comment.id)

    def create_safety_contact(self, user_id: int, *, name: str, phone: str, is_primary: bool = True) -> int:
        with app.app_context():
            contact = SafetyContact(user_id=user_id, name=name, phone=phone, is_primary=is_primary)
            db.session.add(contact)
            db.session.commit()
            return int(contact.id)

    def create_chat_message(self, user_id: int, *, room_name: str, content: str) -> tuple[int, int]:
        with app.app_context():
            room = ChatRoom(name=room_name, is_private=False, is_approved=True, created_by=user_id)
            db.session.add(room)
            db.session.commit()
            db.session.add(ChatParticipant(user_id=user_id, room_id=room.id))
            db.session.add(ChatMessage(content=content, user_id=user_id, room_id=room.id))
            db.session.commit()
            message = ChatMessage.query.filter_by(room_id=room.id, user_id=user_id).order_by(ChatMessage.id.desc()).first()
            assert message is not None
            return int(room.id), int(message.id)

    def create_audit_log(
        self,
        *,
        actor_id: int | None = None,
        target_user_id: int | None = None,
        event_type: str = 'workspace.view',
        workspace: str = 'admin',
        summary: str = 'Evento de prueba',
        created_at: datetime | None = None,
        details: str | None = None,
    ) -> int:
        with app.app_context():
            log = AuditLog(
                actor_id=actor_id,
                target_user_id=target_user_id,
                event_type=event_type,
                workspace=workspace,
                resource_type='audit_log',
                route='/admin',
                method='GET',
                ip_address='127.0.0.1',
                user_agent='smoke-test',
                summary=summary,
                details=details,
                created_at=created_at or datetime.now(),
            )
            db.session.add(log)
            db.session.commit()
            return int(log.id)

    def post_ids_in_feed(self, client) -> list[int]:
        response = client.get('/feed')
        self.assertEqual(response.status_code, 200)
        data = response.get_json() or {}
        return [int(item['id']) for item in data.get('posts') or []]

    def assert_timing_headers(self, response):
        self.assertIn('Server-Timing', response.headers)
        self.assertIn('X-Response-Time-ms', response.headers)
        self.assertRegex(response.headers.get('Server-Timing', ''), r'^app;dur=\d+(\.\d+)?$')
        float(response.headers.get('X-Response-Time-ms', ''))

    def fetch_feed_post(self, client, post_id: int):
        response = client.get('/feed')
        self.assertEqual(response.status_code, 200)
        data = response.get_json() or {}
        for item in data.get('posts') or []:
            if int(item['id']) == int(post_id):
                return item
        return None

    def get_post(self, post_id: int):
        with app.app_context():
            return db.session.get(Post, post_id)

    def get_post_meta(self, post_id: int):
        with app.app_context():
            return PostMeta.query.filter_by(post_id=post_id).first()

    def get_comment(self, comment_id: int):
        with app.app_context():
            return db.session.get(Comment, comment_id)

    def get_user(self, user_id: int):
        with app.app_context():
            return db.session.get(User, user_id)

    def get_strikes(self, user_id: int) -> list[ModerationStrike]:
        with app.app_context():
            return list(ModerationStrike.query.filter_by(user_id=user_id).order_by(ModerationStrike.id.asc()).all())

    def get_audit_logs(self, *, event_type: str | None = None, workspace: str | None = None) -> list[AuditLog]:
        with app.app_context():
            query = AuditLog.query.order_by(AuditLog.id.asc())
            if event_type:
                query = query.filter_by(event_type=event_type)
            if workspace:
                query = query.filter_by(workspace=workspace)
            return list(query.all())

    def backdate_post(self, post_id: int, *, minutes_ago: int):
        with app.app_context():
            post = db.session.get(Post, post_id)
            assert post is not None
            post.created_at = app_module.utc_now_naive() - timedelta(minutes=minutes_ago)
            db.session.add(post)
            db.session.commit()

    def backdate_latest_strike(self, user_id: int, *, days_ago: int):
        with app.app_context():
            strike = ModerationStrike.query.filter_by(user_id=user_id).order_by(ModerationStrike.id.desc()).first()
            assert strike is not None
            strike.created_at = datetime.now() - timedelta(days=days_ago)
            db.session.add(strike)
            db.session.commit()

    def test_login_success_invalid_credentials_and_required_session(self):
        self.create_user('login_smoke')
        client = app.test_client()

        protected = client.get('/profile', follow_redirects=False)
        self.assertEqual(protected.status_code, 302)
        self.assertIn('/login', protected.headers.get('Location', ''))
        self.assert_timing_headers(protected)

        invalid = client.post(
            '/login',
            data={'login': 'login_smoke', 'password': 'wrong-password'},
            follow_redirects=False,
        )
        self.assertEqual(invalid.status_code, 200)
        self.assert_timing_headers(invalid)
        with client.session_transaction() as sess:
            self.assertNotIn('_user_id', sess)

        valid = client.post(
            '/login',
            data={'login': 'login_smoke', 'password': 'Password123'},
            follow_redirects=False,
        )
        self.assertEqual(valid.status_code, 302)
        self.assertIn('/', valid.headers.get('Location', ''))
        self.assert_timing_headers(valid)
        with client.session_transaction() as sess:
            self.assertTrue(sess.get('_user_id'))

    def test_registration_creates_limited_account_without_access_code(self):
        client = app.test_client()
        register_page = client.get('/register')
        self.assertEqual(register_page.status_code, 200)
        html = register_page.get_data(as_text=True).lower()
        forbidden_terms = (
            'inv' + 'ite',
            'invit' + 'ación',
            'código de ' + 'invit' + 'ación',
            'ref' + 'erral',
        )
        for term in forbidden_terms:
            self.assertNotIn(term, html)

        response = client.post(
            '/register',
            data={
                'email': 'nueva_sin_codigo@example.com',
                'username': 'nueva_sin_codigo',
                'password': 'Password123',
                'password2': 'Password123',
                'eligibility_attestation': 'y',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))
        with app.app_context():
            user = User.query.filter_by(username='nueva_sin_codigo').first()
            self.assertIsNotNone(user)
            self.assertFalse(user.is_verified)
            self.assertEqual(user.verification_status, 'unverified')
            self.assertEqual(int(user.trial_location_views_limit or 0), 3)

    def test_password_toggle_buttons_anchor_to_input_row_with_errors(self):
        auth_templates = ('login.html', 'register.html', 'reset_password.html')
        for template_name in auth_templates:
            template_html = (PROJECT_ROOT / 'templates' / template_name).read_text(encoding='utf-8')
            self.assertIn('--password-input-height: 50px;', template_html)
            self.assertIn('top: calc(var(--password-input-height) / 2);', template_html)

        landing_html = (PROJECT_ROOT / 'templates' / 'landing.html').read_text(encoding='utf-8')
        self.assertIn('--password-input-height: 50px;', landing_html)
        self.assertIn('top: calc(var(--password-input-height) / 2);', landing_html)

        auth_css = (PROJECT_ROOT / 'static' / 'css' / 'auth_page.css').read_text(encoding='utf-8')
        self.assertIn('--auth-input-height: 50px;', auth_css)
        self.assertIn('top: calc(var(--auth-input-height) / 2);', auth_css)

        profile_html = (PROJECT_ROOT / 'templates' / 'profile_edit.html').read_text(encoding='utf-8')
        self.assertIn('--profile-password-input-height: 50px;', profile_html)
        self.assertIn('top: calc(var(--profile-password-input-height) / 2);', profile_html)

    def test_visual_verification_requires_app_camera_video_consent_and_valid_file(self):
        user_id = self.create_user('solicita_revision', verified=False)
        client = self.client_for(user_id)

        page = client.get('/verify')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True).lower()
        self.assertIn('verifica tu cuenta', html)
        self.assertIn('grabación de seguridad', html)
        self.assertIn('consentimiento', html)
        self.assertIn('video corto', html)
        self.assertIn('activar mi cámara', html)
        self.assertIn('verification_page.css', html)
        self.assertIn('verification_page.js', html)
        self.assertNotIn('cdn.tailwindcss', html)
        self.assertNotIn('livenessphrases', html)
        self.assertNotIn('type="file"', html)
        self.assertNotIn('otp', html)
        self.assertNotIn('código', html)
        with app.app_context():
            self.assertIsNone(VerificationRequest.query.filter_by(user_id=user_id).first())

        def assert_unverified_without_pending():
            with app.app_context():
                user = db.session.get(User, user_id)
                self.assertEqual(user.verification_status, 'unverified')
                pending = VerificationRequest.query.filter_by(user_id=user_id, status='pending').first()
                self.assertIsNone(pending)

        missing_file = client.post('/api/verify/submit', data={'capture_source': 'app_camera', 'consent_accepted': 'on'})
        self.assertEqual(missing_file.status_code, 400)
        self.assertIn('foto o video', (missing_file.get_json() or {}).get('error', '').lower())
        assert_unverified_without_pending()

        missing_consent = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'evidence': (io.BytesIO(b'\x00\x00\x00\x18ftypmp42'), 'revision.mp4', 'video/mp4'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(missing_consent.status_code, 400)
        self.assertIn('consentimiento', (missing_consent.get_json() or {}).get('error', '').lower())
        assert_unverified_without_pending()

        uploaded_file_source = client.post(
            '/api/verify/submit',
            data={
                'consent_accepted': 'on',
                'evidence': (io.BytesIO(b'\x00\x00\x00\x18ftypmp42'), 'revision.mp4', 'video/mp4'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(uploaded_file_source.status_code, 400)
        self.assertIn('cámara de la app', (uploaded_file_source.get_json() or {}).get('error', '').lower())
        assert_unverified_without_pending()

        invalid_ext = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'consent_accepted': 'on',
                'evidence': (io.BytesIO(b'MZ'), 'malware.exe', 'application/x-msdownload'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(invalid_ext.status_code, 400)
        self.assertIn('formato', (invalid_ext.get_json() or {}).get('error', '').lower())
        assert_unverified_without_pending()

        invalid_mime = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'consent_accepted': 'on',
                'evidence': (io.BytesIO(b'\xff\xd8\xff\xd9'), 'selfie.jpg', 'application/octet-stream'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(invalid_mime.status_code, 400)
        self.assertIn('tipo de archivo', (invalid_mime.get_json() or {}).get('error', '').lower())
        assert_unverified_without_pending()

        oversized_image = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'consent_accepted': 'on',
                'evidence': (io.BytesIO(b'x' * (8 * 1024 * 1024 + 1)), 'selfie.jpg', 'image/jpeg'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(oversized_image.status_code, 413)
        self.assertIn('demasiado grande', (oversized_image.get_json() or {}).get('error', '').lower())
        assert_unverified_without_pending()

        image_bytes = b'\xff\xd8\xff\xe0violeta-selfie\xff\xd9'
        image_response = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'consent_accepted': 'on',
                'evidence': (io.BytesIO(image_bytes), 'selfie.jpg', 'image/jpeg'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(image_response.status_code, 400)
        self.assertIn('video grabado', (image_response.get_json() or {}).get('error', '').lower())
        assert_unverified_without_pending()

        video_bytes = b'\x00\x00\x00\x18ftypmp42violeta-video'
        response = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'consent_accepted': 'on',
                'note': 'Quiero participar en Violeta.',
                'evidence': (io.BytesIO(video_bytes), 'video_verificacion.webm', 'video/webm'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(payload.get('status'), 'pending')
        with app.app_context():
            user = db.session.get(User, user_id)
            self.assertEqual(user.verification_status, 'pending_review')
            request_row = VerificationRequest.query.filter_by(user_id=user_id).first()
            self.assertIsNotNone(request_row)
            self.assertEqual(request_row.status, 'pending')
            self.assertEqual(request_row.evidence_type, 'video')
            self.assertEqual(request_row.mime_type, 'video/webm')
            self.assertEqual(request_row.file_size, len(video_bytes))
            self.assertEqual(request_row.note, 'Quiero participar en Violeta.')
            self.assertTrue(request_row.consent_accepted)
            self.assertIsNotNone(request_row.consent_accepted_at)
            self.assertIsNotNone(request_row.submitted_at)
            evidence_path = request_row.evidence_file_path
            self.assertTrue(evidence_path.startswith(f'verify/{user_id}/'))
            self.assertTrue(evidence_path.endswith('.webm'))
            self.assertNotIn('video_verificacion', evidence_path)
            self.assertTrue((UPLOAD_DIR / evidence_path).exists())

        private_response = app.test_client().get(f'/uploads/{evidence_path}')
        self.assertEqual(private_response.status_code, 403)

        duplicate = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'consent_accepted': 'on',
                'evidence': (io.BytesIO(video_bytes), 'otra.webm', 'video/webm'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn('solicitud en revisión', (duplicate.get_json() or {}).get('error', '').lower())

    def test_visual_verification_accepts_video_evidence(self):
        user_id = self.create_user('solicita_revision_video', verified=False)
        client = self.client_for(user_id)
        video_bytes = b'\x00\x00\x00\x18ftypmp42violeta-video'

        response = client.post(
            '/api/verify/submit',
            data={
                'capture_source': 'app_camera',
                'consent_accepted': 'on',
                'evidence': (io.BytesIO(video_bytes), 'revision.mp4', 'video/mp4'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            user = db.session.get(User, user_id)
            self.assertEqual(user.verification_status, 'pending_review')
            request_row = VerificationRequest.query.filter_by(user_id=user_id).first()
            self.assertEqual(request_row.status, 'pending')
            self.assertEqual(request_row.evidence_type, 'video')
            self.assertEqual(request_row.mime_type, 'video/mp4')
            self.assertEqual(request_row.file_size, len(video_bytes))
            self.assertTrue(request_row.evidence_file_path.startswith(f'verify/{user_id}/'))
            self.assertTrue(request_row.evidence_file_path.endswith('.mp4'))
            self.assertNotIn('revision', request_row.evidence_file_path)

    def test_health_check_public_safe_and_degrades_on_cache_failure(self):
        client = app.test_client()
        response = client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('status'), 'ok')
        checks = payload.get('checks') or {}
        self.assertEqual((checks.get('database') or {}).get('status'), 'ok')
        self.assertEqual((checks.get('uploads') or {}).get('status'), 'ok')
        self.assertEqual((checks.get('uploads') or {}).get('backend'), 'local')
        self.assertIn((checks.get('mail') or {}).get('status'), {'disabled', 'ok'})
        self.assertIn((checks.get('cache') or {}).get('status'), {'disabled', 'ok'})
        self.assertIn((checks.get('background_jobs') or {}).get('status'), {'ok', 'inline', 'disabled'})
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        body = response.get_data(as_text=True)
        self.assertNotIn(os.environ['SECRET_KEY'], body)
        self.assertNotIn(os.environ['DATABASE_URL'], body)

        cli_result = app.test_cli_runner().invoke(args=['health-check'])
        self.assertEqual(cli_result.exit_code, 0)
        self.assertIn('"status": "ok"', cli_result.output)
        self.assertNotIn(os.environ['SECRET_KEY'], cli_result.output)
        self.assertNotIn(os.environ['DATABASE_URL'], cli_result.output)

        original_redis_url = app.config.get('REDIS_URL')

        def restore_redis_config():
            app.config['REDIS_URL'] = original_redis_url

        self.addCleanup(restore_redis_config)
        app.config['REDIS_URL'] = 'redis://127.0.0.1:1/0'
        degraded = client.get('/healthz')
        self.assertEqual(degraded.status_code, 503)
        degraded_payload = degraded.get_json() or {}
        self.assertEqual(degraded_payload.get('status'), 'degraded')
        self.assertIn('cache', degraded_payload.get('failing_checks') or [])

        original_health_config = {
            'APP_ENV': app.config.get('APP_ENV'),
            'UPLOAD_BACKEND': app.config.get('UPLOAD_BACKEND'),
            'SUPABASE_URL': app.config.get('SUPABASE_URL'),
            'SUPABASE_SERVICE_ROLE_KEY': app.config.get('SUPABASE_SERVICE_ROLE_KEY'),
            'SUPABASE_STORAGE_BUCKET': app.config.get('SUPABASE_STORAGE_BUCKET'),
            'MAIL_DELIVERY_METHOD': app.config.get('MAIL_DELIVERY_METHOD'),
            'RESEND_API_KEY': app.config.get('RESEND_API_KEY'),
            'RESEND_FROM': app.config.get('RESEND_FROM'),
        }

        def restore_health_config():
            app.config.update(original_health_config)

        self.addCleanup(restore_health_config)
        app.config.update(
            APP_ENV='production',
            REDIS_URL='',
            UPLOAD_BACKEND='supabase',
            SUPABASE_URL='https://abc.supabase.co',
            SUPABASE_SERVICE_ROLE_KEY='service-role-secret-value',
            SUPABASE_STORAGE_BUCKET='uploads',
            MAIL_DELIVERY_METHOD='resend',
            RESEND_API_KEY='re_secret_value',
            RESEND_FROM='Violeta <no-reply@violeta.app>',
        )
        production_response = client.get('/healthz')
        self.assertEqual(production_response.status_code, 200)
        production_payload = production_response.get_json() or {}
        production_checks = production_payload.get('checks') or {}
        self.assertEqual((production_checks.get('uploads') or {}).get('backend'), 'supabase')
        self.assertEqual((production_checks.get('uploads') or {}).get('status'), 'ok')
        self.assertEqual((production_checks.get('mail') or {}).get('backend'), 'resend')
        self.assertEqual((production_checks.get('mail') or {}).get('status'), 'ok')
        production_body = production_response.get_data(as_text=True)
        self.assertNotIn('service-role-secret-value', production_body)
        self.assertNotIn('re_secret_value', production_body)

    def test_preflight_check_reports_warnings_and_strict_failures_without_secrets(self):
        original_config = {
            'APP_ENV': app.config.get('APP_ENV'),
            'PREFERRED_URL_SCHEME': app.config.get('PREFERRED_URL_SCHEME'),
            'SQLALCHEMY_DATABASE_URI': app.config.get('SQLALCHEMY_DATABASE_URI'),
            'UPLOAD_BACKEND': app.config.get('UPLOAD_BACKEND'),
            'MAIL_DELIVERY_METHOD': app.config.get('MAIL_DELIVERY_METHOD'),
            'MAIL_SERVER': app.config.get('MAIL_SERVER'),
            'MAIL_USERNAME': app.config.get('MAIL_USERNAME'),
            'MAIL_PASSWORD': app.config.get('MAIL_PASSWORD'),
            'MAIL_DEFAULT_SENDER': app.config.get('MAIL_DEFAULT_SENDER'),
            'SESSION_COOKIE_SECURE': app.config.get('SESSION_COOKIE_SECURE'),
            'REMEMBER_COOKIE_SECURE': app.config.get('REMEMBER_COOKIE_SECURE'),
            'REDIS_URL': app.config.get('REDIS_URL'),
            'BACKGROUND_JOBS_ENABLED': app.config.get('BACKGROUND_JOBS_ENABLED'),
            'BACKGROUND_JOBS_INLINE': app.config.get('BACKGROUND_JOBS_INLINE'),
            'ASYNC_IMAGE_PROCESSING': app.config.get('ASYNC_IMAGE_PROCESSING'),
            'ASYNC_UPLOAD_OPTIMIZATION': app.config.get('ASYNC_UPLOAD_OPTIMIZATION'),
            'ASYNC_REVERSE_GEOCODING': app.config.get('ASYNC_REVERSE_GEOCODING'),
            'ASYNC_EMAIL_DELIVERY': app.config.get('ASYNC_EMAIL_DELIVERY'),
        }

        def restore_config():
            app.config.update(original_config)

        self.addCleanup(restore_config)
        app.config.update(
            APP_ENV='development',
            PREFERRED_URL_SCHEME='http',
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{DB_PATH}",
            UPLOAD_BACKEND='local',
            MAIL_DELIVERY_METHOD='smtp',
            MAIL_SERVER='smtp.example.com',
            MAIL_USERNAME='sender@example.com',
            MAIL_PASSWORD='',
            MAIL_DEFAULT_SENDER='sender@example.com',
            SESSION_COOKIE_SECURE=False,
            REMEMBER_COOKIE_SECURE=False,
            REDIS_URL='',
            BACKGROUND_JOBS_ENABLED=True,
            BACKGROUND_JOBS_INLINE=True,
            ASYNC_IMAGE_PROCESSING=False,
            ASYNC_UPLOAD_OPTIMIZATION=False,
            ASYNC_REVERSE_GEOCODING=False,
            ASYNC_EMAIL_DELIVERY=False,
        )

        runner = app.test_cli_runner()
        normal = runner.invoke(args=['preflight-check'])
        self.assertEqual(normal.exit_code, 0)
        self.assertIn('"status": "warning"', normal.output)
        self.assertIn('sqlite_database', normal.output)
        self.assertNotIn(os.environ['SECRET_KEY'], normal.output)
        self.assertNotIn(str(DB_PATH), normal.output)

        strict = runner.invoke(args=['preflight-check', '--strict'])
        self.assertEqual(strict.exit_code, 1)
        self.assertIn('"status": "fail"', strict.output)
        self.assertIn('sqlite_in_strict_mode', strict.output)
        self.assertIn('local_uploads_in_strict_mode', strict.output)
        self.assertIn('preferred_scheme_not_https', strict.output)
        self.assertIn('session_cookie_not_secure', strict.output)
        self.assertIn('remember_cookie_not_secure', strict.output)
        self.assertIn('background_jobs_inline_in_strict_mode', strict.output)
        self.assertIn('async_jobs_disabled', strict.output)
        self.assertIn('missing_smtp_password', strict.output)
        self.assertNotIn(os.environ['SECRET_KEY'], strict.output)
        self.assertNotIn(str(DB_PATH), strict.output)

        app.config.update(
            MAIL_DELIVERY_METHOD='',
            MAIL_SERVER='',
            MAIL_USERNAME='',
            MAIL_PASSWORD='',
            MAIL_DEFAULT_SENDER='',
        )
        no_mail_strict = runner.invoke(args=['preflight-check', '--strict'])
        self.assertEqual(no_mail_strict.exit_code, 1)
        no_mail_payload = json.loads(no_mail_strict.output)
        no_mail_issues = {issue.get('code'): issue.get('level') for issue in no_mail_payload.get('issues') or []}
        self.assertEqual(no_mail_issues.get('mail_not_configured'), 'error')

        app.config.update(UPLOAD_BACKEND='invalid', REDIS_URL='redis+sentinel://cache')
        invalid = runner.invoke(args=['preflight-check', '--strict'])
        self.assertEqual(invalid.exit_code, 1)
        self.assertIn('invalid_upload_backend', invalid.output)
        self.assertIn('invalid_redis_url', invalid.output)

    def test_production_env_audit_guides_render_storage_and_mail_config(self):
        spec = importlib.util.spec_from_file_location(
            'production_env_audit',
            PROJECT_ROOT / 'scripts' / 'production_env_audit.py',
        )
        self.assertIsNotNone(spec)
        audit_module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(audit_module)

        incomplete = audit_module.audit({
            'APP_ENV': 'production',
            'SECRET_KEY': 'violeta-secret-produccion-larga',
            'DATABASE_URL': 'postgresql://violeta:secret@db.internal/violeta',
            'PREFERRED_URL_SCHEME': 'https',
            'SESSION_COOKIE_SECURE': 'true',
            'REMEMBER_COOKIE_SECURE': 'true',
            'UPLOAD_BACKEND': 'local',
            'MAIL_DELIVERY_METHOD': '',
        })
        incomplete_codes = {issue.get('code') for issue in incomplete.get('issues') or []}
        self.assertEqual(incomplete.get('status'), 'error')
        self.assertIn('local_uploads', incomplete_codes)
        self.assertIn('mail_not_configured', incomplete_codes)

        placeholder_config = audit_module.audit({
            'APP_ENV': 'production',
            'SECRET_KEY': 'violeta-produccion-llave-larga-aleatoria',
            'DATABASE_URL': 'postgresql://violeta:secret@db.internal/violeta',
            'PREFERRED_URL_SCHEME': 'https',
            'SESSION_COOKIE_SECURE': 'true',
            'REMEMBER_COOKIE_SECURE': 'true',
            'UPLOAD_BACKEND': 'supabase',
            'SUPABASE_URL': 'https://TU_PROYECTO.supabase.co',
            'SUPABASE_SERVICE_ROLE_KEY': 'TU_SERVICE_ROLE_KEY',
            'SUPABASE_STORAGE_BUCKET': 'uploads',
            'MAIL_DELIVERY_METHOD': 'resend',
            'RESEND_API_KEY': 'TU_RESEND_API_KEY',
            'RESEND_FROM': 'Violeta <no-reply@tu-dominio.com>',
        })
        placeholder_codes = {issue.get('code') for issue in placeholder_config.get('issues') or []}
        self.assertEqual(placeholder_config.get('status'), 'error')
        self.assertIn('placeholder_supabase_url', placeholder_codes)
        self.assertIn('placeholder_supabase_service_role_key', placeholder_codes)
        self.assertIn('placeholder_resend_api_key', placeholder_codes)
        self.assertIn('placeholder_resend_from', placeholder_codes)

        complete = audit_module.audit({
            'APP_ENV': 'production',
            'SECRET_KEY': 'violeta-produccion-llave-larga-aleatoria',
            'DATABASE_URL': 'postgresql://violeta:secret@db.internal/violeta',
            'PREFERRED_URL_SCHEME': 'https',
            'SESSION_COOKIE_SECURE': 'true',
            'REMEMBER_COOKIE_SECURE': 'true',
            'UPLOAD_BACKEND': 'supabase',
            'SUPABASE_URL': 'https://abc.supabase.co',
            'SUPABASE_SERVICE_ROLE_KEY': 'service-role-secret-value',
            'SUPABASE_STORAGE_BUCKET': 'uploads',
            'MAIL_DELIVERY_METHOD': 'resend',
            'RESEND_API_KEY': 're_secret_value',
            'RESEND_FROM': 'Violeta <no-reply@violeta.app>',
            'REDIS_URL': 'rediss://cache.example.com:6379/0',
        })
        self.assertEqual(complete.get('status'), 'ok')
        redacted = complete.get('redacted_config') or {}
        self.assertNotIn('service-role-secret-value', json.dumps(redacted))
        self.assertNotIn('re_secret_value', json.dumps(redacted))
        self.assertNotIn('postgresql://violeta:secret@db.internal/violeta', json.dumps(redacted))

    def test_limited_access_popup_loads_without_blocking_overlay(self):
        verified_id = self.create_user('overlay_verificada', verified=True)
        unverified_id = self.create_user('overlay_no_verificada', verified=False)

        verified_response = self.client_for(verified_id).get('/')
        self.assertEqual(verified_response.status_code, 200)
        verified_html = verified_response.get_data(as_text=True)
        self.assertNotIn('security_overlays.css', verified_html)
        self.assertNotIn('verify-gate-overlay', verified_html)
        self.assertNotIn('limited-access-modal', verified_html)
        self.assertNotIn('user-unverified', verified_html)

        unverified_response = self.client_for(unverified_id).get('/')
        self.assertEqual(unverified_response.status_code, 200)
        unverified_html = unverified_response.get_data(as_text=True)
        self.assertNotIn('security_overlays.css', unverified_html)
        self.assertNotIn('verify-gate-overlay', unverified_html)
        self.assertIn('limited-access-modal', unverified_html)
        self.assertIn('data-limited-access-close', unverified_html)
        self.assertIn('Cuenta no verificada', unverified_html)
        self.assertIn('user-unverified', unverified_html)

    def test_page_script_bundles_are_loaded_by_need(self):
        user_id = self.create_user('bundle_smoke', verified=True)
        post_id = self.create_public_post(user_id, caption='Reporte para bundles')

        login_html = app.test_client().get('/login').get_data(as_text=True)
        self.assertIn('/static/js/app_core.js?', login_html)
        self.assertNotIn('/static/js/app.js?', login_html)
        self.assertNotIn('/static/js/app_realtime.js?', login_html)
        self.assertNotIn('/static/vendor/bootstrap/bootstrap.bundle.min.js', login_html)
        self.assertNotIn('id="reportPostModal"', login_html)
        self.assertNotIn('id="reportCommentModal"', login_html)
        self.assertNotIn('<script src="/static/vendor/leaflet/leaflet.js"></script>', login_html)

        support_html = app.test_client().get('/support').get_data(as_text=True)
        self.assertNotIn('/static/vendor/bootstrap/bootstrap.bundle.min.js', support_html)
        self.assertNotIn('/static/vendor/leaflet/leaflet.js', support_html)

        client = self.client_for(user_id)
        feed_html = client.get('/').get_data(as_text=True)
        self.assertIn('20260525-home-perf-v1', feed_html)
        self.assertIn('id="mainHeader"', feed_html)
        self.assertIn('violeta-header-top', feed_html)
        self.assertIn('violeta-filters-bar', feed_html)
        self.assertIn('filter-divider', feed_html)
        self.assertIn('id="openAdvancedFilters"', feed_html)
        self.assertIn('id="cityChipContainer"', feed_html)
        self.assertIn('data-city="santa-catarina"', feed_html)
        self.assertIn('data-city="apodaca"', feed_html)
        self.assertNotIn('violeta-city-filters-section', feed_html)
        self.assertNotIn('Zonas seleccionadas', feed_html)
        self.assertIn('sidebar-legal', feed_html)
        self.assertIn('id="betaPublicModal"', feed_html)
        self.assertIn('beta-public-modal', feed_html)
        self.assertIn('data-beta-public-dismiss', feed_html)
        self.assertNotIn('beta-public-banner', feed_html)
        self.assertIn('Beta v1.0', feed_html)
        self.assertIn('Reportar problema', feed_html)
        self.assertIn('© 2026 Violeta. Todos los derechos reservados.', feed_html)
        self.assertIn('Política de privacidad', feed_html)
        self.assertIn('Términos', feed_html)
        self.assertIn('Eliminar cuenta', feed_html)
        self.assertIn('mini-map-widget', feed_html)
        self.assertIn('mini-map-widget__map', feed_html)
        self.assertNotIn('style="background: linear-gradient(145deg, #1e1b2e, #2a2436);', feed_html)
        self.assertIn('20260523-report-modal-split-v1', feed_html)

        style_css = (PROJECT_ROOT / 'static' / 'css' / 'style.css').read_text()
        index_css = (PROJECT_ROOT / 'static' / 'css' / 'index_page.css').read_text()
        self.assertIn('background: var(--bg-surface);', style_css)
        self.assertIn('background: var(--primary-color);', style_css)
        self.assertNotIn('.beta-public-modal', style_css)
        self.assertIn('.beta-public-modal', index_css)
        index_js = (PROJECT_ROOT / 'static' / 'js' / 'index_page.js').read_text()
        self.assertIn('violeta.betaPublicModal.dismissed.', index_js)
        self.assertIn('has-beta-public-modal', index_js)
        self.assertIn('id="reportPostModal"', feed_html)
        self.assertIn('id="reportCommentModal"', feed_html)
        self.assertIn('/static/js/app.js?', feed_html)
        self.assertIn('/static/vendor/bootstrap/bootstrap.bundle.min.js', feed_html)
        self.assertIn('/static/js/post_map.js?', feed_html)
        self.assertIn('/static/vendor/leaflet/leaflet.js', feed_html)
        self.assertIn('20260523-pending-timer-hhmmss-v1', feed_html)
        self.assertIn('20260523-ios-camera-capture-v1', feed_html)
        self.assertNotIn('/static/js/app_core.js?', feed_html)
        self.assertNotIn('/static/js/app_realtime.js?', feed_html)
        post_create_js = (PROJECT_ROOT / 'static/js/post_create.js').read_text(encoding='utf-8')
        self.assertIn('centerMapOnCurrentUserLocation', post_create_js)
        self.assertIn('getDeviceCurrentPosition', post_create_js)
        self.assertIn('USER_LOCATION_MAP_ZOOM', post_create_js)
        self.assertIn('detectIOSLikeDevice', post_create_js)
        self.assertIn('captureWithFileInputCamera', post_create_js)
        self.assertIn('waitForCameraVideoFrame', post_create_js)
        self.assertIn('ensureCameraFrameVisible', post_create_js)
        self.assertIn('webkit-playsinline', post_create_js)
        self.assertIn('isAllowedPhotoFile', post_create_js)
        pending_release_js = (PROJECT_ROOT / 'static/js/pending_post_release.js').read_text(encoding='utf-8')
        self.assertIn('String(hours).padStart(2', pending_release_js)
        self.assertIn('String(minutes).padStart(2', pending_release_js)
        self.assertIn('String(seconds).padStart(2', pending_release_js)
        style_css = (PROJECT_ROOT / 'static/css/style.css').read_text(encoding='utf-8')
        self.assertNotIn('#reportPostModal', style_css)
        self.assertNotIn('#reportChatMessageModal', style_css)
        self.assertNotIn('#editRoomModal', style_css)
        self.assertIn('.violeta-filters-bar', style_css)
        self.assertIn('.filter-divider', style_css)
        self.assertIn('.violeta-header-top', style_css)
        self.assertNotIn('.violeta-city-filters-section', style_css)
        self.assertNotIn('.violeta-filter-header', style_css)
        self.assertNotIn('.violeta-filter-label', style_css)
        self.assertIn('.violeta-header.header-scrolled', style_css)
        self.assertIn('.violeta-header.header-scrolled .violeta-header-top', style_css)
        self.assertIn('body.post-create-modal-open .floating-create-btn', style_css)
        index_page_js = (PROJECT_ROOT / 'static/js/index_page.js').read_text(encoding='utf-8')
        self.assertIn("header.classList.toggle('header-scrolled'", index_page_js)
        self.assertIn('mini-map-marker--hotspot', index_page_js)
        self.assertNotIn('User location:', index_page_js)
        index_page_css = (PROJECT_ROOT / 'static/css/index_page.css').read_text(encoding='utf-8')
        self.assertIn('.mini-map-widget__header', index_page_css)
        self.assertIn('.mini-map-marker--user', index_page_css)
        self.assertIn("classList.add('post-create-modal-open')", post_create_js)
        self.assertIn("classList.remove('post-create-modal-open')", post_create_js)
        post_card_css = (PROJECT_ROOT / 'static/css/post_card.css').read_text(encoding='utf-8')
        self.assertIn('#reportPostModal', post_card_css)
        self.assertIn('#reportCommentModal', post_card_css)

        post_html = client.get(f'/post/{post_id}').get_data(as_text=True)
        self.assertIn('20260523-report-modal-split-v1', post_html)
        self.assertIn('id="reportPostModal"', post_html)
        self.assertIn('id="reportCommentModal"', post_html)
        self.assertIn('/static/js/app.js?', post_html)
        self.assertIn('/static/js/post_map.js?', post_html)
        self.assertIn('/static/vendor/leaflet/leaflet.js', post_html)
        self.assertNotIn('/static/js/app_core.js?', post_html)
        self.assertNotIn('/static/js/app_realtime.js?', post_html)
        for template_name in ('upload.html', 'post.html', 'landing.html'):
            template_html = (PROJECT_ROOT / 'templates' / template_name).read_text(encoding='utf-8')
            self.assertNotIn('https://unpkg.com/leaflet', template_html)
            self.assertIn("vendor/leaflet/leaflet", template_html)

        chat_html = client.get('/chat').get_data(as_text=True)
        self.assertIn('20260523-chat-modal-split-v1', chat_html)
        self.assertIn('/static/js/app_core.js?', chat_html)
        self.assertIn('/static/js/app_realtime.js?', chat_html)
        self.assertNotIn('/static/js/app.js?', chat_html)
        self.assertNotIn('/static/js/post_map.js?', chat_html)
        self.assertNotIn('id="reportPostModal"', chat_html)
        self.assertNotIn('id="reportCommentModal"', chat_html)

        profile_html = client.get('/user/bundle_smoke').get_data(as_text=True)
        self.assertIn('/static/js/app_core.js?', profile_html)
        self.assertIn('/static/js/app_realtime.js?', profile_html)
        self.assertNotIn('/static/js/app.js?', profile_html)
        self.assertNotIn('/static/js/post_map.js?', profile_html)
        self.assertNotIn('id="reportPostModal"', profile_html)
        self.assertNotIn('id="reportCommentModal"', profile_html)

    def test_mobile_chat_viewport_guards_prevent_ios_zoom_and_overflow(self):
        user_id = self.create_user('mobile_chat_guard', verified=True)
        chat_html = self.client_for(user_id).get('/chat').get_data(as_text=True)
        self.assertIn('chat_page.css', chat_html)
        self.assertIn('20260523-chat-modal-split-v1', chat_html)
        self.assertIn('chat_page.js', chat_html)

        chat_css = (PROJECT_ROOT / 'static/css/chat_page.css').read_text(encoding='utf-8')
        self.assertIn('--chat-viewport-height', chat_css)
        self.assertIn('max-width: 100vw', chat_css)
        self.assertIn('font-size: 16px', chat_css)
        self.assertIn('#editRoomModal', chat_css)
        self.assertIn('#reportChatMessageModal', chat_css)
        self.assertIn('overflow-x: hidden', chat_css)

        chat_js = (PROJECT_ROOT / 'static/js/chat_page.js').read_text(encoding='utf-8')
        self.assertIn('syncChatViewportHeight', chat_js)
        self.assertIn('window.visualViewport', chat_js)
        self.assertIn('!isMobileChatView()', chat_js)
        self.assertIn('preventScroll: true', chat_js)

    def test_admin_attention_state_reports_new_moderation_work(self):
        admin_id = self.create_user('admin')
        reporter_id = self.create_user('reportera_attention')
        post_author_id = self.create_user('autora_attention_post')
        comment_author_id = self.create_user('autora_attention_comment')
        chat_author_id = self.create_user('autora_attention_chat')
        non_admin_id = self.create_user('sin_admin_attention')

        post_id = self.create_public_post(post_author_id, caption='Reporte para atención admin')
        comment_id = self.create_comment(comment_author_id, post_id, 'Comentario para reportar')
        _, message_id = self.create_chat_message(chat_author_id, room_name='Sala attention', content='Mensaje para reportar')

        non_admin_response = self.client_for(non_admin_id).get('/admin/attention-state')
        self.assertEqual(non_admin_response.status_code, 403)

        admin = self.client_for(admin_id)
        initial = admin.get('/admin/attention-state')
        self.assertEqual(initial.status_code, 200)
        initial_payload = initial.get_json() or {}
        self.assertEqual(initial_payload.get('admin_reports_total_count'), 0)
        self.assertIsNone(initial_payload.get('latest_admin_report_created_at'))

        reporter = self.client_for(reporter_id)
        post_report = reporter.post(
            f'/report_post/{post_id}',
            json={'reason': 'Información falsa', 'details': 'No coincide con el lugar'},
        )
        self.assertEqual(post_report.status_code, 200)
        comment_report = reporter.post(
            f'/api/comment/{comment_id}/report',
            json={'reason': 'Acoso o insultos', 'details': 'Requiere revisión'},
        )
        self.assertEqual(comment_report.status_code, 200)
        chat_report = reporter.post(
            f'/api/chat/message/{message_id}/report',
            json={'reason': 'Spam o fraude', 'details': 'Parece sospechoso'},
        )
        self.assertEqual(chat_report.status_code, 200)

        updated = admin.get('/admin/attention-state')
        self.assertEqual(updated.status_code, 200)
        payload = updated.get_json() or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(payload.get('post_reports_count'), 1)
        self.assertEqual(payload.get('reported_posts_count'), 1)
        self.assertEqual(payload.get('chat_message_reports_count'), 1)
        self.assertEqual(payload.get('comment_reports_count'), 1)
        self.assertEqual(payload.get('admin_reports_total_count'), 3)
        self.assertTrue(payload.get('has_admin_reports_attention'))
        self.assertIsInstance(payload.get('latest_admin_report_created_at'), str)

        shell_html = admin.get('/admin').get_data(as_text=True)
        self.assertIn('attentionState', shell_html)
        self.assertIn('reportsTotal: 3', shell_html)

    def test_admin_metrics_dashboard_summarizes_operational_health(self):
        admin_id = self.create_user('admin')
        reporter_id = self.create_user('reportera_metrics')
        author_id = self.create_user('autora_metrics')
        self.create_user('sin_verificar_metrics', verified=False)

        monterrey_post_id = self.create_public_post(
            author_id,
            caption='Reporte visible en Monterrey',
            city='Monterrey',
            show_public=True,
        )
        san_pedro_post_id = self.create_public_post(
            author_id,
            caption='Reporte oculto en San Pedro',
            city='San Pedro',
            show_public=False,
        )
        comment_id = self.create_comment(author_id, monterrey_post_id, 'Comentario resuelto')

        now = app_module.utc_now_naive()
        with app.app_context():
            db.session.add(Report(
                post_id=monterrey_post_id,
                reporter_id=reporter_id,
                reason='Información falsa',
                status='resolved',
                created_at=now - timedelta(hours=2),
                resolved_at=now - timedelta(hours=1),
                resolved_by=admin_id,
            ))
            db.session.add(Report(
                post_id=san_pedro_post_id,
                reporter_id=reporter_id,
                reason='Doxxing o datos personales',
                status='pending',
                created_at=now - timedelta(hours=1),
            ))
            db.session.add(CommentReport(
                comment_id=comment_id,
                reporter_id=reporter_id,
                reason='Acoso o insultos',
                status='resolved',
                created_at=now - timedelta(hours=3),
                resolved_at=now - timedelta(hours=2),
                resolved_by=admin_id,
            ))
            recovery_user = db.session.get(User, reporter_id)
            assert recovery_user is not None
            recovery_user.password_recovery_requested_at = now - timedelta(minutes=20)
            db.session.add(VerificationRequest(
                user_id=author_id,
                status='pending',
                phone='8112345678',
                submitted_at=now - timedelta(minutes=15),
            ))
            db.session.add(ChatRoom(
                name='Chat pendiente de aprobación',
                is_private=False,
                is_approved=False,
                created_by=author_id,
            ))
            db.session.commit()

        bg_stats = app.extensions.get('violeta_background_job_stats')
        bg_events = app.extensions.get('violeta_background_job_events')
        bg_lock = app.extensions.get('violeta_background_job_stats_lock')
        self.assertIsNotNone(bg_stats)
        self.assertIsNotNone(bg_events)
        saved_bg_stats = dict(bg_stats)
        saved_bg_events = list(bg_events)

        def restore_background_health():
            if bg_lock is not None:
                with bg_lock:
                    bg_stats.clear()
                    bg_stats.update(saved_bg_stats)
                    bg_events.clear()
                    bg_events.extend(saved_bg_events)
            else:
                bg_stats.clear()
                bg_stats.update(saved_bg_stats)
                bg_events.clear()
                bg_events.extend(saved_bg_events)

        self.addCleanup(restore_background_health)

        if bg_lock is not None:
            bg_lock.acquire()
        try:
            bg_stats.clear()
            bg_stats.update({
                'queued': 4,
                'completed': 2,
                'retry': 1,
                'failed': 1,
                'upload_image_processing.queued': 2,
                'upload_image_processing.completed': 1,
                'upload_image_processing.failed': 1,
                'reverse_geocode_post.retry': 1,
            })
            bg_events.clear()
            bg_events.appendleft({
                'job_name': 'upload_image_processing',
                'status': 'failed',
                'attempt': 3,
                'error': 'No se pudo procesar imagen',
                'duration_ms': 127.4,
                'created_at': now.isoformat(),
            })
            bg_events.appendleft({
                'job_name': 'reverse_geocode_post',
                'status': 'retry',
                'attempt': 1,
                'error': 'timeout',
                'duration_ms': None,
                'created_at': now.isoformat(),
            })
        finally:
            if bg_lock is not None:
                bg_lock.release()

        non_admin_response = self.client_for(reporter_id).get('/admin/metrics')
        self.assertEqual(non_admin_response.status_code, 403)
        non_admin_diagnostics = self.client_for(reporter_id).get(
            '/admin/background-jobs?format=json',
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(non_admin_diagnostics.status_code, 403)

        admin = self.client_for(admin_id)
        response = admin.get('/admin/metrics')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get('success'))
        metrics = payload.get('admin_metrics') or {}
        background_health = payload.get('background_job_health') or {}
        self.assertEqual(metrics.get('window_days'), 30)
        self.assertEqual(metrics.get('verified_users_count'), 3)
        self.assertEqual(metrics.get('total_users_count'), 4)
        self.assertEqual(metrics.get('verification_rate'), 75)
        self.assertEqual(metrics.get('hidden_posts_count'), 1)
        self.assertEqual(metrics.get('open_reports_count'), 1)
        self.assertEqual(metrics.get('resolved_reports_count'), 2)
        self.assertEqual(background_health.get('status'), 'danger')
        self.assertEqual(background_health.get('status_label'), 'Revisar fallas')
        self.assertEqual(background_health.get('failed_count'), 1)
        self.assertEqual(background_health.get('retry_count'), 1)
        self.assertTrue(any(
            event.get('job_label') == 'Procesamiento de imagen' and event.get('status') == 'failed'
            for event in background_health.get('recent_events') or []
        ))

        diagnostics_response = admin.get('/admin/background-jobs?format=json')
        self.assertEqual(diagnostics_response.status_code, 200)
        diagnostics_payload = diagnostics_response.get_json() or {}
        self.assertTrue(diagnostics_payload.get('success'))
        diagnostics_health = diagnostics_payload.get('background_job_health') or {}
        diagnostics_rows = diagnostics_payload.get('background_job_rows') or []
        diagnostics_recommendations = diagnostics_payload.get('background_job_recommendations') or []
        self.assertEqual(diagnostics_health.get('status'), 'danger')
        self.assertTrue(any(row.get('job_label') == 'Procesamiento de imagen' for row in diagnostics_rows))
        self.assertTrue(any(item.get('title') == 'Atender fallas recientes' for item in diagnostics_recommendations))
        self.assertEqual((diagnostics_payload.get('background_job_config') or {}).get('max_retries'), app.config.get('BACKGROUND_JOB_MAX_RETRIES'))

        zone_counts = {
            item.get('zone'): item.get('count')
            for item in metrics.get('reports_by_zone') or []
        }
        self.assertEqual(zone_counts.get('Monterrey'), 1)
        self.assertEqual(zone_counts.get('San Pedro'), 1)
        hidden_zone_counts = {
            item.get('zone'): item.get('count')
            for item in metrics.get('hidden_posts_by_zone') or []
        }
        self.assertEqual(hidden_zone_counts.get('San Pedro'), 1)

        overview_html = admin.get('/admin/overview').get_data(as_text=True)
        self.assertIn('Métricas operativas', overview_html)
        self.assertIn('admin-priority-strip', overview_html)
        self.assertIn('admin-background-health', overview_html)
        self.assertIn('Procesos en segundo plano', overview_html)
        self.assertIn('Revisar fallas', overview_html)
        self.assertIn('Procesamiento de imagen', overview_html)
        self.assertIn('No se pudo procesar imagen', overview_html)
        self.assertIn('Diagnóstico', overview_html)
        self.assertIn('Reportes por zona', overview_html)
        self.assertIn('Tiempo de respuesta', overview_html)
        self.assertIn('Reportes abiertos', overview_html)
        self.assertIn('Recuperación', overview_html)
        self.assertIn('Verificaciones', overview_html)
        self.assertIn('Chats pendientes', overview_html)
        self.assertIn('San Pedro', overview_html)
        self.assertRegex(overview_html, r'<strong>1</strong>\s*<span>Reportes abiertos</span>')
        self.assertRegex(overview_html, r'<strong>1</strong>\s*<span>Recuperación</span>')
        self.assertRegex(overview_html, r'<strong>1</strong>\s*<span>Verificaciones</span>')
        self.assertRegex(overview_html, r'<strong>1</strong>\s*<span>Chats pendientes</span>')

        diagnostics_html = admin.get('/admin/background-jobs').get_data(as_text=True)
        self.assertIn('Diagnóstico background', diagnostics_html)
        self.assertIn('Tareas por tipo', diagnostics_html)
        self.assertIn('Recomendaciones', diagnostics_html)
        self.assertIn('Procesamiento de imagen', diagnostics_html)
        self.assertIn('Atender fallas recientes', diagnostics_html)

    def test_admin_user_filters_search_status_strikes_and_reports(self):
        admin_id = self.create_user('admin')
        reporter_id = self.create_user('reportera_filtros_admin')
        searched_id = self.create_user('buscada_filtros_admin')
        unverified_id = self.create_user('sin_verificar_filtros_admin', verified=False)
        strike_id = self.create_user('strikes_filtros_admin')
        reported_author_id = self.create_user('reportada_filtros_admin')
        self.create_user('sin_match_filtros_admin')
        post_id = self.create_public_post(reported_author_id, caption='Post con reporte activo')

        with app.app_context():
            searched = db.session.get(User, searched_id)
            assert searched is not None
            searched.email = 'busqueda-directa@example.com'
            strike_user = db.session.get(User, strike_id)
            assert strike_user is not None
            strike_user.abuse_strikes = 2
            db.session.add(Report(
                post_id=post_id,
                reporter_id=reporter_id,
                reason='Información falsa',
                status='pending',
            ))
            db.session.commit()

        admin = self.client_for(admin_id)
        base_response = admin.get('/admin/content?tab=users')
        self.assertEqual(base_response.status_code, 200)
        base_html = base_response.get_data(as_text=True)
        self.assertIn('admin-user-filter-panel', base_html)
        self.assertIn('adminUserStatusFilter', base_html)

        search_response = admin.get('/admin/content?tab=users&user_q=busqueda-directa')
        self.assertEqual(search_response.status_code, 200)
        search_html = search_response.get_data(as_text=True)
        self.assertIn('buscada_filtros_admin', search_html)
        self.assertNotIn('sin_match_filtros_admin', search_html)

        unverified_response = admin.get('/admin/content?tab=users&user_status=unverified')
        self.assertEqual(unverified_response.status_code, 200)
        unverified_html = unverified_response.get_data(as_text=True)
        self.assertIn('sin_verificar_filtros_admin', unverified_html)
        self.assertNotIn('buscada_filtros_admin', unverified_html)

        strikes_response = admin.get('/admin/content?tab=users&user_strikes=two_plus')
        self.assertEqual(strikes_response.status_code, 200)
        strikes_html = strikes_response.get_data(as_text=True)
        self.assertIn('strikes_filtros_admin', strikes_html)
        self.assertNotIn('buscada_filtros_admin', strikes_html)

        reports_response = admin.get('/admin/content?tab=users&user_reports=with_reports')
        self.assertEqual(reports_response.status_code, 200)
        reports_html = reports_response.get_data(as_text=True)
        self.assertIn('reportada_filtros_admin', reports_html)
        self.assertIn('fa-flag', reports_html)
        self.assertNotIn('sin_match_filtros_admin', reports_html)

    def test_admin_user_audit_summary_shows_strikes_reports_and_actions(self):
        admin_id = self.create_user('admin')
        target_id = self.create_user('historial_visible_admin')
        reporter_id = self.create_user('reportera_historial_admin')
        post_id = self.create_public_post(target_id, caption='Post para historial visible')
        comment_id = self.create_comment(target_id, post_id, 'Comentario para historial visible')
        _, message_id = self.create_chat_message(
            target_id,
            room_name='Sala historial visible',
            content='Mensaje para historial visible',
        )

        with app.app_context():
            db.session.add(Report(
                post_id=post_id,
                reporter_id=reporter_id,
                reason='Información falsa',
                details='Detalle del reporte de publicación',
                status='pending',
            ))
            db.session.add(CommentReport(
                comment_id=comment_id,
                reporter_id=reporter_id,
                reason='Acoso o insultos',
                details='Detalle del reporte de comentario',
                status='reviewing',
            ))
            db.session.add(ChatMessageReport(
                message_id=message_id,
                reporter_id=reporter_id,
                reason='Spam o fraude',
                details='Detalle del reporte de chat',
                status='pending',
            ))
            db.session.add(ModerationStrike(
                user_id=target_id,
                issued_by=admin_id,
                source_type='post',
                source_id=post_id,
                source_label='Publicación reportada',
                reason='Información falsa',
                details='Strike visible para auditoría',
                content_excerpt='Extracto visible para auditoría',
                strike_number=1,
                consequence='warning',
            ))
            target = db.session.get(User, target_id)
            assert target is not None
            target.abuse_strikes = 1
            db.session.commit()

        self.create_audit_log(
            actor_id=admin_id,
            target_user_id=target_id,
            event_type='user_roles.update',
            workspace='admin',
            summary='Actualizó roles visibles',
        )

        non_admin_response = self.client_for(reporter_id).get(f'/admin/user/{target_id}/audit_summary')
        self.assertEqual(non_admin_response.status_code, 403)

        response = self.client_for(admin_id).get(f'/admin/user/{target_id}/audit_summary')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(payload.get('user', {}).get('username'), 'historial_visible_admin')

        summary = payload.get('summary') or {}
        self.assertEqual(summary.get('posts'), 1)
        self.assertEqual(summary.get('comments'), 1)
        self.assertEqual(summary.get('active_reports'), 3)
        self.assertEqual(summary.get('strikes'), 1)

        reports = payload.get('reports') or []
        source_types = {report.get('source_type') for report in reports}
        self.assertTrue({'post', 'comment', 'chat'}.issubset(source_types))
        self.assertEqual((payload.get('strikes') or [{}])[0].get('reason'), 'Información falsa')
        self.assertTrue(any(
            log.get('event_type') == 'user_roles.update'
            for log in (payload.get('audit_logs') or [])
        ))

        with app.app_context():
            audit_view = AuditLog.query.filter_by(
                event_type='user_audit.view',
                actor_id=admin_id,
                target_user_id=target_id,
            ).first()
            self.assertIsNotNone(audit_view)

    def test_admin_report_filters_cover_posts_chat_and_comments(self):
        admin_id = self.create_user('admin')
        reporter_id = self.create_user('reportera_filtros_reportes')
        author_id = self.create_user('autora_filtros_reportes')
        post_match_id = self.create_public_post(
            author_id,
            caption='Banqueta rota avenida filtro',
            location_name='Avenida Filtro',
        )
        post_restored_id = self.create_public_post(
            author_id,
            caption='Otro lugar restaurado filtro',
            location_name='Zona Restaurada',
        )
        comment_match_id = self.create_comment(author_id, post_match_id, 'Comentario con insulto filtro')
        comment_other_id = self.create_comment(author_id, post_restored_id, 'Comentario spam filtro')
        _, message_match_id = self.create_chat_message(
            author_id,
            room_name='Sala de archivos filtro',
            content='archivo sospechoso filtro',
        )
        _, message_other_id = self.create_chat_message(
            author_id,
            room_name='Sala de amenazas filtro',
            content='mensaje amenaza filtro',
        )

        now = app_module.utc_now_naive()
        with app.app_context():
            db.session.add(Report(
                post_id=post_match_id,
                reporter_id=reporter_id,
                reason='Amenaza o violencia',
                details='banqueta peligrosa para filtrar',
                status='pending',
                created_at=now,
            ))
            db.session.add(Report(
                post_id=post_restored_id,
                reporter_id=reporter_id,
                reason='Información falsa',
                details='reporte ya restaurado',
                status='restored',
                created_at=now - timedelta(days=2),
            ))
            db.session.add(ChatMessageReport(
                message_id=message_match_id,
                reporter_id=reporter_id,
                reason='Spam o fraude',
                details='archivo sospechoso',
                status='pending',
                created_at=now,
            ))
            db.session.add(ChatMessageReport(
                message_id=message_other_id,
                reporter_id=reporter_id,
                reason='Amenaza o violencia',
                details='amenaza distinta',
                status='pending',
                created_at=now,
            ))
            db.session.add(CommentReport(
                comment_id=comment_match_id,
                reporter_id=reporter_id,
                reason='Acoso o insultos',
                details='insulto directo',
                status='pending',
                created_at=now,
            ))
            db.session.add(CommentReport(
                comment_id=comment_other_id,
                reporter_id=reporter_id,
                reason='Spam o fraude',
                details='spam distinto',
                status='pending',
                created_at=now - timedelta(days=10),
            ))
            db.session.commit()

        admin = self.client_for(admin_id)
        post_search = admin.get('/admin/content?tab=reportes&reports_subtab=reportados&report_q=banqueta')
        self.assertEqual(post_search.status_code, 200)
        post_search_html = post_search.get_data(as_text=True)
        self.assertIn('admin-report-filter-panel', post_search_html)
        self.assertIn('Banqueta rota avenida filtro', post_search_html)
        self.assertNotIn('Otro lugar restaurado filtro', post_search_html)

        restored_posts = admin.get('/admin/content?tab=reportes&reports_subtab=reportados&report_status=restored')
        self.assertEqual(restored_posts.status_code, 200)
        restored_html = restored_posts.get_data(as_text=True)
        self.assertIn('Restaurado', restored_html)
        self.assertIn('Otro lugar restaurado filtro', restored_html)
        self.assertNotIn('Banqueta rota avenida filtro', restored_html)

        chat_reason = admin.get('/admin/content?tab=reportes&reports_subtab=reportes-chat&report_reason=Spam+o+fraude')
        self.assertEqual(chat_reason.status_code, 200)
        chat_reason_html = chat_reason.get_data(as_text=True)
        self.assertIn('archivo sospechoso filtro', chat_reason_html)
        self.assertNotIn('mensaje amenaza filtro', chat_reason_html)

        comment_search = admin.get('/admin/content?tab=reportes&reports_subtab=reportes-comentarios&report_since=today&report_q=insulto')
        self.assertEqual(comment_search.status_code, 200)
        comment_search_html = comment_search.get_data(as_text=True)
        self.assertIn('Comentario con insulto filtro', comment_search_html)
        self.assertNotIn('Comentario spam filtro', comment_search_html)

        shell_html = admin.get('/admin?tab=reportes&reports_subtab=reportes-chat&report_reason=Spam+o+fraude').get_data(as_text=True)
        self.assertIn('report_reason=Spam+o+fraude', shell_html)

    def test_background_jobs_retry_false_results_and_record_status(self):
        submit_job = app.extensions.get('violeta_submit_background_job')
        self.assertTrue(callable(submit_job))

        class FakeExecutor:
            def __init__(self):
                self.submitted = []

            def submit(self, fn):
                self.submitted.append(fn)
                return object()

        fake_executor = FakeExecutor()
        original_config = {
            key: app.config.get(key)
            for key in (
                'TESTING',
                'BACKGROUND_JOBS_ENABLED',
                'BACKGROUND_JOBS_INLINE',
                'BACKGROUND_JOB_MAX_RETRIES',
                'BACKGROUND_JOB_RETRY_DELAY_SECONDS',
            )
        }
        original_executor = app.extensions.get('violeta_background_executor')

        def restore():
            app.config.update(original_config)
            app.extensions['violeta_background_executor'] = original_executor

        self.addCleanup(restore)

        stats = app.extensions.get('violeta_background_job_stats')
        self.assertIsNotNone(stats)
        before_retry = stats.get('smoke_retry_job.retry', 0)
        before_completed = stats.get('smoke_retry_job.completed', 0)
        before_failed = stats.get('smoke_fail_job.failed', 0)

        app.config.update(
            TESTING=False,
            BACKGROUND_JOBS_ENABLED=True,
            BACKGROUND_JOBS_INLINE=False,
            BACKGROUND_JOB_MAX_RETRIES=2,
            BACKGROUND_JOB_RETRY_DELAY_SECONDS=0,
        )
        app.extensions['violeta_background_executor'] = fake_executor

        attempts = []

        def flaky_job():
            attempts.append('attempt')
            if len(attempts) < 3:
                return False
            return 'ok'

        submit_job('smoke_retry_job', flaky_job)
        self.assertEqual(len(fake_executor.submitted), 1)
        with self.assertLogs(app.logger, level='WARNING') as retry_logs:
            self.assertEqual(fake_executor.submitted[0](), 'ok')
        self.assertEqual(len(attempts), 3)
        self.assertEqual(stats.get('smoke_retry_job.retry', 0) - before_retry, 2)
        self.assertEqual(stats.get('smoke_retry_job.completed', 0) - before_completed, 1)
        self.assertTrue(any('background_job_retry name=smoke_retry_job' in item for item in retry_logs.output))

        fail_attempts = []

        def failing_job():
            fail_attempts.append('attempt')
            return False

        submit_job('smoke_fail_job', failing_job)
        self.assertEqual(len(fake_executor.submitted), 2)
        with self.assertLogs(app.logger, level='WARNING') as fail_logs:
            self.assertIsNone(fake_executor.submitted[1]())
        self.assertEqual(len(fail_attempts), 3)
        self.assertEqual(stats.get('smoke_fail_job.failed', 0) - before_failed, 1)
        self.assertTrue(any('background_job_failed name=smoke_fail_job' in item for item in fail_logs.output))

        events = list(app.extensions.get('violeta_background_job_events') or [])
        self.assertTrue(any(
            event.get('job_name') == 'smoke_retry_job' and event.get('status') == 'completed'
            for event in events
        ))
        self.assertTrue(any(
            event.get('job_name') == 'smoke_fail_job' and event.get('status') == 'failed'
            for event in events
        ))
        with app.app_context():
            persisted_statuses = {
                event.status
                for event in BackgroundJobEvent.query
                .filter(BackgroundJobEvent.job_name.in_(['smoke_retry_job', 'smoke_fail_job']))
                .all()
            }
            self.assertTrue({'queued', 'retry', 'completed', 'failed'}.issubset(persisted_statuses))

        admin_id = self.create_user('background_persist_admin', roles=[ROLE_SUPER_ADMIN])
        bg_events = app.extensions.get('violeta_background_job_events')
        bg_lock = app.extensions.get('violeta_background_job_stats_lock')
        saved_stats = dict(stats)
        saved_events = list(bg_events or [])

        def restore_background_memory():
            if bg_lock is not None:
                with bg_lock:
                    stats.clear()
                    stats.update(saved_stats)
                    if bg_events is not None:
                        bg_events.clear()
                        bg_events.extend(saved_events)
            else:
                stats.clear()
                stats.update(saved_stats)
                if bg_events is not None:
                    bg_events.clear()
                    bg_events.extend(saved_events)

        self.addCleanup(restore_background_memory)
        if bg_lock is not None:
            with bg_lock:
                stats.clear()
                if bg_events is not None:
                    bg_events.clear()
        else:
            stats.clear()
            if bg_events is not None:
                bg_events.clear()

        diagnostics_response = self.client_for(admin_id).get('/admin/background-jobs?format=json')
        self.assertEqual(diagnostics_response.status_code, 200)
        diagnostics = diagnostics_response.get_json() or {}
        diagnostics_health = diagnostics.get('background_job_health') or {}
        self.assertGreaterEqual(diagnostics_health.get('failed_count') or 0, 1)
        self.assertTrue(any(
            row.get('job_name') == 'smoke_retry_job' and row.get('completed_count', 0) >= 1
            for row in (diagnostics.get('background_job_rows') or [])
        ))

    def test_background_job_event_retention_purges_old_rows(self):
        admin_id = self.create_user('background_retention_admin', roles=[ROLE_SUPER_ADMIN])
        now = datetime.now()
        with app.app_context():
            db.session.add(BackgroundJobEvent(
                job_name='old_smoke_job',
                status='failed',
                attempt=1,
                error='evento viejo',
                created_at=now - timedelta(days=45),
            ))
            db.session.add(BackgroundJobEvent(
                job_name='fresh_smoke_job',
                status='completed',
                attempt=1,
                duration_ms=12.3,
                created_at=now - timedelta(days=2),
            ))
            db.session.commit()

        with mock.patch.dict(os.environ, {'BACKGROUND_JOB_EVENT_RETENTION_DAYS': '30'}):
            with app.app_context():
                self.assertEqual(app_module.count_expired_background_job_events(), 1)

            admin = self.client_for(admin_id)
            before = admin.get('/admin/background-jobs?format=json').get_json() or {}
            before_retention = before.get('background_job_retention') or {}
            self.assertEqual(before_retention.get('retention_days'), 30)
            self.assertEqual(before_retention.get('expired_events'), 1)

            purge_response = admin.post('/admin/background-jobs/purge', json={})
            self.assertEqual(purge_response.status_code, 200)
            purge_payload = purge_response.get_json() or {}
            self.assertTrue(purge_payload.get('success'))
            self.assertEqual(purge_payload.get('deleted_count'), 1)

            with app.app_context():
                remaining_names = {
                    event.job_name
                    for event in BackgroundJobEvent.query.order_by(BackgroundJobEvent.id.asc()).all()
                }
                self.assertNotIn('old_smoke_job', remaining_names)
                self.assertIn('fresh_smoke_job', remaining_names)
                self.assertEqual(app_module.count_expired_background_job_events(), 0)

            after = admin.get('/admin/background-jobs?format=json').get_json() or {}
            after_retention = after.get('background_job_retention') or {}
            self.assertEqual(after_retention.get('expired_events'), 0)
            self.assertGreaterEqual(after_retention.get('total_events') or 0, 1)

    def test_background_job_diagnostics_filters_status_job_and_date(self):
        admin_id = self.create_user('background_filter_admin', roles=[ROLE_SUPER_ADMIN])
        now = app_module.utc_now_naive()
        with app.app_context():
            db.session.add(BackgroundJobEvent(
                job_name='email_delivery',
                status='failed',
                attempt=2,
                error='smtp timeout',
                created_at=now - timedelta(days=2),
            ))
            db.session.add(BackgroundJobEvent(
                job_name='email_delivery',
                status='completed',
                attempt=1,
                duration_ms=18.4,
                created_at=now - timedelta(days=2),
            ))
            db.session.add(BackgroundJobEvent(
                job_name='reverse_geocode_post',
                status='failed',
                attempt=1,
                error='network',
                created_at=now - timedelta(days=10),
            ))
            db.session.add(BackgroundJobEvent(
                job_name='upload_image_processing',
                status='completed',
                attempt=1,
                duration_ms=22.1,
                created_at=now,
            ))
            db.session.commit()

        admin = self.client_for(admin_id)
        response = admin.get(
            '/admin/background-jobs?format=json&bg_job=email_delivery&bg_status=failed&bg_since=7d'
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        filters = payload.get('background_job_filters') or {}
        self.assertEqual(filters.get('job_name'), 'email_delivery')
        self.assertEqual(filters.get('status'), 'failed')
        self.assertEqual(filters.get('since'), '7d')
        self.assertEqual(filters.get('active_count'), 3)

        health = payload.get('background_job_health') or {}
        self.assertEqual(health.get('failed_count'), 1)
        self.assertEqual(health.get('completed_count'), 0)
        self.assertTrue(all(
            event.get('job_name') == 'email_delivery' and event.get('status') == 'failed'
            for event in (health.get('recent_events') or [])
        ))

        rows = payload.get('background_job_rows') or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get('job_name'), 'email_delivery')
        self.assertEqual(rows[0].get('failed_count'), 1)
        self.assertEqual(rows[0].get('completed_count'), 0)

        today_response = admin.get('/admin/background-jobs?format=json&bg_status=completed&bg_since=today')
        self.assertEqual(today_response.status_code, 200)
        today_payload = today_response.get_json() or {}
        today_rows = today_payload.get('background_job_rows') or []
        self.assertTrue(any(row.get('job_name') == 'upload_image_processing' for row in today_rows))
        self.assertFalse(any(row.get('job_name') == 'email_delivery' for row in today_rows))

        html = admin.get('/admin/background-jobs?bg_job=email_delivery&bg_status=failed&bg_since=7d').get_data(as_text=True)
        self.assertIn('Filtrar diagnóstico', html)
        self.assertIn('Correos', html)
        self.assertIn('Falló', html)
        self.assertIn('Últimos 7 días', html)
        self.assertIn('Exportar', html)

        export_response = admin.get('/admin/background-jobs/export?bg_job=email_delivery&bg_status=failed&bg_since=7d')
        self.assertEqual(export_response.status_code, 200)
        self.assertIn('text/csv', export_response.headers.get('Content-Type', ''))
        csv_text = export_response.get_data(as_text=True)
        self.assertIn('email_delivery', csv_text)
        self.assertIn('smtp timeout', csv_text)
        self.assertNotIn('reverse_geocode_post', csv_text)

    def test_admin_background_job_manual_retry_reprocesses_image_and_geocoding(self):
        admin_id = self.create_user('admin')
        author_id = self.create_user('background_retry_author')
        non_admin_id = self.create_user('background_retry_non_admin')
        image_post_id = self.create_public_post(
            author_id,
            caption='Imagen pendiente de reproceso',
            show_public=False,
            location_name='Centro',
        )
        reported_hidden_post_id = self.create_public_post(
            author_id,
            caption='Oculta por reporte activo',
            show_public=False,
            location_name='Reporte activo',
        )
        geocode_post_id = self.create_public_post(
            author_id,
            caption='Geocoding pendiente',
            location_name='',
            city='',
            country='',
            latitude=25.7000,
            longitude=-100.3300,
        )

        now = app_module.utc_now_naive()
        with app.app_context():
            db.session.add(Report(
                post_id=reported_hidden_post_id,
                reporter_id=non_admin_id,
                reason='Doxxing o datos personales',
                status='pending',
                created_at=now,
            ))
            db.session.commit()

        admin = self.client_for(admin_id)
        diagnostics_html = admin.get('/admin/background-jobs').get_data(as_text=True)
        self.assertIn('Mantenimiento manual', diagnostics_html)
        self.assertIn('Reprocesar imágenes', diagnostics_html)
        self.assertIn('Completar geocoding', diagnostics_html)
        self.assertIn('Imagen pendiente de reproceso', diagnostics_html)
        self.assertNotIn('Oculta por reporte activo', diagnostics_html)

        non_admin_response = self.client_for(non_admin_id).post(
            '/admin/background-jobs/retry',
            json={'action': 'all'},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(non_admin_response.status_code, 403)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return json.dumps({
                    'address': {
                        'road': 'Calle Reintento',
                        'city': 'Monterrey',
                        'state': 'Nuevo León',
                        'country': 'México',
                    }
                }).encode('utf-8')

        def fake_urlopen(request_obj, timeout=4):  # noqa: ARG001
            self.assertIn('nominatim.openstreetmap.org/reverse', request_obj.full_url)
            return FakeResponse()

        invalid_response = admin.post('/admin/background-jobs/retry', json={'action': 'desconocida'})
        self.assertEqual(invalid_response.status_code, 400)

        with mock.patch.object(app_module, 'urlopen', side_effect=fake_urlopen):
            retry_response = admin.post('/admin/background-jobs/retry', json={'action': 'all', 'limit': 10})
        self.assertEqual(retry_response.status_code, 200)
        payload = retry_response.get_json() or {}
        self.assertTrue(payload.get('success'))
        self.assertEqual(payload.get('queued_count'), 2)
        queued_types = {item.get('type') for item in payload.get('queued') or []}
        self.assertEqual(queued_types, {'image_processing', 'geocoding'})

        with app.app_context():
            image_meta = PostMeta.query.filter_by(post_id=image_post_id).first()
            self.assertIsNotNone(image_meta)
            assert image_meta is not None
            self.assertTrue(bool(image_meta.show_public))

            reported_meta = PostMeta.query.filter_by(post_id=reported_hidden_post_id).first()
            self.assertIsNotNone(reported_meta)
            assert reported_meta is not None
            self.assertFalse(bool(reported_meta.show_public))

            geocode_post = db.session.get(Post, geocode_post_id)
            self.assertIsNotNone(geocode_post)
            assert geocode_post is not None
            self.assertEqual(geocode_post.location_name, 'Calle Reintento, Monterrey, Nuevo León')
            self.assertEqual(geocode_post.city, 'Monterrey')
            self.assertEqual(geocode_post.country, 'México')

    def test_email_delivery_queues_background_job_when_enabled(self):
        deliver_email = app.extensions.get('violeta_deliver_email_message')
        self.assertTrue(callable(deliver_email))

        class FakeExecutor:
            def __init__(self):
                self.submitted = []

            def submit(self, fn):
                self.submitted.append(fn)
                return object()

        fake_executor = FakeExecutor()
        original_config = {
            key: app.config.get(key)
            for key in (
                'TESTING',
                'BACKGROUND_JOBS_ENABLED',
                'BACKGROUND_JOBS_INLINE',
                'ASYNC_EMAIL_DELIVERY',
                'MAIL_DELIVERY_METHOD',
                'MAIL_SERVER',
                'MAIL_USERNAME',
                'MAIL_DEFAULT_SENDER',
            )
        }
        original_executor = app.extensions.get('violeta_background_executor')

        def restore():
            app.config.update(original_config)
            app.extensions['violeta_background_executor'] = original_executor

        self.addCleanup(restore)

        app.config.update(
            TESTING=False,
            BACKGROUND_JOBS_ENABLED=True,
            BACKGROUND_JOBS_INLINE=False,
            ASYNC_EMAIL_DELIVERY=True,
            MAIL_DELIVERY_METHOD='smtp',
            MAIL_SERVER='smtp.example.test',
            MAIL_USERNAME='',
            MAIL_DEFAULT_SENDER='no-reply@example.test',
        )
        app.extensions['violeta_background_executor'] = fake_executor

        queued = deliver_email('Prueba', ['usuaria@example.test'], 'Texto de prueba')
        self.assertTrue(queued)
        self.assertEqual(len(fake_executor.submitted), 1)

        app.config.update(MAIL_SERVER='', MAIL_DEFAULT_SENDER='')
        not_queued = deliver_email('Prueba', ['usuaria@example.test'], 'Texto de prueba')
        self.assertFalse(not_queued)
        self.assertEqual(len(fake_executor.submitted), 1)

    def test_static_and_upload_cache_headers(self):
        public_filename = self.save_seed_image('cache-public.jpg')
        verify_dir = UPLOAD_DIR / 'verify'
        verify_dir.mkdir(parents=True, exist_ok=True)
        verify_filename = 'verify/cache-private.jpg'
        Image.new('RGB', (32, 32), (24, 12, 48)).save(UPLOAD_DIR / verify_filename, format='JPEG')

        static_response = app.test_client().get('/static/images/default_avatar.jpg')
        self.assertEqual(static_response.status_code, 200)
        self.assertIn('public, max-age=604800, immutable', static_response.headers.get('Cache-Control', ''))
        self.assertNotIn('Cookie', static_response.headers.get('Vary', ''))

        public_response = app.test_client().get(f'/uploads/{public_filename}')
        self.assertEqual(public_response.status_code, 200)
        self.assertIn('public, max-age=604800', public_response.headers.get('Cache-Control', ''))
        self.assertIn('stale-while-revalidate=86400', public_response.headers.get('Cache-Control', ''))

        verify_response = app.test_client().get(f'/uploads/{verify_filename}')
        self.assertEqual(verify_response.status_code, 403)
        self.assertEqual(verify_response.headers.get('Cache-Control'), 'no-cache, no-store, must-revalidate')

        optimized_response = app.test_client().get(f'/uploads/optimized/720/{public_filename}')
        self.assertEqual(optimized_response.status_code, 200)
        self.assertIn('public, max-age=31536000, immutable', optimized_response.headers.get('Cache-Control', ''))

    def test_optimized_upload_fallback_queues_missing_variant(self):
        public_filename = self.save_seed_image('async-optimized.jpg')
        stem = os.path.splitext(os.path.basename(public_filename))[0]
        digest = hashlib.sha256(public_filename.encode('utf-8')).hexdigest()[:12]
        optimized_path = UPLOAD_DIR / '_optimized' / 'w720' / f'{stem}-{digest}-w720.webp'
        self.assertFalse(optimized_path.exists())

        class FakeExecutor:
            def __init__(self):
                self.submitted = []

            def submit(self, fn):
                self.submitted.append(fn)
                return object()

        fake_executor = FakeExecutor()
        original_config = {
            key: app.config.get(key)
            for key in (
                'TESTING',
                'BACKGROUND_JOBS_ENABLED',
                'BACKGROUND_JOBS_INLINE',
                'ASYNC_UPLOAD_OPTIMIZATION',
            )
        }
        original_executor = app.extensions.get('violeta_background_executor')

        def restore():
            app.config.update(original_config)
            app.extensions['violeta_background_executor'] = original_executor

        self.addCleanup(restore)
        app.config.update(
            TESTING=False,
            BACKGROUND_JOBS_ENABLED=True,
            BACKGROUND_JOBS_INLINE=False,
            ASYNC_UPLOAD_OPTIMIZATION=True,
        )
        app.extensions['violeta_background_executor'] = fake_executor

        first_response = app.test_client().get(f'/uploads/optimized/720/{public_filename}')
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.headers.get('X-Violeta-Optimized-Fallback'), '1')
        self.assertIn('public, max-age=60', first_response.headers.get('Cache-Control', ''))
        self.assertIn('stale-while-revalidate=86400', first_response.headers.get('Cache-Control', ''))
        self.assertEqual(len(fake_executor.submitted), 1)
        self.assertFalse(optimized_path.exists())

        fake_executor.submitted[0]()
        self.assertTrue(optimized_path.exists())

        second_response = app.test_client().get(f'/uploads/optimized/720/{public_filename}')
        self.assertEqual(second_response.status_code, 200)
        self.assertNotEqual(second_response.headers.get('X-Violeta-Optimized-Fallback'), '1')
        self.assertIn('image/webp', second_response.headers.get('Content-Type', ''))
        self.assertIn('public, max-age=31536000, immutable', second_response.headers.get('Cache-Control', ''))

    def test_optimized_media_srcset_only_lists_real_ready_variants(self):
        user_id = self.create_user('srcset_smoke')
        client = self.client_for(user_id)

        small_post_id = self.create_public_post(user_id, caption='Imagen chica sin srcset falso')
        small_html = client.get(f'/post/{small_post_id}').get_data(as_text=True)
        self.assertIn('/uploads/optimized/720/', small_html)
        self.assertNotIn('srcset=', small_html)
        self.assertNotIn(' 360w', small_html)
        self.assertNotIn(' 720w', small_html)

        large_filename = 'large-srcset.jpg'
        Image.new('RGB', (1200, 900), (122, 64, 210)).save(UPLOAD_DIR / large_filename, format='JPEG')
        large_post_id = self.create_public_post(user_id, caption='Imagen grande con variantes reales')
        with app.app_context():
            post = db.session.get(Post, large_post_id)
            assert post is not None
            post.image_filename = large_filename
            db.session.add(post)
            db.session.commit()

        missing_variant_html = client.get(f'/post/{large_post_id}').get_data(as_text=True)
        self.assertNotIn('srcset=', missing_variant_html)

        for width in (360, 720, 1080):
            variant_response = client.get(f'/uploads/optimized/{width}/{large_filename}')
            try:
                self.assertEqual(variant_response.status_code, 200)
                self.assertIn('image/webp', variant_response.headers.get('Content-Type', ''))
            finally:
                variant_response.close()

        ready_variant_html = client.get(f'/post/{large_post_id}').get_data(as_text=True)
        self.assertIn('/uploads/optimized/360/large-srcset.jpg 360w', ready_variant_html)
        self.assertIn('/uploads/optimized/720/large-srcset.jpg 720w', ready_variant_html)
        self.assertIn('/uploads/optimized/1080/large-srcset.jpg 1080w', ready_variant_html)
        self.assertNotIn('/uploads/large-srcset.jpg 360w', ready_variant_html)

        original_config = {
            key: app.config.get(key)
            for key in (
                'UPLOAD_BACKEND',
                'SUPABASE_URL',
                'SUPABASE_SERVICE_ROLE_KEY',
                'SUPABASE_STORAGE_BUCKET',
            )
        }
        self.addCleanup(lambda: app.config.update(original_config))
        app.config.update(
            UPLOAD_BACKEND='supabase',
            SUPABASE_URL='https://example.supabase.co',
            SUPABASE_SERVICE_ROLE_KEY='service-role',
            SUPABASE_STORAGE_BUCKET='uploads',
        )
        external_html = client.get(f'/post/{large_post_id}').get_data(as_text=True)
        self.assertIn('https://example.supabase.co/storage/v1/object/public/uploads/large-srcset.jpg', external_html)
        self.assertNotIn(' 360w', external_html)
        self.assertNotIn(' 720w', external_html)
        self.assertNotIn(' 1080w', external_html)

    def test_pwa_manifest_service_worker_and_offline_shell(self):
        user_id = self.create_user('pwa_smoke')
        html_response = self.client_for(user_id).get('/')
        self.assertEqual(html_response.status_code, 200)
        html = html_response.get_data(as_text=True)
        self.assertIn('rel="manifest"', html)
        self.assertIn('/manifest.json', html)
        self.assertIn('name="theme-color"', html)
        self.assertIn('viewport-fit=cover', html)
        self.assertNotIn('user-scalable=no', html)

        manifest_response = app.test_client().get('/manifest.json')
        legacy_manifest_response = app.test_client().get('/manifest.webmanifest')
        for response in (manifest_response, legacy_manifest_response):
            self.assertEqual(response.status_code, 200)
            self.assertIn('application/manifest+json', response.headers.get('Content-Type', ''))
            self.assertIn('public, max-age=604800', response.headers.get('Cache-Control', ''))
            self.assertNotIn('Cookie', response.headers.get('Vary', ''))
        manifest = json.loads(manifest_response.get_data(as_text=True))
        self.assertEqual(manifest.get('name'), 'Violeta')
        self.assertEqual(manifest.get('display'), 'standalone')
        self.assertEqual(manifest.get('start_url'), '/?source=pwa')
        self.assertTrue(any(icon.get('sizes') == '192x192' for icon in manifest.get('icons') or []))
        self.assertTrue(any(icon.get('purpose') == 'maskable' for icon in manifest.get('icons') or []))
        self.assertTrue(any(icon.get('src') == '/static/images/pwa/maskable-512.png' for icon in manifest.get('icons') or []))
        self.assertTrue(any(shortcut.get('url', '').startswith('/safety') for shortcut in manifest.get('shortcuts') or []))

        service_worker_response = app.test_client().get('/service-worker.js')
        self.assertEqual(service_worker_response.status_code, 200)
        self.assertEqual(service_worker_response.headers.get('Service-Worker-Allowed'), '/')
        self.assertEqual(service_worker_response.headers.get('Cache-Control'), 'no-cache, no-store, must-revalidate')
        self.assertNotIn('Cookie', service_worker_response.headers.get('Vary', ''))
        service_worker = service_worker_response.get_data(as_text=True)
        self.assertIn('APP_SHELL_CACHE', service_worker)
        self.assertIn('violeta-app-shell-v4', service_worker)
        self.assertIn('/static/offline.html', service_worker)
        self.assertIn('/manifest.json', service_worker)
        self.assertIn('/static/images/pwa/maskable-512.png', service_worker)
        self.assertIn('getOfflineShell', service_worker)

        offline_response = app.test_client().get('/static/offline.html')
        self.assertEqual(offline_response.status_code, 200)
        self.assertNotIn('Cookie', offline_response.headers.get('Vary', ''))
        offline_html = offline_response.get_data(as_text=True)
        self.assertIn('Sin conexión', offline_html)
        self.assertIn('Beta v1.0', offline_html)
        self.assertIn('images/favicon.png', offline_html)
        self.assertIn('border-radius: 50%', offline_html)
        self.assertIn('Volver al inicio', offline_html)
        self.assertIn('Reintentar', offline_html)

    def test_feed_render_pagination_filters_optimized_images_and_timing_headers(self):
        original_page_size = app.config.get('FEED_PAGE_SIZE')
        app.config['FEED_PAGE_SIZE'] = 2
        def restore_page_size():
            if original_page_size is None:
                app.config.pop('FEED_PAGE_SIZE', None)
            else:
                app.config['FEED_PAGE_SIZE'] = original_page_size
        self.addCleanup(restore_page_size)

        author_id = self.create_user('autora_feed_critico')
        viewer = self.client_for(author_id)
        now = app_module.utc_now_naive()
        near_post_id = self.create_public_post(
            author_id,
            caption='Reporte de banqueta cerca',
            latitude=25.6866,
            longitude=-100.3161,
            created_at=now,
            categories=['Banquetas en mal estado'],
        )
        second_post_id = self.create_public_post(
            author_id,
            caption='Reporte de poca iluminación',
            latitude=25.6870,
            longitude=-100.3164,
            created_at=now - timedelta(minutes=2),
            categories=['Poca iluminación'],
        )
        old_post_id = self.create_public_post(
            author_id,
            caption='Reporte antiguo',
            latitude=25.6868,
            longitude=-100.3162,
            created_at=now - timedelta(days=2),
            categories=['Terrenos baldíos'],
        )
        far_post_id = self.create_public_post(
            author_id,
            caption='Reporte lejano',
            latitude=25.8000,
            longitude=-100.4500,
            created_at=now - timedelta(minutes=4),
            categories=['Zona insegura'],
        )

        index_response = viewer.get('/')
        self.assertEqual(index_response.status_code, 200)
        self.assert_timing_headers(index_response)

        feed_response = viewer.get('/feed')
        self.assertEqual(feed_response.status_code, 200)
        self.assert_timing_headers(feed_response)
        payload = feed_response.get_json() or {}
        self.assertTrue(payload.get('has_next'))
        self.assertEqual(payload.get('page'), 1)
        self.assertEqual(payload.get('next_page'), 2)
        self.assertEqual(len(payload.get('posts') or []), 2)
        self.assertEqual([int(item['id']) for item in payload['posts']], [near_post_id, second_post_id])
        self.assertTrue(payload['posts'][0]['image_url'].startswith('/uploads/optimized/720/'))

        page_two = viewer.get('/feed?page=2')
        self.assertEqual(page_two.status_code, 200)
        page_two_payload = page_two.get_json() or {}
        self.assertEqual([int(item['id']) for item in page_two_payload.get('posts') or []], [far_post_id, old_post_id])
        self.assertFalse(page_two_payload.get('has_next'))

        category_response = viewer.get('/feed?categories=Banquetas%20en%20mal%20estado')
        self.assertEqual(category_response.status_code, 200)
        category_payload = category_response.get_json() or {}
        self.assertEqual([int(item['id']) for item in category_payload.get('posts') or []], [near_post_id])
        self.assertEqual(category_payload['posts'][0]['categories'], ['Banquetas en mal estado'])

        today_response = viewer.get('/feed?today=1')
        self.assertEqual(today_response.status_code, 200)
        today_ids = [int(item['id']) for item in (today_response.get_json() or {}).get('posts') or []]
        self.assertIn(near_post_id, today_ids)
        self.assertIn(second_post_id, today_ids)
        self.assertNotIn(old_post_id, today_ids)

        near_response = viewer.get('/feed?near=1&lat=25.6866&lng=-100.3161')
        self.assertEqual(near_response.status_code, 200)
        near_ids = [int(item['id']) for item in (near_response.get_json() or {}).get('posts') or []]
        self.assertIn(near_post_id, near_ids)
        self.assertNotIn(far_post_id, near_ids)

        empty_filters = viewer.get('/feed?categories=&near=1&today=0')
        self.assertEqual(empty_filters.status_code, 200)

    def test_upload_creates_post_with_categories_and_optimized_feed_url(self):
        admin_id = self.create_user('admin')
        client = self.client_for(admin_id)

        response = client.post(
            '/upload',
            data={
                'caption': 'Reporte con categorías #smoke',
                'latitude': '25.7000',
                'longitude': '-100.3300',
                'location_name': 'Centro',
                'city': 'Monterrey',
                'country': 'México',
                'location_visibility': 'exact',
                'show_public': 'true',
                'allow_likes': 'true',
                'allow_comments': 'true',
                'capture_source': 'upload',
                'categories': ['Banquetas en mal estado', 'Terrenos baldíos'],
                'image': self.image_upload('categorias.jpg'),
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assert_timing_headers(response)

        with app.app_context():
            post = Post.query.order_by(Post.id.desc()).first()
            self.assertIsNotNone(post)
            assert post is not None
            self.assertEqual(post.caption, 'Reporte con categorías #smoke')
            self.assertEqual(json.loads(post.categories or '[]'), ['Banquetas en mal estado', 'Terrenos baldíos'])
            post_id = int(post.id)
            post_filename = post.image_filename

        feed_post = self.fetch_feed_post(client, post_id)
        self.assertIsNotNone(feed_post)
        assert feed_post is not None
        self.assertEqual(feed_post['categories'], ['Banquetas en mal estado', 'Terrenos baldíos'])
        self.assertTrue(feed_post['image_url'].startswith('/uploads/optimized/720/'))
        stem = os.path.splitext(os.path.basename(post_filename))[0]
        digest = hashlib.sha256(post_filename.encode('utf-8')).hexdigest()[:12]
        optimized_name = f'{stem}-{digest}-w720.webp'
        self.assertTrue((UPLOAD_DIR / '_optimized' / 'w720' / optimized_name).exists())

    def test_upload_queues_image_processing_and_hides_post_until_finished(self):
        admin_id = self.create_user('admin')
        client = self.client_for(admin_id)

        class FakeExecutor:
            def __init__(self):
                self.submitted = []

            def submit(self, fn):
                self.submitted.append(fn)
                return object()

        fake_executor = FakeExecutor()
        original_config = {
            key: app.config.get(key)
            for key in (
                'TESTING',
                'BACKGROUND_JOBS_ENABLED',
                'BACKGROUND_JOBS_INLINE',
                'ASYNC_IMAGE_PROCESSING',
                'ASYNC_UPLOAD_OPTIMIZATION',
            )
        }
        original_executor = app.extensions.get('violeta_background_executor')

        def restore():
            app.config.update(original_config)
            app.extensions['violeta_background_executor'] = original_executor

        self.addCleanup(restore)

        app.config.update(
            TESTING=False,
            BACKGROUND_JOBS_ENABLED=True,
            BACKGROUND_JOBS_INLINE=False,
            ASYNC_IMAGE_PROCESSING=True,
            ASYNC_UPLOAD_OPTIMIZATION=True,
        )
        app.extensions['violeta_background_executor'] = fake_executor

        response = client.post(
            '/upload',
            data={
                'caption': 'Reporte con procesamiento async',
                'latitude': '25.7000',
                'longitude': '-100.3300',
                'location_name': 'Centro',
                'city': 'Monterrey',
                'country': 'México',
                'location_visibility': 'exact',
                'show_public': 'true',
                'allow_likes': 'true',
                'allow_comments': 'true',
                'capture_source': 'upload',
                'image': self.image_upload('async-processing.jpg'),
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(fake_executor.submitted), 1)

        with app.app_context():
            post = Post.query.order_by(Post.id.desc()).first()
            self.assertIsNotNone(post)
            assert post is not None
            meta = PostMeta.query.filter_by(post_id=post.id).first()
            self.assertIsNotNone(meta)
            assert meta is not None
            self.assertFalse(bool(meta.show_public))
            post_id = int(post.id)

        self.assertIsNone(self.fetch_feed_post(client, post_id))

    def test_background_reverse_geocoding_fills_missing_post_location(self):
        admin_id = self.create_user('admin')
        client = self.client_for(admin_id)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return json.dumps({
                    'address': {
                        'road': 'Calle Prueba',
                        'city': 'Monterrey',
                        'state': 'Nuevo León',
                        'country': 'México',
                    }
                }).encode('utf-8')

        def fake_urlopen(request_obj, timeout=4):  # noqa: ARG001
            self.assertIn('nominatim.openstreetmap.org/reverse', request_obj.full_url)
            return FakeResponse()

        with mock.patch.object(app_module, 'urlopen', side_effect=fake_urlopen):
            response = client.post(
                '/upload',
                data={
                    'caption': 'Reporte sin nombre de ubicación',
                    'latitude': '25.7000',
                    'longitude': '-100.3300',
                    'location_visibility': 'exact',
                    'show_public': 'true',
                    'allow_likes': 'true',
                    'allow_comments': 'true',
                    'capture_source': 'upload',
                    'image': self.image_upload('sin-ubicacion.jpg'),
                },
                content_type='multipart/form-data',
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            post = Post.query.order_by(Post.id.desc()).first()
            self.assertIsNotNone(post)
            assert post is not None
            self.assertEqual(post.location_name, 'Calle Prueba, Monterrey, Nuevo León')
            self.assertEqual(post.city, 'Monterrey')
            self.assertEqual(post.country, 'México')

    def test_admin_delete_user_removes_related_content_and_blocks_non_admin(self):
        admin_id = self.create_user('admin')
        target_id = self.create_user('delete_target')
        other_id = self.create_user('delete_other')
        reporter_id = self.create_user('delete_reporter')
        target_profile_pic = self.save_seed_image('target-profile.jpg')

        with app.app_context():
            target = db.session.get(User, target_id)
            assert target is not None
            target.profile_pic = target_profile_pic
            db.session.add(target)
            db.session.commit()

        target_post_id = self.create_public_post(target_id, caption='Post de usuaria a eliminar')
        other_post_id = self.create_public_post(other_id, caption='Post de otra usuaria')
        target_comment_id = self.create_comment(target_id, other_post_id, 'Comentario de usuaria a eliminar')
        other_comment_id = self.create_comment(other_id, other_post_id, 'Comentario reportable')

        with app.app_context():
            target_post = db.session.get(Post, target_post_id)
            assert target_post is not None
            target_post_filename = target_post.image_filename
            db.session.add(Like(user_id=target_id, post_id=other_post_id))
            db.session.add(Report(post_id=target_post_id, reporter_id=reporter_id, reason='Información falso'))
            db.session.add(Report(post_id=other_post_id, reporter_id=target_id, reason='Información falso'))
            db.session.add(CommentReport(comment_id=other_comment_id, reporter_id=target_id, reason='Spam o fraude'))
            db.session.commit()

        non_admin_response = self.client_for(other_id).post(f'/admin/delete_user/{target_id}')
        self.assertEqual(non_admin_response.status_code, 403)

        admin_response = self.client_for(admin_id).post(f'/admin/delete_user/{target_id}')
        self.assertEqual(admin_response.status_code, 200)
        payload = admin_response.get_json() or {}
        self.assertTrue(payload.get('success'))
        self.assert_timing_headers(admin_response)

        with app.app_context():
            self.assertIsNone(db.session.get(User, target_id))
            self.assertIsNone(db.session.get(Post, target_post_id))
            self.assertIsNone(db.session.get(Comment, target_comment_id))
            self.assertEqual(Like.query.filter_by(user_id=target_id).count(), 0)
            self.assertEqual(Report.query.filter_by(reporter_id=target_id).count(), 0)
            self.assertEqual(Report.query.filter_by(post_id=target_post_id).count(), 0)
            self.assertEqual(CommentReport.query.filter_by(reporter_id=target_id).count(), 0)

        self.assertFalse((UPLOAD_DIR / target_profile_pic).exists())
        self.assertFalse((UPLOAD_DIR / target_post_filename).exists())

    def test_privacy_pages_and_self_account_deletion_for_store_compliance(self):
        user_id = self.create_user('self_delete', password='Password123')
        other_id = self.create_user('self_delete_other')
        profile_pic = self.save_seed_image('self-delete-profile.jpg')
        other_post_id = self.create_public_post(other_id, caption='Post que recibe comentario')

        with app.app_context():
            user = db.session.get(User, user_id)
            assert user is not None
            user.profile_pic = profile_pic
            db.session.add(user)
            db.session.commit()

        own_post_id = self.create_public_post(user_id, caption='Post propio a eliminar')
        own_comment_id = self.create_comment(user_id, other_post_id, 'Comentario propio a eliminar')
        with app.app_context():
            own_post = db.session.get(Post, own_post_id)
            assert own_post is not None
            own_post_filename = own_post.image_filename
            db.session.add(Like(user_id=user_id, post_id=other_post_id))
            db.session.add(Report(post_id=other_post_id, reporter_id=user_id, reason='Información falsa'))
            db.session.add(SafetyContact(user_id=user_id, name='Contacto', phone='+528112345678', is_primary=True))
            db.session.commit()

        public_client = app.test_client()
        privacy_response = public_client.get('/privacy')
        self.assertEqual(privacy_response.status_code, 200)
        self.assertIn(b'Pol', privacy_response.data)
        privacy_html = privacy_response.get_data(as_text=True)
        self.assertIn('Beta v1.0', privacy_html)
        self.assertIn('Verificación visual', privacy_html)
        self.assert_timing_headers(privacy_response)

        for path, expected_text in (
            ('/beta', 'Violeta está en beta pública'),
            ('/support', 'Reportar problema'),
            ('/terms', 'Términos de uso'),
        ):
            response = public_client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(expected_text, response.get_data(as_text=True))
            self.assert_timing_headers(response)

        support_html = public_client.get('/support').get_data(as_text=True)
        self.assertIn('mailto:violetaapp38@gmail.com?subject=Soporte%20Violeta%20Beta', support_html)
        self.assertIn('data-copy-support-email', support_html)
        self.assertIn('Copiar correo', support_html)
        self.assertIn('supportCopyStatus', support_html)
        self.assertIn('navigator.clipboard', support_html)

        public_delete_response = public_client.get('/account/delete')
        self.assertEqual(public_delete_response.status_code, 200)
        self.assertIn(b'Iniciar sesi', public_delete_response.data)

        client = self.client_for(user_id)
        wrong_password_response = client.post(
            '/account/delete',
            data={'password': 'wrong-password', 'confirm_delete': 'ELIMINAR'},
        )
        self.assertEqual(wrong_password_response.status_code, 400)
        self.assertIn(b'contrase', wrong_password_response.data)

        delete_response = client.post(
            '/account/delete',
            data={'password': 'Password123', 'confirm_delete': 'ELIMINAR'},
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertIn('/login', delete_response.headers.get('Location', ''))
        self.assert_timing_headers(delete_response)

        with app.app_context():
            self.assertIsNone(db.session.get(User, user_id))
            self.assertIsNone(db.session.get(Post, own_post_id))
            self.assertIsNone(db.session.get(Comment, own_comment_id))
            self.assertEqual(Like.query.filter_by(user_id=user_id).count(), 0)
            self.assertEqual(Report.query.filter_by(reporter_id=user_id).count(), 0)
            self.assertEqual(SafetyContact.query.filter_by(user_id=user_id).count(), 0)
            self.assertEqual(AuditLog.query.filter_by(event_type='account.self_delete').count(), 1)

        self.assertFalse((UPLOAD_DIR / profile_pic).exists())
        self.assertFalse((UPLOAD_DIR / own_post_filename).exists())
        protected_response = client.get('/profile/edit', follow_redirects=False)
        self.assertEqual(protected_response.status_code, 302)

    def test_upload_camera_policy_and_safe_release(self):
        author_id = self.create_user('autora_feed')
        client = self.client_for(author_id)

        response = client.post(
            '/upload',
            data={
                'caption': 'Intento con galería',
                'latitude': '25.6866',
                'longitude': '-100.3161',
                'location_name': 'Av. Morelos y Escobedo',
                'city': 'Monterrey',
                'country': 'México',
                'location_visibility': 'exact',
                'show_public': 'true',
                'allow_likes': 'true',
                'allow_comments': 'true',
                'capture_source': 'upload',
                'image': self.image_upload('galeria.jpg'),
                **self.capture_fields(),
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(Post.query.count(), 0)

        response = client.post(
            '/upload',
            data={
                'caption': 'Reporte en vivo desde Morelos',
                'latitude': '25.7000',
                'longitude': '-100.3300',
                'location_name': 'Ubicación de publicación',
                'city': 'Monterrey',
                'country': 'México',
                'location_visibility': 'exact',
                'show_public': 'true',
                'allow_likes': 'true',
                'allow_comments': 'true',
                'capture_source': 'camera',
                'image': self.image_upload('camara.jpg'),
                **self.capture_fields(
                    lat=25.6866,
                    lng=-100.3161,
                    location_name='Av. Morelos y Escobedo',
                    city='Monterrey',
                    country='México',
                    motion_state='walking',
                    speed_mps=1.4,
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            post = Post.query.order_by(Post.id.desc()).first()
            assert post is not None
            post_id = int(post.id)
            self.assertGreater(post.publish_at, app_module.utc_now_naive())

        meta = self.get_post_meta(post_id)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.location_visibility, 'exact')

        status_response = client.get('/api/posts/pending-safety/status')
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.get_json() or {}
        self.assertEqual(status_payload.get('pending_count'), 1)

        self.assertNotIn(post_id, self.post_ids_in_feed(self.client_for()))

        before_delay = client.post('/api/posts/pending-safety/release', json={'lat': 25.6889, 'lng': -100.3161})
        self.assertEqual(before_delay.status_code, 200)
        self.assertEqual((before_delay.get_json() or {}).get('released_count'), 0)

        self.backdate_post(post_id, minutes_ago=16)

        too_close = client.post('/api/posts/pending-safety/release', json={'lat': 25.6870, 'lng': -100.3161})
        self.assertEqual(too_close.status_code, 200)
        self.assertEqual((too_close.get_json() or {}).get('released_count'), 0)

        far_enough = client.post('/api/posts/pending-safety/release', json={'lat': 25.6889, 'lng': -100.3161})
        self.assertEqual(far_enough.status_code, 200)
        far_payload = far_enough.get_json() or {}
        self.assertEqual(far_payload.get('released_count'), 1)
        self.assertEqual((far_payload.get('released_posts') or [{}])[0].get('reason'), 'distance')

        feed_post = self.fetch_feed_post(self.client_for(), post_id)
        self.assertIsNotNone(feed_post)
        assert feed_post is not None
        self.assertEqual(feed_post['location_visibility'], 'exact')
        self.assertEqual(feed_post['location_name'], 'Av. Morelos y Escobedo')

    def test_upload_blocks_capture_when_motion_is_not_walking(self):
        author_id = self.create_user('autora_movimiento')
        client = self.client_for(author_id)

        response = client.post(
            '/upload',
            data={
                'caption': 'Reporte desde carro',
                'location_visibility': 'exact',
                'show_public': 'true',
                'allow_likes': 'true',
                'allow_comments': 'true',
                'capture_source': 'camera',
                'image': self.image_upload('movimiento.jpg'),
                **self.capture_fields(
                    motion_state='blocked',
                    speed_mps=8.2,
                    location_name='Av. Constitución',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(Post.query.count(), 0)

    def test_pending_post_falls_back_after_sixty_minutes(self):
        author_id = self.create_user('autora_fallback')
        post_id = self.create_public_post(
            author_id,
            caption='Reporte pendiente por fallback',
            created_at=app_module.utc_now_naive() - timedelta(minutes=61),
            publish_at=app_module.utc_now_naive() + timedelta(minutes=20),
        )
        client = self.client_for(author_id)

        response = client.post('/api/posts/pending-safety/release', json={})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('released_count'), 1)
        self.assertEqual((payload.get('released_posts') or [{}])[0].get('reason'), 'fallback')
        self.assertIn(post_id, self.post_ids_in_feed(self.client_for()))

    def test_pending_post_overlay_uses_utc_timestamps(self):
        author_id = self.create_user('autora_pending_timer')
        self.create_public_post(
            author_id,
            caption='Reporte pendiente con hora UTC',
            created_at=app_module.utc_now_naive(),
            publish_at=app_module.utc_now_naive() + timedelta(minutes=60),
            show_public=False,
        )

        response = self.client_for(author_id).get('/user/autora_pending_timer/content')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-pending-post', html)
        self.assertRegex(html, r'data-min-ready-at="[^"]+Z"')
        self.assertRegex(html, r'data-fallback-at="[^"]+Z"')
        self.assertNotIn('data-min-ready-at=""', html)
        self.assertNotIn('data-fallback-at=""', html)

    def test_uploaded_images_strip_exif_metadata(self):
        author_id = self.create_user('autora_exif')
        client = self.client_for(author_id)

        response = client.post(
            '/upload',
            data={
                'caption': 'Foto con EXIF',
                'latitude': '25.7000',
                'longitude': '-100.3300',
                'location_name': 'Ubicación de publicación',
                'city': 'Monterrey',
                'country': 'México',
                'location_visibility': 'exact',
                'show_public': 'true',
                'allow_likes': 'true',
                'allow_comments': 'true',
                'capture_source': 'camera',
                'image': self.image_upload('exif.jpg', with_exif=True),
                **self.capture_fields(
                    lat=25.6866,
                    lng=-100.3161,
                    location_name='Centro',
                    city='Monterrey',
                    country='México',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            post = Post.query.order_by(Post.id.desc()).first()
            assert post is not None
            file_path = UPLOAD_DIR / post.image_filename
            self.assertAlmostEqual(float(post.latitude), 25.6866, places=4)
            self.assertAlmostEqual(float(post.longitude), -100.3161, places=4)
            self.assertEqual(post.location_name, 'Centro')

        with Image.open(file_path) as stored:
            exif = stored.getexif()
            self.assertEqual(len(exif), 0)
            self.assertNotIn('exif', stored.info)
            self.assertNotIn('icc_profile', stored.info)

    def test_interactions_and_automatic_abusive_language_strike(self):
        author_id = self.create_user('autora_social')
        viewer_id = self.create_user('lectora_social')
        abusive_id = self.create_user('abusiva_social')
        post_id = self.create_public_post(author_id, caption='Zona con poca iluminación')

        viewer = self.client_for(viewer_id)
        like_response = viewer.post('/like/%d' % post_id, json={})
        self.assertEqual(like_response.status_code, 200)
        self.assertTrue((like_response.get_json() or {}).get('liked'))

        comment_response = viewer.post('/comment/%d' % post_id, data={'content': 'Gracias por avisar'})
        self.assertEqual(comment_response.status_code, 200)
        self.assertTrue((comment_response.get_json() or {}).get('ok'))

        abusive = self.client_for(abusive_id)
        abusive_response = abusive.post('/comment/%d' % post_id, data={'content': 'Eres una puta'})
        self.assertEqual(abusive_response.status_code, 400)
        self.assertIn('lenguaje no permitido', (abusive_response.get_json() or {}).get('error', '').lower())

        abusive_user = self.get_user(abusive_id)
        self.assertEqual(int(abusive_user.abuse_strikes or 0), 1)
        strikes = self.get_strikes(abusive_id)
        self.assertEqual(len(strikes), 1)
        self.assertEqual(strikes[0].source_type, 'comment')

    def test_post_reports_low_and_high_risk_and_admin_actions(self):
        admin_id = self.create_user('admin')
        low_author_id = self.create_user('autora_low_post')
        high_author_id = self.create_user('autora_high_post')
        reporter_id = self.create_user('reportera_post')

        low_post_id = self.create_public_post(low_author_id, caption='Reporte posiblemente inexacto')
        high_post_id = self.create_public_post(high_author_id, caption='Publicación con datos delicados')

        reporter = self.client_for(reporter_id)
        low_report = reporter.post(f'/report_post/{low_post_id}', json={'reason': 'Información falso', 'details': 'No coincide con lo que vi'})
        self.assertEqual(low_report.status_code, 200)
        low_payload = low_report.get_json() or {}
        self.assertFalse(low_payload.get('hidden_immediately'))
        self.assertEqual(low_payload.get('status'), 'pending')
        self.assertIn(low_post_id, self.post_ids_in_feed(self.client_for()))

        high_report = reporter.post(f'/report_post/{high_post_id}', json={'reason': 'Doxxing o datos personales', 'details': 'Incluye datos sensibles'})
        self.assertEqual(high_report.status_code, 200)
        high_payload = high_report.get_json() or {}
        self.assertTrue(high_payload.get('hidden_immediately'))
        self.assertEqual(high_payload.get('status'), 'reviewing')
        self.assertNotIn(high_post_id, self.post_ids_in_feed(self.client_for()))

        admin = self.client_for(admin_id)
        low_report_id = int(low_payload['report_id'])
        strike_response = admin.post(f'/admin/report/{low_report_id}/strike', json={'admin_note': 'Validado por smoke test'})
        self.assertEqual(strike_response.status_code, 200)
        self.assertTrue((strike_response.get_json() or {}).get('strike_applied'))
        self.assertNotIn(low_post_id, self.post_ids_in_feed(self.client_for()))

        low_author = self.get_user(low_author_id)
        self.assertEqual(int(low_author.abuse_strikes or 0), 1)

        high_report_id = int(high_payload['report_id'])
        restore_response = admin.post(f'/admin/report/{high_report_id}/restore', json={'admin_note': 'Restaurado por smoke test'})
        self.assertEqual(restore_response.status_code, 200)
        self.assertIn(high_post_id, self.post_ids_in_feed(self.client_for()))

        with app.app_context():
            high_report_db = db.session.get(Report, high_report_id)
            assert high_report_db is not None
            self.assertEqual(high_report_db.status, 'restored')

    def test_comment_reports_low_and_high_risk(self):
        admin_id = self.create_user('admin')
        post_author_id = self.create_user('autora_comment_post')
        low_comment_author_id = self.create_user('comentadora_low')
        high_comment_author_id = self.create_user('comentadora_high')
        reporter_id = self.create_user('reportera_comment')

        post_id = self.create_public_post(post_author_id, caption='Publicación con comentarios')
        low_comment_id = self.create_comment(low_comment_author_id, post_id, 'No estoy de acuerdo con este reporte')
        high_comment_id = self.create_comment(high_comment_author_id, post_id, 'Te sigo viendo todos los días')

        reporter = self.client_for(reporter_id)
        low_response = reporter.post(
            f'/api/comment/{low_comment_id}/report',
            json={'reason': 'Acoso o insultos', 'details': 'Es molesto, pero no expone datos'},
        )
        self.assertEqual(low_response.status_code, 200)
        low_payload = low_response.get_json() or {}
        self.assertFalse(low_payload.get('hidden_immediately'))
        self.assertEqual(low_payload.get('status'), 'pending')
        self.assertFalse(bool(self.get_comment(low_comment_id).is_hidden))

        admin = self.client_for(admin_id)
        low_report_id = int(low_payload['report_id'])
        low_strike = admin.post(f'/admin/comment_report/{low_report_id}/strike', json={'admin_note': 'Strike de prueba'})
        self.assertEqual(low_strike.status_code, 200)
        self.assertTrue((low_strike.get_json() or {}).get('strike_applied'))
        self.assertTrue(bool(self.get_comment(low_comment_id).is_hidden))
        self.assertEqual(int(self.get_user(low_comment_author_id).abuse_strikes or 0), 1)

        high_response = reporter.post(
            f'/api/comment/{high_comment_id}/report',
            json={'reason': 'Ubicación exacta, rastreo o rutina', 'details': 'Comparte rutina exacta'},
        )
        self.assertEqual(high_response.status_code, 200)
        high_payload = high_response.get_json() or {}
        self.assertTrue(high_payload.get('hidden_immediately'))
        self.assertEqual(high_payload.get('status'), 'reviewing')
        self.assertTrue(bool(self.get_comment(high_comment_id).is_hidden))

        high_report_id = int(high_payload['report_id'])
        restore = admin.post(f'/admin/comment_report/{high_report_id}/restore', json={'admin_note': 'Restauración de prueba'})
        self.assertEqual(restore.status_code, 200)
        self.assertFalse(bool(self.get_comment(high_comment_id).is_hidden))

        with app.app_context():
            high_report_db = db.session.get(CommentReport, high_report_id)
            assert high_report_db is not None
            self.assertEqual(high_report_db.status, 'restored')

    def test_chat_reports_low_and_high_risk(self):
        admin_id = self.create_user('admin')
        low_author_id = self.create_user('chat_low_author')
        high_author_id = self.create_user('chat_high_author')
        reporter_id = self.create_user('chat_reportera')

        low_room_id, low_message_id = self.create_chat_message(low_author_id, room_name='Chat low', content='Mensaje incómodo pero no crítico')
        high_room_id, high_message_id = self.create_chat_message(high_author_id, room_name='Chat high', content='Tengo tu dirección exacta')

        reporter = self.client_for(reporter_id)
        low_response = reporter.post(
            f'/api/chat/message/{low_message_id}/report',
            json={'reason': 'Acoso o insultos', 'details': 'Molesta, pero no es riesgo inmediato'},
        )
        self.assertEqual(low_response.status_code, 200)
        low_payload = low_response.get_json() or {}
        self.assertFalse(low_payload.get('hidden_immediately'))
        self.assertEqual(low_payload.get('status'), 'pending')

        room_messages = reporter.get(f'/api/chat/room/{low_room_id}/messages')
        self.assertEqual(room_messages.status_code, 200)
        low_messages = room_messages.get_json() or {}
        low_message_payload = next(item for item in low_messages['messages'] if int(item['id']) == low_message_id)
        self.assertFalse(low_message_payload['is_deleted'])
        self.assertEqual(low_message_payload['content'], 'Mensaje incómodo pero no crítico')

        admin = self.client_for(admin_id)
        low_report_id = int(low_payload['report_id'])
        low_strike = admin.post(f'/admin/chat_report/{low_report_id}/strike', json={'admin_note': 'Strike de prueba'})
        self.assertEqual(low_strike.status_code, 200)
        self.assertTrue((low_strike.get_json() or {}).get('strike_applied'))

        high_response = reporter.post(
            f'/api/chat/message/{high_message_id}/report',
            json={'reason': 'Doxxing o datos personales', 'details': 'Expone datos directos'},
        )
        self.assertEqual(high_response.status_code, 200)
        high_payload = high_response.get_json() or {}
        self.assertTrue(high_payload.get('hidden_immediately'))
        self.assertEqual(high_payload.get('status'), 'reviewing')

        high_room_messages = reporter.get(f'/api/chat/room/{high_room_id}/messages')
        self.assertEqual(high_room_messages.status_code, 200)
        high_messages = high_room_messages.get_json() or {}
        high_message_payload = next(item for item in high_messages['messages'] if int(item['id']) == high_message_id)
        self.assertTrue(high_message_payload['is_deleted'])
        self.assertEqual(high_message_payload['deleted_reason'], 'reported')

        high_report_id = int(high_payload['report_id'])
        restore = admin.post(f'/admin/chat_report/{high_report_id}/restore', json={'admin_note': 'Restauración de prueba'})
        self.assertEqual(restore.status_code, 200)

        restored_messages = reporter.get(f'/api/chat/room/{high_room_id}/messages')
        restored_payload = restored_messages.get_json() or {}
        restored_message = next(item for item in restored_payload['messages'] if int(item['id']) == high_message_id)
        self.assertFalse(restored_message['is_deleted'])
        self.assertEqual(restored_message['content'], 'Tengo tu dirección exacta')

    def test_role_based_permissions_split_verification_and_safety(self):
        super_admin_id = self.create_user('admin')
        verification_reviewer_id = self.create_user('verificadora', roles=['verification_reviewer'])
        safety_operator_id = self.create_user('operadora_safety', roles=['safety_operator'])
        moderation_reviewer_id = self.create_user('moderadora', roles=['moderation_reviewer'])
        target_user_id = self.create_user('usuaria_objetivo', verified=False)

        with app.app_context():
            req = VerificationRequest(
                user_id=target_user_id,
                phone='+528111111111',
                status='pending',
            )
            db.session.add(req)
            db.session.commit()
            verification_request_id = int(req.id)

            panic = PanicEvent(
                user_id=target_user_id,
                contact_name='Contacto',
                contact_phone='+528122222222',
                latitude=25.6866,
                longitude=-100.3161,
                note='Smoke test panic',
                status='open',
            )
            db.session.add(panic)
            db.session.commit()
            panic_event_id = int(panic.id)

        super_admin_client = self.client_for(super_admin_id)
        assign_roles = super_admin_client.post(
            f'/admin/user/{target_user_id}/roles',
            json={'roles': ['verification_reviewer', 'support_readonly']},
        )
        self.assertEqual(assign_roles.status_code, 200)
        assigned_payload = assign_roles.get_json() or {}
        self.assertTrue(assigned_payload.get('success'))
        self.assertIn('verification_reviewer', assigned_payload.get('roles', []))

        verification_client = self.client_for(verification_reviewer_id)
        verification_workspace = verification_client.get('/staff/verificaciones')
        self.assertEqual(verification_workspace.status_code, 200)
        approve_response = verification_client.post(f'/admin/verify/{verification_request_id}/approve')
        self.assertEqual(approve_response.status_code, 200)
        self.assertTrue((approve_response.get_json() or {}).get('success'))
        self.assertTrue(bool(self.get_user(target_user_id).is_verified))

        delete_user_response = verification_client.post(f'/admin/delete_user/{target_user_id}')
        self.assertEqual(delete_user_response.status_code, 403)
        admin_panel_response = verification_client.get('/admin')
        self.assertEqual(admin_panel_response.status_code, 302)

        safety_client = self.client_for(safety_operator_id)
        safety_workspace = safety_client.get('/staff/safety')
        self.assertEqual(safety_workspace.status_code, 200)
        resolve_response = safety_client.post(f'/admin/panic/{panic_event_id}/resolve')
        self.assertEqual(resolve_response.status_code, 200)
        self.assertTrue((resolve_response.get_json() or {}).get('ok'))

        reject_response = safety_client.post(f'/admin/verify/{verification_request_id}/reject')
        self.assertEqual(reject_response.status_code, 403)

        moderation_client = self.client_for(moderation_reviewer_id)
        moderation_workspace = moderation_client.get('/staff/moderacion')
        self.assertEqual(moderation_workspace.status_code, 200)
        no_safety_access = moderation_client.get('/staff/safety')
        self.assertEqual(no_safety_access.status_code, 302)

    def test_audit_logs_sensitive_access_and_role_changes(self):
        super_admin_id = self.create_user('admin')
        verification_reviewer_id = self.create_user('verificadora_audit', roles=['verification_reviewer'])
        safety_operator_id = self.create_user('operadora_audit', roles=['safety_operator'])
        moderation_reviewer_id = self.create_user('moderadora_audit', roles=['moderation_reviewer'])
        target_user_id = self.create_user('objetivo_audit', verified=False)
        post_id = self.create_public_post(target_user_id, caption='Post para auditoría')

        with app.app_context():
            req = VerificationRequest(
                user_id=target_user_id,
                phone='+528111111111',
                status='pending',
            )
            panic = PanicEvent(
                user_id=target_user_id,
                contact_name='Contacto Audit',
                contact_phone='+528122222222',
                latitude=25.6866,
                longitude=-100.3161,
                note='Evento para auditoría',
                status='open',
            )
            db.session.add(req)
            db.session.add(panic)
            db.session.commit()
            verification_request_id = int(req.id)
            panic_event_id = int(panic.id)

        super_admin_client = self.client_for(super_admin_id)
        verification_client = self.client_for(verification_reviewer_id)
        safety_client = self.client_for(safety_operator_id)
        moderation_client = self.client_for(moderation_reviewer_id)

        self.assertEqual(super_admin_client.get('/admin').status_code, 200)
        self.assertEqual(super_admin_client.get('/admin/content').status_code, 200)
        self.assertEqual(super_admin_client.get(f'/admin/report_details/{post_id}').status_code, 200)

        assign_roles = super_admin_client.post(
            f'/admin/user/{target_user_id}/roles',
            json={'roles': ['support_readonly']},
        )
        self.assertEqual(assign_roles.status_code, 200)
        self.assertTrue((assign_roles.get_json() or {}).get('success'))

        self.assertEqual(verification_client.get('/staff/verificaciones').status_code, 200)
        self.assertEqual(verification_client.post(f'/admin/verify/{verification_request_id}/approve').status_code, 200)
        self.assertEqual(safety_client.get('/staff/safety').status_code, 200)
        self.assertEqual(safety_client.post(f'/admin/panic/{panic_event_id}/resolve').status_code, 200)
        self.assertEqual(moderation_client.get('/staff/moderacion').status_code, 200)

        with app.app_context():
            role_log = AuditLog.query.filter_by(
                event_type='user_roles.update',
                target_user_id=target_user_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(role_log)
            role_details = json.loads(role_log.details or '{}')
            self.assertEqual(role_details.get('previous_roles'), [])
            self.assertEqual(role_details.get('new_roles'), ['support_readonly'])

            admin_view_log = AuditLog.query.filter_by(
                event_type='workspace.view',
                workspace='admin',
                actor_id=super_admin_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(admin_view_log)

            verification_view_log = AuditLog.query.filter_by(
                event_type='workspace.view',
                workspace='verification',
                actor_id=verification_reviewer_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(verification_view_log)

            moderation_view_log = AuditLog.query.filter_by(
                event_type='workspace.view',
                workspace='moderation',
                actor_id=moderation_reviewer_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(moderation_view_log)

            safety_view_log = AuditLog.query.filter_by(
                event_type='workspace.view',
                workspace='safety',
                actor_id=safety_operator_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(safety_view_log)

            report_details_log = AuditLog.query.filter_by(
                event_type='report_details.view',
                actor_id=super_admin_id,
                resource_id=post_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(report_details_log)
            self.assertEqual(report_details_log.target_user_id, target_user_id)

            approve_log = AuditLog.query.filter_by(
                event_type='verification.approve',
                actor_id=verification_reviewer_id,
                resource_id=verification_request_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(approve_log)
            self.assertEqual(approve_log.target_user_id, target_user_id)

            panic_log = AuditLog.query.filter_by(
                event_type='panic.resolve',
                actor_id=safety_operator_id,
                resource_id=panic_event_id,
            ).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(panic_log)
            self.assertEqual(panic_log.target_user_id, target_user_id)

    def test_audit_logs_export_and_purge(self):
        super_admin_id = self.create_user('admin')
        actor_id = self.create_user('audit_actor', roles=['moderation_reviewer'])
        target_user_id = self.create_user('audit_target')
        old_log_id = self.create_audit_log(
            actor_id=actor_id,
            target_user_id=target_user_id,
            event_type='workspace.view',
            workspace='moderation',
            summary='Log antiguo',
            created_at=datetime.now() - timedelta(days=500),
            details=json.dumps({'scope': 'old'}),
        )
        recent_log_id = self.create_audit_log(
            actor_id=actor_id,
            target_user_id=target_user_id,
            event_type='report_details.view',
            workspace='moderation',
            summary='Detalle reciente',
            created_at=datetime.now() - timedelta(days=5),
            details=json.dumps({'scope': 'recent'}),
        )

        admin_client = self.client_for(super_admin_id)
        export_response = admin_client.get('/admin/audit_logs/export?tab=auditoria&audit_workspace=moderation&audit_event=report_details.view&audit_days=30')
        self.assertEqual(export_response.status_code, 200)
        self.assertIn('text/csv', export_response.headers.get('Content-Type', ''))
        csv_body = export_response.get_data(as_text=True)
        self.assertIn('Detalle reciente', csv_body)
        self.assertNotIn('Log antiguo', csv_body)

        purge_response = admin_client.post('/admin/audit_logs/purge')
        self.assertEqual(purge_response.status_code, 200)
        purge_payload = purge_response.get_json() or {}
        self.assertTrue(purge_payload.get('success'))
        self.assertGreaterEqual(int(purge_payload.get('deleted_count') or 0), 1)

        with app.app_context():
            self.assertIsNone(db.session.get(AuditLog, old_log_id))
            self.assertIsNotNone(db.session.get(AuditLog, recent_log_id))
            purge_audit_log = AuditLog.query.filter_by(event_type='audit.purge', actor_id=super_admin_id).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(purge_audit_log)
            export_audit_log = AuditLog.query.filter_by(event_type='audit.export', actor_id=super_admin_id).order_by(AuditLog.id.desc()).first()
            self.assertIsNotNone(export_audit_log)

    def test_strike_escalation_and_interaction_restriction(self):
        admin_id = self.create_user('admin')
        offender_id = self.create_user('reincidente')
        reporter_id = self.create_user('reportera_strikes')
        other_author_id = self.create_user('otra_autora')
        target_post_id = self.create_public_post(other_author_id, caption='Post para probar restricción')

        offender_post_ids = [
            self.create_public_post(offender_id, caption='Publicación 1'),
            self.create_public_post(offender_id, caption='Publicación 2'),
            self.create_public_post(offender_id, caption='Publicación 3'),
        ]

        reporter = self.client_for(reporter_id)
        admin = self.client_for(admin_id)

        for index, post_id in enumerate(offender_post_ids, start=1):
            report_response = reporter.post(
                f'/report_post/{post_id}',
                json={'reason': 'Información falso', 'details': f'Reporte {index}'},
            )
            self.assertEqual(report_response.status_code, 200)
            report_id = int((report_response.get_json() or {})['report_id'])
            strike_response = admin.post(f'/admin/report/{report_id}/strike', json={'admin_note': f'Strike {index}'})
            self.assertEqual(strike_response.status_code, 200)
            if index < 3:
                self.assertTrue((strike_response.get_json() or {}).get('strike_applied'))
                self.backdate_latest_strike(offender_id, days_ago=index)

            offender = self.get_user(offender_id)
            self.assertEqual(int(offender.abuse_strikes or 0), index)

            if index == 2:
                self.assertIsNotNone(offender.muted_until)
                restricted = self.client_for(offender_id)
                blocked_like = restricted.post(
                    f'/like/{target_post_id}',
                    json={},
                    headers={'Accept': 'application/json'},
                )
                self.assertEqual(blocked_like.status_code, 423)
                blocked_payload = blocked_like.get_json() or {}
                self.assertEqual((blocked_payload.get('restriction') or {}).get('type'), 'temporary')
                restricted_page = restricted.get('/account-restricted')
                self.assertEqual(restricted_page.status_code, 200)
                restricted_html = restricted_page.get_data(as_text=True)
                self.assertIn('security_overlays.css', restricted_html)
                self.assertIn('strike-overlay--restricted', restricted_html)

        offender = self.get_user(offender_id)
        self.assertIsNotNone(offender.permanently_banned_at)
        self.assertIsNone(offender.muted_until)
        strikes = self.get_strikes(offender_id)
        self.assertEqual(len(strikes), 3)
        self.assertEqual(strikes[-1].consequence, 'permanent_ban')

    def test_unverified_user_gets_protected_feed_and_blocked_actions(self):
        admin_id = self.create_user('admin')
        author_id = self.create_user('autora_protegida')
        unverified_id = self.create_user('no_verificada', verified=False)
        normal_post_id = self.create_public_post(
            author_id,
            caption='Detalle sensible protegido smoke',
            location_name='Ubicación sensible protegida',
        )
        admin_post_id = self.create_public_post(
            admin_id,
            caption='Anuncio oficial visible smoke',
            location_name='Ubicación oficial visible',
        )
        self.create_comment(author_id, normal_post_id, 'Comentario sensible protegido')
        with app.app_context():
            db.session.add(Like(user_id=author_id, post_id=normal_post_id))
            db.session.commit()
            original_filename = db.session.get(Post, normal_post_id).image_filename

        client = self.client_for(unverified_id)
        page = client.get('/')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('Cuenta no verificada', html)
        self.assertIn('********************', html)
        self.assertIn('Reporte protegido. Verifica tu cuenta para ver los detalles completos.', html)
        self.assertIn('/static/images/protected_post_placeholder.svg', html)
        self.assertIn('Anuncio oficial visible smoke', html)
        self.assertNotIn('Detalle sensible protegido smoke', html)
        self.assertNotIn('Comentario sensible protegido', html)
        self.assertNotIn('autora_protegida', html)
        self.assertNotIn(original_filename, html)

        protected_payload = self.fetch_feed_post(client, normal_post_id)
        self.assertIsNotNone(protected_payload)
        self.assertTrue(protected_payload.get('protected'))
        self.assertEqual(protected_payload.get('username'), '********************')
        self.assertEqual(protected_payload.get('caption'), 'Reporte protegido. Verifica tu cuenta para ver los detalles completos.')
        self.assertEqual(protected_payload.get('image_url'), '/static/images/protected_post_placeholder.svg')
        self.assertIsNone(protected_payload.get('likes_count'))
        self.assertIsNone(protected_payload.get('comments_count'))
        self.assertFalse(protected_payload.get('can_like'))
        self.assertFalse(protected_payload.get('can_comment'))

        admin_payload = self.fetch_feed_post(client, admin_post_id)
        self.assertIsNotNone(admin_payload)
        self.assertFalse(admin_payload.get('protected'))
        self.assertEqual(admin_payload.get('username'), 'admin')
        self.assertEqual(admin_payload.get('caption'), 'Anuncio oficial visible smoke')

        like_response = client.post(f'/like/{normal_post_id}', json={}, headers={'Accept': 'application/json'})
        self.assertEqual(like_response.status_code, 403)
        self.assertIn('verifica', (like_response.get_json() or {}).get('error', '').lower())

        comment_response = client.post(f'/comment/{normal_post_id}', data={'content': 'No debería pasar'})
        self.assertEqual(comment_response.status_code, 403)
        self.assertIn('comentarios', (comment_response.get_json() or {}).get('error', '').lower())

        comments_response = client.get(f'/comments/{normal_post_id}')
        self.assertEqual(comments_response.status_code, 403)
        self.assertEqual((comments_response.get_json() or {}).get('comments'), [])

        upload_response = client.post('/upload', data={}, headers={'Accept': 'application/json'})
        self.assertEqual(upload_response.status_code, 403)
        self.assertIn('publicar', (upload_response.get_json() or {}).get('error', '').lower())

        chat_response = client.get('/chat', follow_redirects=False)
        self.assertEqual(chat_response.status_code, 302)
        self.assertIn('/verify', chat_response.headers.get('Location', ''))

        profile_response = client.get('/user/autora_protegida', follow_redirects=False)
        self.assertEqual(profile_response.status_code, 302)
        self.assertIn('/verify', profile_response.headers.get('Location', ''))

        search_response = client.get('/api/search?q=autora_protegida')
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.get_json() or {}
        self.assertEqual(search_payload.get('users'), [])

    def test_unverified_location_trial_reveals_three_unique_non_admin_posts(self):
        admin_id = self.create_user('admin')
        author_id = self.create_user('autora_ubicaciones')
        viewer_id = self.create_user('no_verificada_ubicaciones', verified=False)
        post_ids = [
            self.create_public_post(
                author_id,
                caption=f'Reporte ubicación {index}',
                latitude=25.60 + index / 100,
                longitude=-100.30 - index / 100,
                location_name=f'Punto sensible {index}',
            )
            for index in range(4)
        ]
        admin_post_id = self.create_public_post(
            admin_id,
            caption='Ubicación admin libre',
            latitude=25.75,
            longitude=-100.20,
            location_name='Punto oficial',
        )

        client = self.client_for(viewer_id)
        first = client.post(f'/api/posts/{post_ids[0]}/reveal-location')
        self.assertEqual(first.status_code, 200)
        self.assertTrue((first.get_json() or {}).get('ok'))
        self.assertEqual((first.get_json() or {}).get('used'), 1)

        repeat = client.post(f'/api/posts/{post_ids[0]}/reveal-location')
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual((repeat.get_json() or {}).get('used'), 1)

        second = client.post(f'/api/posts/{post_ids[1]}/reveal-location')
        third = client.post(f'/api/posts/{post_ids[2]}/reveal-location')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 200)
        self.assertEqual((third.get_json() or {}).get('used'), 3)

        blocked = client.post(f'/api/posts/{post_ids[3]}/reveal-location')
        self.assertEqual(blocked.status_code, 403)
        blocked_payload = blocked.get_json() or {}
        self.assertFalse(blocked_payload.get('ok'))
        self.assertIn('3 vistas de ubicación de prueba', blocked_payload.get('error', ''))

        admin_reveal = client.post(f'/api/posts/{admin_post_id}/reveal-location')
        self.assertEqual(admin_reveal.status_code, 200)
        self.assertEqual((admin_reveal.get_json() or {}).get('used'), 3)

        with app.app_context():
            audit_count = LocationViewAudit.query.filter_by(user_id=viewer_id).count()
            self.assertEqual(audit_count, 3)

    def test_emergency_trigger_prefers_whatsapp_and_falls_back_to_sms(self):
        user_id = self.create_user('usuaria_emergencia')
        self.create_safety_contact(user_id, name='Mamá', phone='+5218111111111', is_primary=True)
        self.create_safety_contact(user_id, name='Amiga', phone='+5218222222222', is_primary=False)
        client = self.client_for(user_id)

        class FakeResponse:
            def __init__(self, status=201):
                self.status = status

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        def fake_urlopen(request_obj, timeout=15):  # noqa: ARG001
            payload = parse_qs((request_obj.data or b'').decode('utf-8'))
            to_value = (payload.get('To') or [''])[0]
            if to_value == 'whatsapp:+5218111111111':
                return FakeResponse(201)
            if to_value == 'whatsapp:+5218222222222':
                raise URLError('whatsapp disabled for this contact')
            if to_value == '+5218222222222':
                return FakeResponse(201)
            raise URLError(f'unexpected destination: {to_value}')

        twilio_env = {
            'TWILIO_ACCOUNT_SID': 'AC_test',
            'TWILIO_AUTH_TOKEN': 'token_test',
            'TWILIO_FROM_NUMBER': '+15005550006',
            'TWILIO_WHATSAPP_FROM_NUMBER': '+14155238886',
            'EMERGENCY_NUMBER': '911',
        }

        with mock.patch.dict(os.environ, twilio_env, clear=False):
            with mock.patch.object(app_module, 'urlopen', side_effect=fake_urlopen):
                response = client.post('/api/safety/emergency/trigger', json={'lat': 25.6866, 'lng': -100.3161})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload.get('contacts_total'), 2)
        self.assertEqual(payload.get('contacts_notified'), 2)
        self.assertEqual(payload.get('contacts_notified_whatsapp'), 1)
        self.assertEqual(payload.get('contacts_notified_sms'), 1)
        self.assertTrue(payload.get('whatsapp_auto_enabled'))
        self.assertTrue(payload.get('sms_auto_enabled'))
        self.assertIn('maps.google.com', payload.get('maps_url', ''))

        with app.app_context():
            events = PanicEvent.query.filter_by(user_id=user_id).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].contact_name, 'Mamá')
            self.assertEqual(events[0].status, 'open')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(VioletaSmokeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
