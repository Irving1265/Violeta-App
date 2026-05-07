#!/usr/bin/env python3
from __future__ import annotations

import io
import importlib
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
    def tearDownClass(cls):
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
                created_at=created_at or datetime.now() - timedelta(minutes=30),
                publish_at=publish_at or datetime.now() - timedelta(minutes=1),
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
            post.created_at = datetime.now() - timedelta(minutes=minutes_ago)
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

        feed_post = self.fetch_feed_post(client, post_id)
        self.assertIsNotNone(feed_post)
        assert feed_post is not None
        self.assertEqual(feed_post['categories'], ['Banquetas en mal estado', 'Terrenos baldíos'])
        self.assertTrue(feed_post['image_url'].startswith('/uploads/optimized/720/'))

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
            self.assertGreater(post.publish_at, datetime.now())

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
            created_at=datetime.now() - timedelta(minutes=61),
            publish_at=datetime.now() + timedelta(minutes=20),
        )
        client = self.client_for(author_id)

        response = client.post('/api/posts/pending-safety/release', json={})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('released_count'), 1)
        self.assertEqual((payload.get('released_posts') or [{}])[0].get('reason'), 'fallback')
        self.assertIn(post_id, self.post_ids_in_feed(self.client_for()))

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
                otp_code=None,
                otp_expires_at=None,
                video_filename=None,
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
                otp_code=None,
                otp_expires_at=None,
                video_filename=None,
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

        offender = self.get_user(offender_id)
        self.assertIsNotNone(offender.permanently_banned_at)
        self.assertIsNone(offender.muted_until)
        strikes = self.get_strikes(offender_id)
        self.assertEqual(len(strikes), 3)
        self.assertEqual(strikes[-1].consequence, 'permanent_ban')

    def test_unverified_user_cannot_interact(self):
        author_id = self.create_user('autora_verificada')
        unverified_id = self.create_user('no_verificada', verified=False)
        post_id = self.create_public_post(author_id, caption='Post para gate de verificación')

        client = self.client_for(unverified_id)
        response = client.post(f'/like/{post_id}', json={}, headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 403)
        self.assertIn('verificar', (response.get_json() or {}).get('error', '').lower())

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

            def __exit__(self, exc_type, exc, tb):
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
