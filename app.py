import os
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    send_from_directory,
    make_response,
    abort,
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    current_user,
    login_required,
)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from models import db, User, UserBlock, SafetyContact, PanicEvent, SafetyCheckin, CheckinRoutePoint, Post, Comment, Like, Share, Tag, PostMeta, ChatRoom, ChatParticipant, ChatMessage, Report, VerificationRequest, post_tag
from sqlalchemy import or_, and_, text, func
from config import Config
from forms import LoginForm, RegisterForm, PostForm, CommentForm, ShareForm
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict, deque
import json
import csv
import glob
import smtplib
import base64
import hashlib
import re
from email.message import EmailMessage
import secrets
import threading
from flask_mail import Mail, Message
from math import radians, cos, sin, asin, sqrt
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.middleware.proxy_fix import ProxyFix

VERIFY_REQUIRED_MSG = 'Para poder ver el contenido tenemos que verificar tu identidad'
PASSWORD_RESET_TOKEN_TTL_SECONDS = 15 * 60
TOKEN_STATE_OK = 0
TOKEN_STATE_INVALID = 1
TOKEN_STATE_EXPIRED = 2

# Best-effort in-memory throttling for abuse-prone endpoints.
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT_LOCK = threading.Lock()


def utc_now_naive() -> datetime:
    """Return UTC now as naive datetime to preserve current DB semantics."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_request_ip() -> str:
    forwarded_for = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    real_ip = (request.headers.get('X-Real-IP') or '').strip()
    remote = (request.remote_addr or '').strip()
    return forwarded_for or real_ip or remote or 'unknown'

def is_rate_limited(bucket: str, limit: int, window_seconds: int) -> bool:
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - float(window_seconds)
    with _RATE_LIMIT_LOCK:
        q = _RATE_LIMIT_BUCKETS[bucket]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now_ts)
    return False


def _debug_log_suppressed(context: str, exc: Exception | None = None) -> None:
    """Logs swallowed exceptions only in debug mode, without breaking flow."""
    try:
        global_app = globals().get('app')
        if global_app is not None and getattr(global_app, 'debug', False):
            print(f'DEBUG: {context}: {exc}')
    except Exception:
        return

def is_same_origin_request() -> bool:
    origin = (request.headers.get('Origin') or '').strip()
    referer = (request.headers.get('Referer') or '').strip()
    host_url = (request.host_url or '').rstrip('/')
    if origin:
        return origin.rstrip('/') == host_url
    if referer:
        return referer.startswith(host_url)
    # Some clients may omit both headers; keep backwards compatibility.
    return True


def ensure_chatroom_schema():
    """Add is_approved column to chat_room if missing (SQLite only)."""
    try:
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(chat_room)")).fetchall()]
            if 'is_approved' not in cols:
                conn.execute(text("ALTER TABLE chat_room ADD COLUMN is_approved BOOLEAN DEFAULT 1"))
            if 'image_filename' not in cols:
                conn.execute(text("ALTER TABLE chat_room ADD COLUMN image_filename VARCHAR(255)"))
            if 'description' not in cols:
                conn.execute(text("ALTER TABLE chat_room ADD COLUMN description TEXT"))
            if 'created_by' not in cols:
                conn.execute(text("ALTER TABLE chat_room ADD COLUMN created_by INTEGER"))
            if 'messages_open' not in cols:
                conn.execute(text("ALTER TABLE chat_room ADD COLUMN messages_open BOOLEAN DEFAULT 1"))
            conn.execute(text("UPDATE chat_room SET is_approved = 1 WHERE is_approved IS NULL"))
            conn.execute(text("UPDATE chat_room SET messages_open = 1 WHERE messages_open IS NULL"))

            # Ensure chat_message attachments columns exist
            msg_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(chat_message)")).fetchall()]
            if 'attachment_filename' not in msg_cols:
                conn.execute(text("ALTER TABLE chat_message ADD COLUMN attachment_filename VARCHAR(255)"))
            if 'attachment_name' not in msg_cols:
                conn.execute(text("ALTER TABLE chat_message ADD COLUMN attachment_name VARCHAR(255)"))
            if 'attachment_mime' not in msg_cols:
                conn.execute(text("ALTER TABLE chat_message ADD COLUMN attachment_mime VARCHAR(120)"))
            if 'is_deleted' not in msg_cols:
                conn.execute(text("ALTER TABLE chat_message ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            if 'deleted_at' not in msg_cols:
                conn.execute(text("ALTER TABLE chat_message ADD COLUMN deleted_at DATETIME"))
            if 'deleted_by' not in msg_cols:
                conn.execute(text("ALTER TABLE chat_message ADD COLUMN deleted_by INTEGER"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_chatroom_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
def ensure_post_schema():
    """Add publish_at column to post if missing (SQLite only)."""
    try:
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(post)")).fetchall()]
            if 'publish_at' not in cols:
                conn.execute(text("ALTER TABLE post ADD COLUMN publish_at DATETIME"))
            conn.execute(text("UPDATE post SET publish_at = created_at WHERE publish_at IS NULL"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_post_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
def ensure_postmeta_schema():
    """Ensure interaction controls exist in post_meta (SQLite only)."""
    try:
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(post_meta)")).fetchall()]
            if 'allow_likes' not in cols:
                conn.execute(text("ALTER TABLE post_meta ADD COLUMN allow_likes BOOLEAN DEFAULT 1"))
            if 'allow_comments' not in cols:
                conn.execute(text("ALTER TABLE post_meta ADD COLUMN allow_comments BOOLEAN DEFAULT 1"))
            if 'location_visibility' not in cols:
                conn.execute(text("ALTER TABLE post_meta ADD COLUMN location_visibility VARCHAR(20) DEFAULT 'exact'"))
            conn.execute(text("UPDATE post_meta SET allow_likes = 1 WHERE allow_likes IS NULL"))
            conn.execute(text("UPDATE post_meta SET allow_comments = 1 WHERE allow_comments IS NULL"))
            conn.execute(text("UPDATE post_meta SET location_visibility = 'exact' WHERE location_visibility IS NULL OR location_visibility = ''"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_postmeta_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
def ensure_report_schema():
    """Ensure moderation fields exist in report (SQLite only)."""
    try:
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(report)")).fetchall()]
            if 'status' not in cols:
                conn.execute(text("ALTER TABLE report ADD COLUMN status VARCHAR(20) DEFAULT 'pending'"))
            if 'admin_note' not in cols:
                conn.execute(text("ALTER TABLE report ADD COLUMN admin_note TEXT"))
            if 'resolved_at' not in cols:
                conn.execute(text("ALTER TABLE report ADD COLUMN resolved_at DATETIME"))
            if 'resolved_by' not in cols:
                conn.execute(text("ALTER TABLE report ADD COLUMN resolved_by INTEGER"))
            conn.execute(text("UPDATE report SET status = 'pending' WHERE status IS NULL OR status = ''"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_report_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
def ensure_user_schema():
    """Add is_verified column to user if missing (SQLite only)."""
    try:
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(user)")).fetchall()]
            if 'is_verified' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN is_verified BOOLEAN DEFAULT 1"))
            if 'abuse_strikes' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN abuse_strikes INTEGER DEFAULT 0"))
            if 'muted_until' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN muted_until DATETIME"))
            if 'last_abuse_at' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN last_abuse_at DATETIME"))
            conn.execute(text("UPDATE user SET is_verified = 1 WHERE is_verified IS NULL"))
            conn.execute(text("UPDATE user SET abuse_strikes = 0 WHERE abuse_strikes IS NULL"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_user_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
def ensure_userblock_schema():
    """Ensure user_block table exists and has expected columns (SQLite only)."""
    try:
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return
        with engine.connect() as conn:
            tables = [row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
            if 'user_block' not in tables:
                conn.execute(text(
                    """
                    CREATE TABLE user_block (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        blocker_id INTEGER NOT NULL,
                        blocked_id INTEGER NOT NULL,
                        is_muted BOOLEAN DEFAULT 0,
                        created_at DATETIME,
                        CONSTRAINT unique_user_block_pair UNIQUE (blocker_id, blocked_id)
                    )
                    """
                ))
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(user_block)"))]
            if 'is_muted' not in cols:
                conn.execute(text("ALTER TABLE user_block ADD COLUMN is_muted BOOLEAN DEFAULT 0"))
            conn.execute(text("UPDATE user_block SET is_muted = 0 WHERE is_muted IS NULL"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_userblock_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
def ensure_safety_schema():
    """Ensure safety_contact, panic_event, safety_checkin and checkin_route_point tables exist (SQLite only)."""
    try:
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return
        # Use a transaction so ALTER/CREATE statements persist reliably.
        with engine.begin() as conn:
            tables = [row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]

            if 'safety_contact' not in tables:
                conn.execute(text(
                    """
                    CREATE TABLE safety_contact (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        name VARCHAR(120) NOT NULL,
                        phone VARCHAR(24) NOT NULL,
                        relationship VARCHAR(80),
                        is_primary BOOLEAN DEFAULT 1,
                        created_at DATETIME
                    )
                    """
                ))

            if 'panic_event' not in tables:
                conn.execute(text(
                    """
                    CREATE TABLE panic_event (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        contact_name VARCHAR(120),
                        contact_phone VARCHAR(24),
                        latitude FLOAT,
                        longitude FLOAT,
                        note VARCHAR(255),
                        status VARCHAR(20) DEFAULT 'open',
                        created_at DATETIME,
                        resolved_at DATETIME,
                        resolved_by INTEGER
                    )
                    """
                ))
            else:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(panic_event)"))]
                if 'resolved_at' not in cols:
                    conn.execute(text("ALTER TABLE panic_event ADD COLUMN resolved_at DATETIME"))
                if 'resolved_by' not in cols:
                    conn.execute(text("ALTER TABLE panic_event ADD COLUMN resolved_by INTEGER"))
                conn.execute(text("UPDATE panic_event SET status = 'open' WHERE status IS NULL OR status = ''"))

            if 'safety_checkin' not in tables:
                conn.execute(text(
                    """
                    CREATE TABLE safety_checkin (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        title VARCHAR(180),
                        contact_name VARCHAR(120),
                        contact_phone VARCHAR(24),
                        destination VARCHAR(180),
                        note VARCHAR(255),
                        eta_minutes INTEGER DEFAULT 30,
                        latitude FLOAT,
                        longitude FLOAT,
                        started_at DATETIME,
                        expires_at DATETIME NOT NULL,
                        status VARCHAR(20) DEFAULT 'active',
                        arrived_at DATETIME,
                        cancelled_at DATETIME,
                        triggered_panic_id INTEGER
                    )
                    """
                ))
            else:
                checkin_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(safety_checkin)"))]
                if 'title' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN title VARCHAR(180)"))
                if 'contact_name' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN contact_name VARCHAR(120)"))
                if 'contact_phone' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN contact_phone VARCHAR(24)"))
                if 'destination' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN destination VARCHAR(180)"))
                if 'note' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN note VARCHAR(255)"))
                if 'eta_minutes' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN eta_minutes INTEGER DEFAULT 30"))
                if 'latitude' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN latitude FLOAT"))
                if 'longitude' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN longitude FLOAT"))
                if 'started_at' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN started_at DATETIME"))
                if 'arrived_at' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN arrived_at DATETIME"))
                if 'cancelled_at' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN cancelled_at DATETIME"))
                if 'triggered_panic_id' not in checkin_cols:
                    conn.execute(text("ALTER TABLE safety_checkin ADD COLUMN triggered_panic_id INTEGER"))
                conn.execute(text("UPDATE safety_checkin SET status = 'active' WHERE status IS NULL OR status = ''"))

            # Ruta del trayecto (puntos GPS asociados a un check-in)
            if 'checkin_route_point' not in tables:
                conn.execute(text(
                    """
                    CREATE TABLE checkin_route_point (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        checkin_id INTEGER NOT NULL,
                        recorded_at DATETIME,
                        latitude FLOAT NOT NULL,
                        longitude FLOAT NOT NULL,
                        speed_kmh FLOAT,
                        accuracy_m FLOAT,
                        created_at DATETIME,
                        FOREIGN KEY(checkin_id) REFERENCES safety_checkin(id)
                    )
                    """
                ))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_checkin_route_point_checkin_id ON checkin_route_point(checkin_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_checkin_route_point_recorded_at ON checkin_route_point(recorded_at)"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_safety_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
def is_user_verified(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return True
    if getattr(user, 'username', '') == 'admin':
        return True
    return bool(getattr(user, 'is_verified', False))


ABUSIVE_WORDS = {
    'puta', 'puta madre', 'pendeja', 'pendejo', 'idiota', 'imbecil', 'zorra',
    'cabrona', 'estupida', 'estupido', 'chingada', 'chingado', 'mierda',
}


def contains_abusive_language(content: str) -> bool:
    text = (content or '').strip().lower()
    if not text:
        return False
    collapsed = ' '.join(text.replace('\n', ' ').split())
    for bad in ABUSIVE_WORDS:
        if bad in collapsed:
            return True
    return False


def is_user_temp_muted(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'username', '') == 'admin':
        return False
    until = getattr(user, 'muted_until', None)
    if not until:
        return False
    return until > datetime.now()


def remaining_mute_seconds(user) -> int:
    if not user or not getattr(user, 'is_authenticated', False):
        return 0
    until = getattr(user, 'muted_until', None)
    if not until:
        return 0
    delta = int((until - datetime.now()).total_seconds())
    return max(0, delta)


def apply_abuse_strike(user, reason: str = 'abusive_language'):
    if not user or getattr(user, 'username', '') == 'admin':
        return

    now = datetime.now()
    strikes = int(getattr(user, 'abuse_strikes', 0) or 0) + 1
    user.abuse_strikes = strikes
    user.last_abuse_at = now

    # Escalación progresiva: 10m, 30m, 2h, 12h, 24h
    if strikes == 1:
        cooldown = timedelta(minutes=10)
    elif strikes == 2:
        cooldown = timedelta(minutes=30)
    elif strikes == 3:
        cooldown = timedelta(hours=2)
    elif strikes == 4:
        cooldown = timedelta(hours=12)
    else:
        cooldown = timedelta(hours=24)

    user.muted_until = now + cooldown
    db.session.add(user)


def temp_mute_error_payload(prefix: str = 'Tienes una restricción temporal de interacción.'):
    secs = remaining_mute_seconds(current_user)
    if secs <= 0:
        return {'error': prefix}
    return {'error': f"{prefix} Intenta de nuevo en {secs} segundos."}


def normalize_phone_simple(raw: str | None) -> str:
    txt = (raw or '').strip()
    if not txt:
        return ''
    digits = ''.join(ch for ch in txt if ch.isdigit())
    if len(digits) == 10:
        return f'+52{digits}'
    if len(digits) == 12 and digits.startswith('52'):
        return f'+{digits}'
    if txt.startswith('+') and len(digits) >= 10:
        return '+' + digits
    return ''


def process_overdue_checkins(user_id: int | None = None) -> int:
    """Marca check-ins vencidos y crea alerta de pánico automática."""
    now = datetime.now()
    query = SafetyCheckin.query.filter(
        SafetyCheckin.status == 'active',
        SafetyCheckin.expires_at <= now,
    )
    if user_id:
        query = query.filter(SafetyCheckin.user_id == user_id)

    overdue = query.all()
    if not overdue:
        return 0

    created = 0
    for checkin in overdue:
        checkin.status = 'expired'
        if checkin.triggered_panic_id:
            db.session.add(checkin)
            continue

        panic_note = 'Check-in vencido automáticamente.'
        if checkin.note:
            panic_note = f"{panic_note} Nota: {checkin.note[:180]}"

        event = PanicEvent(
            user_id=checkin.user_id,
            contact_name=checkin.contact_name,
            contact_phone=checkin.contact_phone,
            latitude=checkin.latitude,
            longitude=checkin.longitude,
            note=panic_note,
            status='open',
        )
        db.session.add(event)
        db.session.flush()
        checkin.triggered_panic_id = event.id
        db.session.add(checkin)
        created += 1

    db.session.commit()
    return created


def _meta_allows_interaction(post, interaction: str) -> bool:
    meta = getattr(post, 'meta', None)
    if not meta:
        return True
    if interaction == 'like':
        value = getattr(meta, 'allow_likes', True)
    else:
        value = getattr(meta, 'allow_comments', True)
    if value is None:
        return True
    return bool(value)


def can_user_interact_post(post, user, interaction: str) -> bool:
    if _meta_allows_interaction(post, interaction):
        return True
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'username', '') == 'admin':
        return True
    return getattr(post, 'user_id', None) == getattr(user, 'id', None)


def normalize_location_visibility(value: str | None, is_admin_user: bool) -> str:
    val = (value or '').strip().lower()
    allowed = {'exact', 'approx', 'hidden'}
    if val not in allowed:
        return 'exact' if is_admin_user else 'approx'
    if not is_admin_user and val == 'exact':
        return 'approx'
    return val


def blocked_user_ids_for(user) -> set[int]:
    if not user or not getattr(user, 'is_authenticated', False):
        return set()
    uid = getattr(user, 'id', None)
    if uid is None:
        return set()
    rows = UserBlock.query.filter(
        (UserBlock.blocker_id == uid) | (UserBlock.blocked_id == uid)
    ).all()
    ids: set[int] = set()
    for row in rows:
        if row.blocker_id == uid:
            ids.add(row.blocked_id)
        if row.blocked_id == uid:
            ids.add(row.blocker_id)
    return ids


def is_user_blocked_between(user_a_id: int | None, user_b_id: int | None) -> bool:
    if not user_a_id or not user_b_id or user_a_id == user_b_id:
        return False
    exists = UserBlock.query.filter(
        ((UserBlock.blocker_id == user_a_id) & (UserBlock.blocked_id == user_b_id)) |
        ((UserBlock.blocker_id == user_b_id) & (UserBlock.blocked_id == user_a_id))
    ).first()
    return exists is not None


def public_location_for_post(post, viewer=None):
    lat = getattr(post, 'latitude', None)
    lng = getattr(post, 'longitude', None)
    name = (getattr(post, 'location_name', None) or '').strip()
    city = (getattr(post, 'city', None) or '').strip()
    country = (getattr(post, 'country', None) or '').strip()

    is_owner_or_admin = False
    if viewer and getattr(viewer, 'is_authenticated', False):
        if getattr(viewer, 'username', '') == 'admin' or getattr(viewer, 'id', None) == getattr(post, 'user_id', None):
            is_owner_or_admin = True

    meta = getattr(post, 'meta', None)
    mode = (getattr(meta, 'location_visibility', 'exact') or 'exact').lower() if meta else 'exact'
    if mode not in {'exact', 'approx', 'hidden'}:
        mode = 'exact'

    if is_owner_or_admin:
        return {
            'lat': lat,
            'lng': lng,
            'name': name,
            'city': city,
            'country': country,
            'visibility': mode,
        }

    if mode == 'hidden':
        return {
            'lat': None,
            'lng': None,
            'name': 'Ubicación oculta por seguridad',
            'city': '',
            'country': '',
            'visibility': mode,
        }

    if mode == 'approx':
        approx_lat = round(float(lat), 3) if lat is not None else None
        approx_lng = round(float(lng), 3) if lng is not None else None
        approx_name = name
        if approx_name and 'aprox' not in approx_name.lower():
            approx_name = f"{approx_name} (aprox.)"
        return {
            'lat': approx_lat,
            'lng': approx_lng,
            'name': approx_name,
            'city': city,
            'country': country,
            'visibility': mode,
        }

    return {
        'lat': lat,
        'lng': lng,
        'name': name,
        'city': city,
        'country': country,
        'visibility': mode,
    }


def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    app.config.from_object(Config)

    if not os.environ.get('SECRET_KEY'):
        app.logger.warning('SECRET_KEY no está definido en entorno. Se usa una clave efímera para esta sesión.')

    # FORCE UPDATE MAX_CONTENT_LENGTH to 32MB
    app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

    # --- Extensiones ---
    db.init_app(app)
    
    csrf = CSRFProtect()
    csrf.init_app(app)

    # Initialize SocketIO for real-time chat (same-origin by default).
    socketio_cors_allowed_origins = app.config.get('SOCKETIO_CORS_ALLOWED_ORIGINS')
    socketio = SocketIO(app, cors_allowed_origins=socketio_cors_allowed_origins)

    login_manager = LoginManager()
    login_manager.login_view = 'login'  # type: ignore
    login_manager.init_app(app)

    @app.context_processor
    def inject_user_verification():
        return {'user_is_verified': is_user_verified(current_user)}

    @app.context_processor
    def inject_user_safety_state():
        return {
            'user_is_temp_muted': is_user_temp_muted(current_user),
            'user_mute_remaining_seconds': remaining_mute_seconds(current_user),
        }

    @login_manager.user_loader
    def load_user(user_id):
        # Compatible con SQLAlchemy 2.x (Query.get es legacy)
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # --- Utils ---
    def allowed_file(filename: str) -> bool:
        """Valida extensión de archivo con valores por defecto si no hay config."""
        if not filename or '.' not in filename:
            return False
        ext = filename.rsplit('.', 1)[1].lower()
        allowed = app.config.get(
            'ALLOWED_EXTENSIONS',
            {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
        )
        return ext in allowed

    def allowed_chat_attachment(filename: str) -> bool:
        if not filename or '.' not in filename:
            return False
        ext = filename.rsplit('.', 1)[1].lower()
        return ext in {'png', 'jpg', 'jpeg', 'pdf'}

    def ensure_upload_folder() -> str:
        folder = app.config.get('UPLOAD_FOLDER')
        if not folder:
            # Valor por defecto si no viene en la Config
            folder = os.path.join(os.path.dirname(__file__), 'uploads')
            app.config['UPLOAD_FOLDER'] = folder
        os.makedirs(folder, exist_ok=True)
        return folder

    def ensure_verification_folder() -> str:
        base = ensure_upload_folder()
        folder = os.path.join(base, 'verify')
        os.makedirs(folder, exist_ok=True)
        return folder

    _face_blur_runtime_cache = {'ready': False, 'dnn': None, 'haar': [], 'hog': None}
    _face_blur_fast_mode = str(os.environ.get('FACE_BLUR_FAST_MODE', '1')).strip().lower() in {'1', 'true', 'yes', 'on'}

    def ensure_ml_models_folder() -> str:
        folder = os.path.join(app.instance_path, 'ml_models')
        os.makedirs(folder, exist_ok=True)
        return folder

    def _download_to_path(url: str, dst_path: str, timeout_sec: int = 12) -> bool:
        try:
            req = Request(url, headers={'User-Agent': 'Violeta/1.0'})
            with urlopen(req, timeout=timeout_sec) as resp:  # nosec B310
                content = resp.read()
            if not content:
                return False
            tmp_path = f'{dst_path}.tmp'
            with open(tmp_path, 'wb') as f:
                f.write(content)
            os.replace(tmp_path, dst_path)
            return True
        except Exception as e:
            if app.debug:
                print('DEBUG: model download failed:', url, e)
            return False

    def _is_valid_model_file(path: str, min_bytes: int = 1) -> bool:
        if not os.path.exists(path):
            return False
        if os.path.getsize(path) < min_bytes:
            return False
        try:
            with open(path, 'rb') as f:
                head = f.read(512)
            lower = head.lower()
            # Reject Git LFS pointer files and HTML error pages.
            if b'git-lfs.github.com/spec/v1' in lower:
                return False
            if lower.startswith(b'<!doctype html') or lower.startswith(b'<html'):
                return False
        except Exception:
            return False
        return True

    def ensure_dnn_face_model_paths() -> tuple[str, str] | None:
        models_dir = ensure_ml_models_folder()
        proto_path = os.path.join(models_dir, 'opencv_face_deploy.prototxt')
        model_path = os.path.join(models_dir, 'opencv_face_res10_fp16.caffemodel')

        if not _is_valid_model_file(proto_path, min_bytes=1200):
            proto_urls = [
                'https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt',
                'https://github.com/opencv/opencv/raw/master/samples/dnn/face_detector/deploy.prototxt',
            ]
            for url in proto_urls:
                if _download_to_path(url, proto_path):
                    break

        if not _is_valid_model_file(model_path, min_bytes=500000):
            model_urls = [
                'https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20180205_fp16/res10_300x300_ssd_iter_140000_fp16.caffemodel',
                'https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20180205_fp16/res10_300x300_ssd_iter_140000_fp16.caffemodel',
            ]
            for url in model_urls:
                if _download_to_path(url, model_path):
                    break

        if _is_valid_model_file(proto_path, min_bytes=1200) and _is_valid_model_file(model_path, min_bytes=500000):
            return (proto_path, model_path)
        return None

    def get_face_blur_runtime():
        """Lazy-load face detectors once per process."""
        if _face_blur_runtime_cache.get('ready'):
            return _face_blur_runtime_cache

        runtime = {'ready': True, 'dnn': None, 'haar': [], 'hog': None}
        try:
            import cv2

            dnn_paths = ensure_dnn_face_model_paths()
            if dnn_paths:
                proto_path, model_path = dnn_paths
                try:
                    runtime['dnn'] = cv2.dnn.readNetFromCaffe(proto_path, model_path)
                except Exception as e:
                    if app.debug:
                        print('DEBUG: DNN face model init failed:', e)

            # HOG people detector is expensive; keep it off in fast mode.
            if not _face_blur_fast_mode:
                try:
                    hog = cv2.HOGDescriptor()
                    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                    runtime['hog'] = hog
                except Exception as e:
                    if app.debug:
                        print('DEBUG: HOG people detector init failed:', e)

            cascade_dir = getattr(cv2.data, 'haarcascades', '')
            candidates = [
                ('frontal', os.path.join(cascade_dir, 'haarcascade_frontalface_default.xml')),
                ('frontal', os.path.join(cascade_dir, 'haarcascade_frontalface_alt2.xml')),
                ('profile', os.path.join(cascade_dir, 'haarcascade_profileface.xml')),
            ]
            for kind, path in candidates:
                if not path or not os.path.exists(path):
                    continue
                cascade = cv2.CascadeClassifier(path)
                if not cascade.empty():
                    runtime['haar'].append({'kind': kind, 'cascade': cascade})
        except Exception as e:
            if app.debug:
                print('DEBUG: OpenCV runtime init failed:', e)

        _face_blur_runtime_cache.update(runtime)
        if app.debug:
            print(
                'DEBUG: face blur runtime ready ->',
                'dnn:', bool(runtime.get('dnn')),
                'haar:', len(runtime.get('haar', [])),
                'hog:', bool(runtime.get('hog')),
                'fast_mode:', _face_blur_fast_mode
            )
        return _face_blur_runtime_cache

    def _iou_rect(a, b):
        ax1, ay1, aw, ah = a
        bx1, by1, bw, bh = b
        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = aw * ah
        area_b = bw * bh
        union = max(1, area_a + area_b - inter)
        return inter / union

    def _merge_face_boxes(boxes, iou_threshold=0.33):
        if not boxes:
            return []
        boxes_sorted = sorted(boxes, key=lambda r: r[2] * r[3], reverse=True)
        merged = []
        for candidate in boxes_sorted:
            keep = True
            for existing in merged:
                if _iou_rect(candidate, existing) >= iou_threshold:
                    keep = False
                    break
            if keep:
                merged.append(candidate)
        return merged

    def blur_faces_in_image(image_path: str) -> int:
        """Detect faces and blur only detected face regions."""
        try:
            import cv2
        except Exception:
            return 0

        runtime = get_face_blur_runtime()
        if not runtime.get('dnn') and not runtime.get('haar'):
            return 0

        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img is None:
            return 0

        orig_h, orig_w = img.shape[:2]
        if orig_h <= 0 or orig_w <= 0:
            return 0

        # Detect on a resized copy for better performance on large images.
        detect_max_side = 1120 if _face_blur_fast_mode else 1600
        max_side = max(orig_h, orig_w)
        resize_factor = 1.0
        detect_img = img
        if max_side > detect_max_side:
            resize_factor = detect_max_side / float(max_side)
            new_w = max(1, int(round(orig_w * resize_factor)))
            new_h = max(1, int(round(orig_h * resize_factor)))
            detect_img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        detect_h, detect_w = detect_img.shape[:2]
        raw_boxes = []

        dnn_net = runtime.get('dnn')
        if dnn_net is not None:
            try:
                blob = cv2.dnn.blobFromImage(
                    detect_img,
                    scalefactor=1.0,
                    size=(300, 300),
                    mean=(104.0, 177.0, 123.0),
                    swapRB=False,
                    crop=False
                )
                dnn_net.setInput(blob)
                detections = dnn_net.forward()
                if detections is not None:
                    for i in range(detections.shape[2]):
                        confidence = float(detections[0, 0, i, 2])
                        # Privacy-first: include weak face detections too.
                        if confidence < 0.35:
                            continue
                        x1n = float(detections[0, 0, i, 3])
                        y1n = float(detections[0, 0, i, 4])
                        x2n = float(detections[0, 0, i, 5])
                        y2n = float(detections[0, 0, i, 6])
                        x1 = int(round(x1n * detect_w))
                        y1 = int(round(y1n * detect_h))
                        x2 = int(round(x2n * detect_w))
                        y2 = int(round(y2n * detect_h))
                        w = x2 - x1
                        h = y2 - y1
                        if w <= 0 or h <= 0:
                            continue
                        # Keep plausible face aspect ratio.
                        ratio = w / float(max(1, h))
                        if ratio < 0.45 or ratio > 1.9:
                            continue
                        pad_ratio = 0.08 if confidence >= 0.55 else 0.20
                        px = int(round(w * pad_ratio))
                        py = int(round(h * pad_ratio))
                        raw_boxes.append((x1 - px, y1 - py, w + 2 * px, h + 2 * py))
            except Exception as e:
                if app.debug:
                    print('DEBUG: DNN face detect failed:', e)

        # Run Haar only when DNN found nothing; this keeps upload responsive.
        if runtime.get('haar') and (not raw_boxes):
            gray = cv2.cvtColor(detect_img, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            min_face = max(16, int(min(detect_h, detect_w) * 0.024))
            search_scales = (1.0, 1.15) if _face_blur_fast_mode else (1.0, 1.15, 1.3, 1.45)
            for search_scale in search_scales:
                if search_scale != 1.0:
                    work_gray = cv2.resize(
                        gray,
                        None,
                        fx=search_scale,
                        fy=search_scale,
                        interpolation=cv2.INTER_LINEAR
                    )
                else:
                    work_gray = gray
                sh, sw = work_gray.shape[:2]
                det_min = max(20, int(min_face * search_scale))

                for detector in runtime['haar']:
                    cascade = detector['cascade']
                    kind = detector['kind']
                    try:
                        faces = cascade.detectMultiScale(
                            work_gray,
                            scaleFactor=1.10 if _face_blur_fast_mode else 1.08,
                            minNeighbors=6 if (kind == 'profile' and _face_blur_fast_mode) else (5 if kind == 'profile' else 4),
                            minSize=(det_min, det_min)
                        )
                    except Exception:
                        faces = []

                    local = []
                    for (x, y, w, h) in faces if faces is not None else []:
                        if w <= 0 or h <= 0:
                            continue
                        ratio = w / float(max(1, h))
                        if ratio < 0.45 or ratio > 1.9:
                            continue
                        local.append((int(x), int(y), int(w), int(h)))

                    if kind == 'profile':
                        try:
                            flipped = cv2.flip(work_gray, 1)
                            faces_flip = cascade.detectMultiScale(
                                flipped,
                                scaleFactor=1.10 if _face_blur_fast_mode else 1.08,
                                minNeighbors=6 if _face_blur_fast_mode else 5,
                                minSize=(det_min, det_min)
                            )
                        except Exception:
                            faces_flip = []
                        for (x, y, w, h) in faces_flip if faces_flip is not None else []:
                            if w <= 0 or h <= 0:
                                continue
                            ratio = w / float(max(1, h))
                            if ratio < 0.45 or ratio > 1.9:
                                continue
                            local.append((int(sw - x - w), int(y), int(w), int(h)))

                    for (x, y, w, h) in local:
                        dx = int(round(x / search_scale))
                        dy = int(round(y / search_scale))
                        dw = int(round(w / search_scale))
                        dh = int(round(h / search_scale))
                        raw_boxes.append((dx, dy, dw, dh))

        if resize_factor != 1.0:
            raw_boxes = [
                (
                    int(round(x / resize_factor)),
                    int(round(y / resize_factor)),
                    int(round(w / resize_factor)),
                    int(round(h / resize_factor)),
                )
                for (x, y, w, h) in raw_boxes
            ]

        merged_boxes = _merge_face_boxes(raw_boxes, iou_threshold=0.32)
        if not merged_boxes:
            return 0

        applied = 0
        for (x, y, w, h) in merged_boxes:
            pad_x = int(round(w * 0.12))
            pad_y = int(round(h * 0.18))
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(orig_w, x + w + pad_x)
            y2 = min(orig_h, y + h + pad_y)
            if x2 <= x1 or y2 <= y1:
                continue
            roi = img[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            # Blur strength proportional to face size.
            kernel = int(max(19, round(min(x2 - x1, y2 - y1) * 0.52)))
            if kernel % 2 == 0:
                kernel += 1
            img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (kernel, kernel), 0)
            applied += 1

        if applied > 0:
            try:
                cv2.imwrite(image_path, img)
            except Exception as e:
                if app.debug:
                    print('DEBUG: could not save blurred image:', e)
                return 0
        return applied

    def _mail_delivery_method() -> str:
        configured = (app.config.get('MAIL_DELIVERY_METHOD') or '').strip().lower()
        if configured in {'smtp', 'resend'}:
            return configured
        if (app.config.get('RESEND_API_KEY') or '').strip():
            return 'resend'
        return 'smtp'

    def _send_email_via_smtp(subject: str, recipients: list[str], text_body: str, html_body: str | None = None) -> bool:
        server = app.config.get('MAIL_SERVER')
        port = int(app.config.get('MAIL_PORT') or 587)
        use_tls = bool(app.config.get('MAIL_USE_TLS'))
        username = app.config.get('MAIL_USERNAME')
        password = app.config.get('MAIL_PASSWORD')
        sender = app.config.get('MAIL_DEFAULT_SENDER') or username
        if not server or not sender or not recipients:
            return False

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype='html')

        with smtplib.SMTP(server, port) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
        return True

    def _send_email_via_resend(subject: str, recipients: list[str], text_body: str, html_body: str | None = None) -> bool:
        api_key = (app.config.get('RESEND_API_KEY') or '').strip()
        api_url = (app.config.get('RESEND_API_URL') or 'https://api.resend.com/emails').strip()
        sender = (app.config.get('RESEND_FROM') or app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
        reply_to = (app.config.get('RESEND_REPLY_TO') or '').strip()
        if not api_key or not api_url or not sender or not recipients:
            return False

        payload = {
            'from': sender,
            'to': recipients,
            'subject': subject,
            'text': text_body,
        }
        if html_body:
            payload['html'] = html_body
        if reply_to:
            payload['reply_to'] = reply_to

        body = json.dumps(payload).encode('utf-8')
        req = Request(
            api_url,
            data=body,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        try:
            with urlopen(req, timeout=15) as resp:  # nosec B310
                status = getattr(resp, 'status', None) or resp.getcode()
                if status not in (200, 201, 202):
                    raise RuntimeError(f'Resend respondió con estado {status}')
                return True
        except HTTPError as exc:
            if app.debug:
                detail = ''
                try:
                    detail = exc.read().decode('utf-8', errors='replace')
                except Exception:
                    detail = str(exc)
                print(f'DEBUG: Resend HTTPError: {detail}')
            return False
        except URLError as exc:
            if app.debug:
                print(f'DEBUG: Resend URLError: {exc}')
            return False

    def send_email_message(subject: str, recipients: list[str], text_body: str, html_body: str | None = None) -> bool:
        method = _mail_delivery_method()
        try:
            if method == 'resend':
                return _send_email_via_resend(subject, recipients, text_body, html_body)
            return _send_email_via_smtp(subject, recipients, text_body, html_body)
        except Exception as exc:
            if app.debug:
                print(f'DEBUG: Error enviando correo ({method}): {type(exc).__name__} - {exc}')
            return False

    def send_verification_email(to_email: str, code: str) -> bool:
        subject = 'Tu código de verificación - Violeta'
        text_body = (
            f"Tu código de verificación es: {code}\n\n"
            "Este código expira en 10 minutos.\n\n"
            "Violeta"
        )
        html_body = (
            "<html><body style=\"font-family:Inter,Arial,sans-serif;background:#0f1020;color:#f3f4f6;padding:20px;\">"
            "<div style=\"max-width:560px;margin:0 auto;background:#1b1d35;border:1px solid rgba(167,139,250,.35);"
            "border-radius:16px;padding:24px;\">"
            "<h2 style=\"margin:0 0 10px 0;color:#a78bfa;\">Tu código de verificación</h2>"
            f"<p style=\"margin:0 0 18px 0;\">Tu código de verificación es <strong style=\"font-size:22px;letter-spacing:2px;\">{code}</strong>.</p>"
            "<p style=\"margin:0;color:#c4b5fd;\">Este código expira en 10 minutos.</p>"
            "</div></body></html>"
        )
        return send_email_message(subject, [to_email], text_body, html_body)

    def _password_reset_email_bodies(user: User, reset_link: str) -> tuple[str, str, str]:
        display_name = (getattr(user, 'username', '') or 'usuaria').strip()
        subject = 'Restablece tu contraseña - Violeta'
        text_body = (
            f"Hola {display_name},\n\n"
            "Recibimos una solicitud para restablecer tu contraseña en Violeta.\n\n"
            f"Usa este enlace para crear una nueva contraseña:\n{reset_link}\n\n"
            "Este enlace expira en 15 minutos.\n"
            "Si no solicitaste este cambio, puedes ignorar este correo.\n\n"
            "Equipo Violeta"
        )
        html_body = (
            "<html><body style=\"font-family:Inter,Arial,sans-serif;background:#0f1020;color:#f3f4f6;padding:20px;\">"
            "<div style=\"max-width:560px;margin:0 auto;background:#1b1d35;border:1px solid rgba(167,139,250,.35);"
            "border-radius:16px;padding:24px;\">"
            "<h2 style=\"margin:0 0 10px 0;color:#a78bfa;\">Restablece tu contraseña</h2>"
            f"<p style=\"margin:0 0 14px 0;\">Hola <strong>{display_name}</strong>, recibimos una solicitud para cambiar tu contraseña.</p>"
            f"<p style=\"margin:0 0 18px 0;\"><a href=\"{reset_link}\" "
            "style=\"display:inline-block;background:#7c3aed;color:#fff;text-decoration:none;padding:12px 18px;border-radius:10px;"
            "font-weight:700;\">Crear nueva contraseña</a></p>"
            "<p style=\"margin:0 0 8px 0;color:#c4b5fd;\">Este enlace expira en 15 minutos.</p>"
            "<p style=\"margin:0;color:#9ca3af;\">Si no solicitaste este cambio, ignora este correo.</p>"
            "</div></body></html>"
        )
        return subject, text_body, html_body

    def send_password_reset_email(user: User, reset_link: str) -> bool:
        subject, text_body, html_body = _password_reset_email_bodies(user, reset_link)
        try:
            return send_email_message(subject, [(user.email or '').strip()], text_body, html_body)
        except Exception as e:
            if app.debug:
                print(f'DEBUG: Error enviando correo de recuperación: {type(e).__name__} - {e}')
            return False

    def normalize_phone(raw: str) -> str:
        if not raw:
            return ''
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if digits.startswith('52') and len(digits) > 10:
            digits = digits[-10:]
        if len(digits) == 10:
            return f"+52{digits}"
        return ''

    def generate_liveness_phrase() -> str:
        verbs = ['confirmo', 'protejo', 'valido', 'respaldo', 'cuido', 'reconozco']
        adjectives = ['real', 'segura', 'valiente', 'clara', 'autentica']
        nouns = ['comunidad', 'ciudad', 'espacio', 'camino', 'luz', 'historia', 'voz', 'dia', 'noche', 'puente']
        chooser = secrets.SystemRandom()
        number = secrets.randbelow(90) + 10
        phrase = (
            f"Hoy {chooser.choice(verbs)} mi identidad en Violeta, "
            f"soy {chooser.choice(adjectives)} y mi {chooser.choice(nouns)} "
            f"es {chooser.choice(nouns)} {number}"
        )
        return phrase

    def get_or_create_verification(user):
        req = VerificationRequest.query.filter_by(user_id=user.id).order_by(VerificationRequest.created_at.desc()).first()
        if req and req.status in ('pending', 'approved'):
            return req
        if req and req.status == 'draft':
            req.liveness_phrase = generate_liveness_phrase()
            db.session.commit()
            return req
        # If rejected or none, create new draft
        req = VerificationRequest()
        req.user_id = user.id
        req.status = 'draft'
        req.liveness_phrase = generate_liveness_phrase()
        db.session.add(req)
        db.session.commit()
        return req

    def append_user_export(user):
        try:
            export_dir = os.path.join(os.path.dirname(__file__), 'exports')
            os.makedirs(export_dir, exist_ok=True)
            csv_path = os.path.join(export_dir, 'users_export.csv')
            write_header = (not os.path.exists(csv_path)) or os.path.getsize(csv_path) == 0
            posts_count = 0
            try:
                posts_count = Post.query.filter_by(user_id=user.id).count()
            except Exception:
                posts_count = 0
            with open(csv_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(['username', 'email', 'password_hash', 'posts_count', 'is_verified'])
                writer.writerow([
                    user.username,
                    user.email,
                    user.password_hash,
                    posts_count,
                    bool(getattr(user, 'is_verified', False))
                ])
        except Exception as e:
            if app.debug:
                print('DEBUG: user export failed:', e)

    def parse_float(val):
        try:
            if val is None:
                return None
            s = str(val).strip()
            return float(s) if s != '' else None
        except (ValueError, TypeError):
            return None

    def build_emergency_message(user_label: str, lat=None, lng=None):
        base_msg = (
            f"ALERTA VIOLETA: {user_label} está en posible peligro. "
            f"Por favor acude lo más pronto posible."
        )
        if valid_coords(lat, lng):
            maps_url = f"https://maps.google.com/?q={float(lat):.6f},{float(lng):.6f}"
            return f"{base_msg} Ubicación: {maps_url}", maps_url
        return f"{base_msg} Ubicación no disponible.", ""

    def send_sms_via_twilio(to_phone: str, body: str) -> bool:
        sid = (os.environ.get('TWILIO_ACCOUNT_SID') or '').strip()
        token = (os.environ.get('TWILIO_AUTH_TOKEN') or '').strip()
        from_phone = (os.environ.get('TWILIO_FROM_NUMBER') or '').strip()
        if not sid or not token or not from_phone:
            return False

        try:
            payload = urlencode({
                'To': to_phone,
                'From': from_phone,
                'Body': body,
            }).encode('utf-8')
            req = Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data=payload,
                method='POST'
            )
            auth = base64.b64encode(f"{sid}:{token}".encode('utf-8')).decode('utf-8')
            req.add_header('Authorization', f'Basic {auth}')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urlopen(req, timeout=12) as response:  # nosec B310
                return 200 <= int(getattr(response, 'status', 0)) < 300
        except Exception as e:
            if app.debug:
                print('DEBUG twilio sms error:', e)
            return False

    def valid_coords(lat, lng):
        try:
            if lat is None or lng is None:
                return False
            return -90.0 <= float(lat) <= 90.0 and -180.0 <= float(lng) <= 180.0
        except Exception:
            return False

    def extract_hashtags(text: str):
        """Extrae hashtags de un texto (sin el #), en minúsculas.

        Acepta letras, números y guiones bajos. Devuelve lista única preservando orden.
        """
        try:
            import re
            if not text:
                return []
            candidates = re.findall(r"#([\wáéíóúñÁÉÍÓÚÑ]+)", text)
            seen = set()
            uniq = []
            for c in candidates:
                name = c.strip().lower()
                if name and name not in seen:
                    seen.add(name)
                    uniq.append(name)
            return uniq
        except Exception:
            return []

    def is_public_post(post):
        """Determina si un post debe ser visible al público."""
        try:
            publish_at = getattr(post, 'publish_at', None)
            if publish_at and publish_at > datetime.now():
                return False
            meta = getattr(post, 'meta', None)
            if meta is None:
                return True
            if meta.show_public is None:
                return True
            return bool(meta.show_public)
        except Exception:
            return True

    def public_posts_query(query):
        """Filtra posts visibles (sin reportes o con show_public=True)."""
        now = datetime.now()
        return query.outerjoin(PostMeta, PostMeta.post_id == Post.id).filter(
            or_(
                PostMeta.id.is_(None),
                PostMeta.show_public.is_(True),
                PostMeta.show_public.is_(None),
            ),
            or_(Post.publish_at.is_(None), Post.publish_at <= now)
        )

    # --- Template Filters ---
    @app.template_filter('from_json')
    def from_json_filter(value):
        import json
        if not value:
            return []
        try:
            return json.loads(value)
        except Exception:
            return []

    def safe_field(form, name):
        """Obtiene un campo de forma robusta ante duplicados en el HTML.

        Prioriza `form.<name>.data`. Si está vacío, revisa `request.form.getlist(name)`
        y devuelve el ÚLTIMO valor no vacío (útil cuando hay dos inputs con el mismo
        nombre y el primero viene vacío, p.ej. `hidden_tag()` + inputs personalizados).
        """
        # 1) Intentar via objeto de formulario
        if hasattr(form, name):
            try:
                data = getattr(form, name).data
                if isinstance(data, str):
                    data = data.strip()
                if data not in (None, ''):
                    return data
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        # 2) Revisar lista de valores crudos del request
        try:
            values = request.form.getlist(name)
        except Exception:
            values = []
        # Elegir el último no vacío (el que está más abajo en el DOM)
        for v in reversed(values):
            if v is None:
                continue
            s = v.strip() if isinstance(v, str) else v
            if s != '':
                return s
        return None

    # Cache busting global (útil para evitar contenido viejo del feed)
    @app.after_request
    def add_no_cache_headers(response):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        # Asegurar que geolocalización del navegador no sea limitada por política (por defecto está permitida)
        # Esto explícitamente la habilita para el mismo origen.
        response.headers['Permissions-Policy'] = "geolocation=(self)"
        # Hardening headers
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        return response

    # Hacer disponible csrf_token() en todas las plantillas (fallback explícito)
    @app.context_processor
    def inject_csrf():
        try:
            return dict(csrf_token=generate_csrf)
        except Exception:
            return dict(csrf_token=lambda: '')

    @app.context_processor
    def inject_interaction_helpers():
        return dict(
            can_user_interact_post=can_user_interact_post,
            meta_allows_interaction=_meta_allows_interaction,
            public_location_for_post=public_location_for_post,
        )

    @app.context_processor
    def inject_user_safety_helpers():
        def is_blocked_user(target_user_id):
            if not current_user.is_authenticated:
                return False
            try:
                uid = int(target_user_id)
            except Exception:
                return False
            row = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=uid).first()
            return row is not None

        def is_muted_user(target_user_id):
            if not current_user.is_authenticated:
                return False
            try:
                uid = int(target_user_id)
            except Exception:
                return False
            row = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=uid).first()
            return bool(row.is_muted) if row else False

        return dict(
            is_blocked_user=is_blocked_user,
            is_muted_user=is_muted_user,
        )

    # --- Rutas ---
    @app.route('/')
    def index():
        # Si no está autenticado, mostrar landing con login + mapa
        if not current_user.is_authenticated:
            return redirect(url_for('login'))

        selected_city = (request.args.get('city') or 'all').strip().lower()
        page = request.args.get('page', 1, type=int)
        per_page = app.config.get('FEED_PAGE_SIZE', 10)

        city_bounds = {
            'monterrey': (25.60, 25.75, -100.42, -100.25),
            'san-pedro': (25.62, 25.70, -100.45, -100.35),
            'guadalupe': (25.65, 25.72, -100.28, -100.18),
            'apodaca': (25.73, 25.82, -100.25, -100.12),
            'escobedo': (25.75, 25.85, -100.38, -100.28),
            'santa-catarina': (25.62, 25.72, -100.52, -100.42),
        }

        query = public_posts_query(Post.query).order_by(Post.created_at.desc())
        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        if blocked_ids:
            query = query.filter(~Post.user_id.in_(blocked_ids))

        if selected_city and selected_city != 'all':
            bounds = city_bounds.get(selected_city)
            if bounds:
                lat_min, lat_max, lng_min, lng_max = bounds
                query = query.filter(
                    Post.latitude.isnot(None),
                    Post.longitude.isnot(None),
                    Post.latitude.between(lat_min, lat_max),
                    Post.longitude.between(lng_min, lng_max),
                )
            else:
                query = query.filter(Post.city.ilike(f"%{selected_city}%"))

        # Sidebar: reportes generados por categoría (orden descendente)
        report_counts = []
        report_counts_today = []
        try:
            def extract_categories(cats_raw):
                if not cats_raw:
                    return set()
                try:
                    cats = json.loads(cats_raw)
                except Exception:
                    return set()
                if not isinstance(cats, list):
                    return set()
                # Count each post once per category (avoid duplicates inside the JSON array)
                normalized = set()
                for c in cats:
                    if c is None:
                        continue
                    name = str(c).strip()
                    if not name:
                        continue
                    key = name.casefold()
                    if key in ('baldios', 'baldío', 'baldio', 'baldíos'):
                        name = 'Baldíos'
                    elif key in ('poca iluminacion', 'poca iluminación'):
                        name = 'Poca iluminación'
                    normalized.add(name)
                return normalized

            cat_counts = Counter()
            rows = query.with_entities(Post.categories).all()
            for (cats_raw,) in rows:
                for name in extract_categories(cats_raw):
                    cat_counts[name] += 1

            report_counts = [{'category': k, 'count': v} for k, v in cat_counts.items() if v > 0]
            report_counts.sort(key=lambda x: (-x['count'], x['category'].casefold()))

            # Reportes generados hoy por categoría (mismo widget, pero filtrado a hoy).
            # created_at se guarda con utc_now_naive() (UTC naive), así que convertimos
            # el "hoy" local (zona horaria de la app) a límites UTC naive para filtrar correctamente.
            #
            # Importante: no dependemos del timezone del servidor/OS, ya que puede variar (p. ej. UTC).
            # Usamos una zona horaria fija configurable (por default: America/Monterrey).
            from zoneinfo import ZoneInfo

            tz_name = app.config.get('APP_TIMEZONE') or 'America/Monterrey'
            try:
                app_tz = ZoneInfo(tz_name)
            except Exception:
                # Fallback defensivo si la zona no existe en el runtime.
                app_tz = datetime.now().astimezone().tzinfo or timezone.utc

            now_local = datetime.now(tz=app_tz)
            start_today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            start_tomorrow_local = start_today_local + timedelta(days=1)
            start_today = start_today_local.astimezone(timezone.utc).replace(tzinfo=None)
            start_tomorrow = start_tomorrow_local.astimezone(timezone.utc).replace(tzinfo=None)
            rows_today = query.filter(
                Post.created_at >= start_today,
                Post.created_at < start_tomorrow,
            ).with_entities(Post.categories).all()

            cat_counts_today = Counter()
            for (cats_raw,) in rows_today:
                for name in extract_categories(cats_raw):
                    cat_counts_today[name] += 1

            report_counts_today = [{'category': k, 'count': v} for k, v in cat_counts_today.items() if v > 0]
            report_counts_today.sort(key=lambda x: (-x['count'], x['category'].casefold()))
        except Exception:
            report_counts = []
            report_counts_today = []

        posts = query.paginate(page=page, per_page=per_page, error_out=False)

        if app.debug:
            print(f"DEBUG: Total posts found: {posts.total}")
            print(f"DEBUG: Posts on current page: {len(posts.items)}")
            for i, post in enumerate(posts.items):
                try:
                    print(f"DEBUG: Post {i+1}: {post.id} - {post.caption} - {post.image_filename}")
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
        post_form = PostForm()
        comment_form = CommentForm()
        share_form = ShareForm()

        response = make_response(
            render_template(
                'index.html',
                posts=posts.items,
                pagination=posts,
                post_form=post_form,
                comment_form=comment_form,
                share_form=share_form,
                selected_city=selected_city,
                report_counts=report_counts,
                report_counts_today=report_counts_today,
            )
        )
        return response

    @app.route('/feed')
    def feed():
        page = request.args.get('page', 1, type=int)
        per_page = app.config.get('FEED_PAGE_SIZE', 10)
        posts = public_posts_query(
            Post.query.options(db.joinedload(Post.comments).joinedload(Comment.author))
        ).order_by(Post.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        data = []
        for p in posts.items:
            if blocked_ids and p.user_id in blocked_ids:
                continue
            try:
                image_url = url_for('uploaded_file', filename=p.image_filename) if getattr(p, 'image_filename', None) else ''
                liked_by_me = p.is_liked_by(current_user) if current_user.is_authenticated else False
                allow_likes = _meta_allows_interaction(p, 'like')
                allow_comments = _meta_allows_interaction(p, 'comment')
                loc = public_location_for_post(p, current_user)
                # Parse categories from JSON
                categories = []
                if getattr(p, 'categories', None):
                    try:
                        import json
                        categories = json.loads(p.categories)
                    except Exception:
                        categories = []

                data.append({
                    'id': p.id,
                    'username': getattr(p.author, 'username', 'unknown'),
                    'caption': p.caption,
                    'image_url': image_url,
                    'likes_count': p.get_likes_count(),
                    'comments_count': p.get_comments_count(),
                    'created_at': p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
                    'liked_by_me': liked_by_me,
                    'allow_likes': allow_likes,
                    'allow_comments': allow_comments,
                    'latitude': loc.get('lat'),
                    'longitude': loc.get('lng'),
                    'location_name': loc.get('name'),
                    'city': loc.get('city'),
                    'country': loc.get('country'),
                    'location_visibility': loc.get('visibility'),
                    'tags': [t.name for t in getattr(p, 'tags', [])] if hasattr(p, 'tags') else [],
                    'categories': categories,
                })
            except Exception as e:
                if app.debug:
                    print('DEBUG: error building feed item:', e)
        return jsonify({'posts': data, 'has_next': posts.has_next})

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        form = RegisterForm()
        if form.validate_on_submit():
            normalized_email = (form.email.data or '').strip().lower()
            # Evitar duplicados por usuario o email
            exists = User.query.filter(
                (User.username == form.username.data) | (func.lower(User.email) == normalized_email)
            ).first()
            if exists:
                flash('La usuaria o el correo ya existen', 'danger')
                return redirect(url_for('register'))
            try:
                user = User(username=form.username.data, email=normalized_email)  # type: ignore
                user.set_password(form.password.data)
                user.is_verified = False
                db.session.add(user)
                db.session.commit()
                append_user_export(user)
                flash('Registro exitoso. Inicia sesión.', 'success')
                return redirect(url_for('login'))
            except Exception as e:
                db.session.rollback()
                flash('Hubo un problema creando tu cuenta. Inténtalo más tarde.', 'danger')
                if app.debug:
                    print('DEBUG register error:', e)
        return render_template('register.html', form=form)

    @app.route('/api/check-email', methods=['POST'])
    @csrf.exempt
    def check_email():
        """Check if email already exists in database."""
        if not is_same_origin_request():
            return jsonify({'error': 'Origen inválido'}), 403

        ip = get_request_ip()
        if is_rate_limited(f'check_email:{ip}', limit=60, window_seconds=60):
            return jsonify({'error': 'Demasiadas solicitudes. Intenta de nuevo en un minuto.'}), 429

        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip()

        if not email:
            return jsonify({'exists': False})

        normalized_email = email.lower()
        user = User.query.filter(func.lower(User.email) == normalized_email).first()
        return jsonify({'exists': user is not None})

    @app.route('/api/check-username', methods=['POST'])
    @csrf.exempt
    def check_username():
        """Check if username already exists in database."""
        if not is_same_origin_request():
            return jsonify({'error': 'Origen inválido'}), 403

        ip = get_request_ip()
        if is_rate_limited(f'check_username:{ip}', limit=60, window_seconds=60):
            return jsonify({'error': 'Demasiadas solicitudes. Intenta de nuevo en un minuto.'}), 429

        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()

        if not username:
            return jsonify({'exists': False})

        user = User.query.filter_by(username=username).first()
        return jsonify({'exists': user is not None})


    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        form = LoginForm()
        # Handle login with either username or email
        login_input = request.form.get('login', '').strip()
        password = request.form.get('password', '')

        if login_input and password:
            ip = get_request_ip()
            if is_rate_limited(f'login:{ip}', limit=12, window_seconds=300):
                flash('Demasiados intentos de inicio de sesión. Intenta de nuevo en unos minutos.', 'error')
                return render_template('login.html', form=form), 429

            # Try to find user by username first, then by email
            user = User.query.filter_by(username=login_input).first()
            if not user:
                user = User.query.filter_by(email=login_input).first()

            if user and user.check_password(password):
                # Recordarme opcional (checkbox)
                remember_raw = (request.form.get('remember') or '').lower()
                remember = remember_raw in ('1', 'true', 'on', 'yes')
                # Prevent session fixation by rotating session data at login.
                session.clear()
                login_user(user, remember=remember)
                flash('Sesión iniciada', 'success')
                return redirect(url_for('index'))

            # Generic message to avoid account enumeration.
            flash('Credenciales inválidas', 'error')
        return render_template('login.html', form=form)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Sesión cerrada', 'info')
        return redirect(url_for('login'))

    @app.route('/forgot-password')
    def forgot_password():
        return render_template('forgot_password.html')

    @app.route('/api/forgot-password/request', methods=['POST'])
    @csrf.exempt
    def forgot_password_request():
        if not is_same_origin_request():
            return jsonify({'error': 'Origen inválido'}), 403

        ip = get_request_ip()
        if is_rate_limited(f'forgot_password:{ip}', limit=8, window_seconds=600):
            return jsonify({'error': 'Demasiadas solicitudes. Intenta nuevamente en unos minutos.'}), 429

        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip()
        if not email:
            return jsonify({'error': 'El correo electrónico es requerido.'}), 400
        if not _is_valid_email(email):
            return jsonify({'error': 'Formato de correo inválido.'}), 400

        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if not user:
            return jsonify({'error': 'No encontramos una cuenta con ese correo.'}), 404

        token = build_password_reset_token(user)
        reset_link = url_for('reset_password', token=token, _external=True)
        sent = send_password_reset_email(user, reset_link)
        if not sent:
            return jsonify({'error': 'No pudimos enviar el correo. Revisa la configuración de correo (MAIL_* o RESEND_*).'}), 500

        return jsonify({
            'ok': True,
            'message': 'Te enviamos un enlace para restablecer tu contraseña. Expira en 15 minutos.',
        }), 200

    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    def reset_password(token):
        user, token_state = resolve_password_reset_token(token, PASSWORD_RESET_TOKEN_TTL_SECONDS)
        if token_state == TOKEN_STATE_EXPIRED:
            return render_template('reset_password_expired.html', is_expired=True), 410
        if token_state != TOKEN_STATE_OK or not user:
            return render_template('reset_password_expired.html', is_expired=False), 400

        errors = []
        if request.method == 'POST':
            new_password = (request.form.get('new_password') or '').strip()
            confirm_password = (request.form.get('confirm_password') or '').strip()

            if not new_password or not confirm_password:
                errors.append('Debes completar ambos campos de contraseña.')
            if new_password and len(new_password) < 8:
                errors.append('La contraseña debe tener al menos 8 caracteres.')
            if new_password and not (re.search(r'[A-Za-z]', new_password) and re.search(r'[0-9]', new_password)):
                errors.append('La contraseña debe incluir al menos una letra y un número.')
            if new_password and confirm_password and new_password != confirm_password:
                errors.append('Las contraseñas no coinciden.')

            if not errors:
                try:
                    user.set_password(new_password)
                    db.session.commit()
                    flash('Tu contraseña se actualizó correctamente. Inicia sesión con la nueva contraseña.', 'success')
                    return redirect(url_for('login'))
                except Exception as e:
                    db.session.rollback()
                    if app.debug:
                        print(f'DEBUG reset password error: {e}')
                    errors.append('No pudimos actualizar la contraseña. Inténtalo nuevamente.')

        return render_template(
            'reset_password.html',
            token=token,
            email=(user.email or '').strip(),
            errors=errors,
        )

    # --- OTP Verification Routes ---
    @app.route('/send-otp', methods=['POST'])
    @csrf.exempt
    def send_otp():
        try:
            if not is_same_origin_request():
                return jsonify({'error': 'Origen inválido'}), 403

            ip = get_request_ip()
            if is_rate_limited(f'send_otp:{ip}', limit=5, window_seconds=600):
                return jsonify({'error': 'Demasiadas solicitudes OTP. Intenta de nuevo más tarde.'}), 429

            data = request.get_json(silent=True) or {}
            email = (data.get('email') or '').strip()

            if not email:
                return jsonify({'error': 'Email es requerido'}), 400

            # Generate 6-digit OTP
            otp_code = f"{secrets.randbelow(900000) + 100000}"

            # Store OTP in session (in production use Redis or DB with expiry)
            session['current_otp'] = otp_code
            session['current_email'] = email
            # Simple expiry mechanism: store timestamp
            session['otp_timestamp'] = datetime.now().timestamp()
            session['otp_failures'] = 0

            # Send email
            sent = send_verification_email(email, otp_code)
            if not sent:
                return jsonify({'error': 'No se pudo enviar el correo. Revisa la configuración de correo.'}), 500

            return jsonify({'message': 'Código enviado exitosamente'}), 200
        except Exception as e:
            if app.debug:
                print(f"Error enviando OTP: {e}")
            return jsonify({'error': 'No se pudo enviar el correo'}), 500

    @app.route('/verify-otp', methods=['POST'])
    @csrf.exempt
    def verify_otp():
        try:
            if not is_same_origin_request():
                return jsonify({'error': 'Origen inválido'}), 403

            ip = get_request_ip()
            if is_rate_limited(f'verify_otp:{ip}', limit=15, window_seconds=600):
                return jsonify({'error': 'Demasiados intentos. Intenta de nuevo más tarde.'}), 429

            data = request.get_json(silent=True) or {}
            user_otp = (data.get('otp') or '').strip()
            email = (data.get('email') or '').strip()  # Optional validation

            saved_otp = session.get('current_otp')
            saved_email = session.get('current_email')
            timestamp = session.get('otp_timestamp')
            failures = int(session.get('otp_failures', 0) or 0)

            if not user_otp:
                return jsonify({'error': 'Falta el código OTP'}), 400

            if failures >= 8:
                return jsonify({'error': 'Demasiados intentos fallidos. Solicita un código nuevo.'}), 429

            # Check expiry (10 minutes)
            if not timestamp or datetime.now().timestamp() - timestamp > 600:
                session.pop('current_otp', None)
                session.pop('otp_timestamp', None)
                session.pop('otp_failures', None)
                return jsonify({'error': 'El código ha expirado'}), 400

            if user_otp == saved_otp:
                if email and email != saved_email:
                    return jsonify({'error': 'Email no coincide con el código solicitado'}), 400

                # Success
                # Clear OTP from session
                session.pop('current_otp', None)
                session.pop('otp_timestamp', None)
                session.pop('otp_failures', None)

                return jsonify({'message': 'Verificación exitosa', 'verified': True}), 200

            session['otp_failures'] = failures + 1
            return jsonify({'error': 'Código incorrecto'}), 400
        except Exception as e:
            if app.debug:
                print(f"Error verificando OTP: {e}")
            return jsonify({'error': 'Error en el servidor'}), 500


    @app.route('/upload', methods=['POST'])
    @login_required
    def upload():
        if current_user.is_authenticated and not is_user_verified(current_user):
            flash(VERIFY_REQUIRED_MSG, 'info')
            return redirect(url_for('index'))
        if is_user_temp_muted(current_user):
            secs = remaining_mute_seconds(current_user)
            flash(f'Tu cuenta tiene una restricción temporal por seguridad. Intenta de nuevo en {secs} segundos.', 'warning')
            return redirect(url_for('index'))
        if app.debug:
            print('DEBUG: Upload function called')
        form = PostForm()
        if app.debug:
            try:
                print(f'DEBUG: Form validation: {form.validate_on_submit()}')
                print(f"DEBUG: Image in files: {'image' in request.files}")
                print(f'DEBUG: Form errors: {form.errors}')
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        # Obtener archivo
        file = request.files.get('image')
        if not file or not getattr(file, 'filename', ''):
            flash('Debes seleccionar una imagen.', 'danger')
            return redirect(url_for('index'))

        # Defense-in-depth: normalize and validate filename again.
        filename = (file.filename or '').strip()
        if not filename:
            flash('Debes seleccionar una imagen.', 'danger')
            return redirect(url_for('index'))

        if not allowed_file(filename):
            flash('Archivo inválido. Extensiones permitidas: png, jpg, jpeg, gif, webp, bmp.', 'danger')
            return redirect(url_for('index'))

        # Asegurar carpeta
        upload_folder = ensure_upload_folder()

        # Nombre único + seguro
        original_name = secure_filename(filename)
        _, ext = os.path.splitext(original_name)
        ext = ext.lower()
        unique_name = f"{uuid4().hex}{ext}"
        save_path = os.path.join(upload_folder, unique_name)
        try:
            file.save(save_path)
        except Exception as e:
            if app.debug:
                print('DEBUG: error saving file:', e)
            flash('No se pudo guardar la imagen.', 'danger')
            return redirect(url_for('index'))

        # Conversión de HEIC/HEIF a JPEG para compatibilidad en navegadores
        if ext in {'.heic', '.heif'}:
            try:
                try:
                    from pillow_heif import register_heif_opener
                    register_heif_opener()
                except Exception as _e:
                    if app.debug:
                        print('DEBUG: pillow_heif not available:', _e)
                from PIL import Image
                with Image.open(save_path) as im:
                    rgb = im.convert('RGB')
                    new_name = f"{uuid4().hex}.jpg"
                    new_path = os.path.join(upload_folder, new_name)
                    rgb.save(new_path, format='JPEG', quality=92)
                # Replace saved file/metadata
                try:
                    os.remove(save_path)
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
                unique_name = new_name
                save_path = new_path
                ext = '.jpg'
            except Exception as conv_e:
                if app.debug:
                    print('DEBUG: HEIC conversion failed:', conv_e)
                flash('No se pudo procesar la imagen HEIC. Intenta con JPG/PNG.', 'danger')
                return redirect(url_for('index'))

        # Protección de privacidad: difuminar únicamente rostros detectados.
        faces_blurred = 0
        if ext in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}:
            try:
                blur_t0 = datetime.now()
                faces_blurred = blur_faces_in_image(save_path)
                if app.debug:
                    blur_ms = int((datetime.now() - blur_t0).total_seconds() * 1000)
                    print(f'DEBUG: Faces blurred in post upload: {faces_blurred}')
                    print(f'DEBUG: Face blur elapsed: {blur_ms}ms')
            except Exception as e:
                if app.debug:
                    print('DEBUG: Face blur failed on upload:', e)

        # Campos del formulario (con fallback a request.form)
        caption = safe_field(form, 'caption') or ''
        lat = parse_float(safe_field(form, 'latitude'))
        lng = parse_float(safe_field(form, 'longitude'))
        loc_source = (safe_field(form, 'loc_source') or '').lower()

        # Procesar categorías
        categories_raw = request.form.getlist('categories') or []
        categories = [cat.strip() for cat in categories_raw if cat.strip()]
        categories_json = None
        if categories:
            try:
                import json
                categories_json = json.dumps(categories)
            except Exception:
                categories_json = None

        if app.debug:
            try:
                print('DEBUG: Upload coords -> lat:', lat, 'lng:', lng, 'loc_source:', loc_source)
                print('DEBUG: Categories:', categories)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        # Ya no bloqueamos la publicación por ubicación.
        # Si vienen coordenadas inválidas o faltan, continuamos sin ubicarlas.
        # Esto permite publicar independientemente de si el GPS está activo.
        if not valid_coords(lat, lng):
            lat = None
            lng = None

        location_name = safe_field(form, 'location_name')
        city = safe_field(form, 'city')
        country = safe_field(form, 'country')

        # Programación de publicación
        now = datetime.now()
        publish_at = now
        if current_user.username != 'admin':
            publish_at = now + timedelta(minutes=15)
        else:
            mode = (request.form.get('publish_mode') or 'now').lower()
            if mode == 'delay':
                publish_at = now + timedelta(minutes=15)
            elif mode == 'schedule':
                raw = (request.form.get('publish_at') or '').strip()
                parsed = None
                if raw:
                    try:
                        parsed = datetime.fromisoformat(raw)
                    except Exception:
                        parsed = None
                if parsed and parsed > now:
                    publish_at = parsed
                else:
                    publish_at = now

        # Si faltan etiquetas de lugar, intentar reverse geocoding ligero (mejora UX)
        # Usa Nominatim con timeout corto y User-Agent identificable
        if not location_name:
            try:
                import json as _json
                from urllib.request import Request, urlopen
                from urllib.parse import urlencode
                params = {
                    'format': 'json',
                    'lat': f'{lat:.6f}',
                    'lon': f'{lng:.6f}',
                    'addressdetails': '1',
                }
                url = f"https://nominatim.openstreetmap.org/reverse?{urlencode(params)}"
                req = Request(url, headers={
                    'User-Agent': 'VioletaApp/1.0 (+contact@example.com)'
                })
                with urlopen(req, timeout=4) as resp:  # nosec B310
                    data = _json.loads(resp.read().decode('utf-8'))
                    address = data.get('address', {}) if isinstance(data, dict) else {}
                    # Construir location_name tipo Instagram
                    street = address.get('road') or address.get('pedestrian') or address.get('footway')
                    town = address.get('city') or address.get('town') or address.get('village')
                    state = address.get('state')
                    parts = []
                    if street:
                        parts.append(street)
                    if town:
                        parts.append(town)
                    if state:
                        parts.append(state)
                    built = ', '.join(parts)
                    if built:
                        location_name = built
                    if not city:
                        city = town
                    if not country:
                        country = address.get('country')
            except Exception as _e:
                if app.debug:
                    print('DEBUG: reverse geocoding failed:', _e)

        try:
            post = Post()
            post.caption = caption
            post.image_filename = unique_name
            post.user_id = current_user.id
            post.latitude = lat
            post.longitude = lng
            post.location_name = location_name
            post.city = city
            post.country = country
            post.categories = categories_json
            post.publish_at = publish_at
            db.session.add(post)
            db.session.commit()

            # Guardar meta de interacción/visibilidad
            alt_text = safe_field(form, 'alt_text') or (request.form.get('alt_text') if request.form else None)
            show_public_raw = safe_field(form, 'show_public') or (request.form.get('show_public') if request.form else None)
            location_visibility_raw = request.form.get('location_visibility') if request.form else None
            allow_likes_raw = request.form.get('allow_likes') if request.form else None
            allow_comments_raw = request.form.get('allow_comments') if request.form else None
            try:
                show_public = True
                if isinstance(show_public_raw, str):
                    show_public = show_public_raw.lower() not in ('false', '0', 'no')
                elif isinstance(show_public_raw, bool):
                    show_public = show_public_raw

                allow_likes = True
                if isinstance(allow_likes_raw, str):
                    allow_likes = allow_likes_raw.lower() not in ('false', '0', 'no')

                allow_comments = True
                if isinstance(allow_comments_raw, str):
                    allow_comments = allow_comments_raw.lower() not in ('false', '0', 'no')

                location_visibility = normalize_location_visibility(
                    location_visibility_raw,
                    current_user.username == 'admin'
                )

                meta = PostMeta.query.filter_by(post_id=post.id).first()
                if not meta:
                    meta = PostMeta()  # type: ignore
                    meta.post_id = post.id
                meta.alt_text = alt_text or None
                meta.show_public = show_public
                meta.allow_likes = allow_likes
                meta.allow_comments = allow_comments
                meta.location_visibility = location_visibility
                db.session.add(meta)
                db.session.commit()
            except Exception as _meta_e:
                if app.debug:
                    print('DEBUG: PostMeta save failed:', _meta_e)

            # Etiquetas a partir de hashtags en la descripción
            try:
                tags = extract_hashtags(caption)
                if tags:
                    for name in tags:
                        tag = Tag.query.filter_by(name=name).first()
                        if not tag:
                            tag = Tag()  # type: ignore
                            tag.name = name
                            db.session.add(tag)
                            db.session.flush()
                        # evitar duplicados
                        tags_list = getattr(post, 'tags', [])
                        if tag not in tags_list:
                            tags_list.append(tag)
                    db.session.add(post)
                    db.session.commit()
            except Exception as _tag_e:
                if app.debug:
                    print('DEBUG: tag attach failed:', _tag_e)
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG: DB error creating post:', e)
            # Intentar limpiar el archivo guardado si falla DB
            try:
                if os.path.exists(save_path):
                    os.remove(save_path)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            flash('No se pudo crear la publicación.', 'danger')
            return redirect(url_for('index'))

        if app.debug:
            try:
                print('DEBUG: Post created successfully!')
                print(f'DEBUG: Post ID: {post.id}')
                print(f'DEBUG: Caption: {post.caption}')
                print(f'DEBUG: Image: {post.image_filename}')
                print(f'DEBUG: Author: {post.author.username}')
                print(f'DEBUG: Location: {post.location_name}')
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        # Mensajes según programación
        if current_user.username != 'admin':
            flash('Por seguridad tuya, tu publicación se hará pública en 15 min.', 'info')
        else:
            mode = (request.form.get('publish_mode') or 'now').lower()
            if mode == 'delay':
                flash('Publicación programada para hacerse pública en 15 min.', 'info')
            elif mode == 'schedule':
                if publish_at > datetime.now():
                    flash(f'Publicación programada para {publish_at.strftime("%d/%m/%Y %H:%M")}.', 'info')
                else:
                    flash('Publicación creada', 'success')
            else:
                flash('Publicación creada', 'success')
        return redirect(url_for('index'))

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return send_from_directory(os.path.join(os.path.dirname(__file__), 'static', 'images'), 'default_avatar.jpg')

        normalized = (filename or '').replace('\\', '/').lstrip('/')
        # Protect sensitive verification artifacts.
        if normalized.startswith('verify/'):
            if not current_user.is_authenticated:
                abort(403)
            if current_user.username != 'admin':
                own_req = VerificationRequest.query.filter_by(user_id=current_user.id).first()
                if not own_req or (own_req.video_filename or '').strip() != normalized:
                    abort(403)

        folder = ensure_upload_folder()
        return send_from_directory(folder, normalized)

    @app.route('/post/<int:post_id>')
    def post_detail(post_id):
        post = Post.query.get_or_404(post_id)
        if current_user.is_authenticated and is_user_blocked_between(current_user.id, post.user_id):
            abort(404)
        if not is_public_post(post) and (not current_user.is_authenticated or current_user.username != 'admin'):
            abort(404)
        comment_form = CommentForm()
        share_form = ShareForm()
        return render_template('post_detail.html', post=post, comment_form=comment_form, share_form=share_form)

    def _avatar_url(user):
        try:
            if user and getattr(user, 'profile_pic', None) and user.profile_pic != 'default.jpg':
                return url_for('uploaded_file', filename=user.profile_pic)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        return url_for('static', filename='images/default_avatar.jpg')

    @app.route('/comments/<int:post_id>')
    def comments(post_id):
        post = Post.query.get_or_404(post_id)
        if current_user.is_authenticated and is_user_blocked_between(current_user.id, post.user_id):
            return jsonify({'comments': []})
        if not is_public_post(post) and (not current_user.is_authenticated or current_user.username != 'admin'):
            return jsonify({'comments': []})
        out = []
        for c in post.comments:
            try:
                out.append({
                    'id': c.id,
                    'username': getattr(c.author, 'username', 'unknown'),
                    'profile_pic': _avatar_url(getattr(c, 'author', None)),
                    'content': c.content,
                    'created_at': c.created_at.isoformat() if getattr(c, 'created_at', None) else None,
                })
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        return jsonify({'comments': out})

    @app.route('/hotspots')
    def hotspots_page():
        return render_template('hotspots.html')

    @app.route('/chat')
    @login_required
    def chat():
        return render_template('chat.html')

    @app.route('/verify')
    @login_required
    def verify_identity():
        if is_user_verified(current_user):
            return render_template('verify.html', status='verified', verification=None)
        req = get_or_create_verification(current_user)
        return render_template('verify.html', status=req.status, verification=req)

    @app.route('/api/verify/send-otp', methods=['POST'])
    @login_required
    def verify_send_otp():
        if is_user_verified(current_user):
            return jsonify({'error': 'Cuenta ya verificada.'}), 400

        if is_rate_limited(f'verify_send_otp:user:{current_user.id}', limit=4, window_seconds=600):
            return jsonify({'error': 'Demasiados intentos. Intenta de nuevo en unos minutos.'}), 429

        req = get_or_create_verification(current_user)
        if req.status == 'pending':
            return jsonify({'error': 'Tu verificación está en revisión.'}), 400

        code = f"{secrets.randbelow(900000) + 100000}"
        email = getattr(current_user, 'email', None)
        if not email:
            return jsonify({'error': 'No hay email asociado a tu cuenta.'}), 400

        req.otp_code = code
        req.otp_expires_at = datetime.now() + timedelta(minutes=10)
        req.phone_verified_at = None
        db.session.add(req)
        db.session.commit()

        sent = send_verification_email(email, code)
        if not sent:
            return jsonify({'error': 'No se pudo enviar el correo. Revisa la configuración de correo (MAIL_* o RESEND_*).'}), 500

        session['verify_otp_failures'] = 0
        return jsonify({'ok': True, 'message': 'Código enviado a tu correo.'})

    @app.route('/api/verify/confirm-otp', methods=['POST'])
    @login_required
    def verify_confirm_otp():
        if is_user_verified(current_user):
            return jsonify({'error': 'Cuenta ya verificada.'}), 400

        if is_rate_limited(f'verify_confirm_otp:user:{current_user.id}', limit=15, window_seconds=600):
            return jsonify({'error': 'Demasiados intentos. Intenta de nuevo más tarde.'}), 429

        payload = request.get_json(silent=True) or request.form
        code = (payload.get('code') or '').strip()
        if not code:
            return jsonify({'error': 'Ingresa el código.'}), 400

        failures = int(session.get('verify_otp_failures', 0) or 0)
        if failures >= 8:
            return jsonify({'error': 'Demasiados intentos fallidos. Solicita un código nuevo.'}), 429

        req = get_or_create_verification(current_user)
        if not req.otp_code:
            return jsonify({'error': 'Primero solicita un código.'}), 400
        if req.otp_expires_at and req.otp_expires_at < datetime.now():
            return jsonify({'error': 'El código expiró. Solicita uno nuevo.'}), 400
        if code != req.otp_code:
            session['verify_otp_failures'] = failures + 1
            return jsonify({'error': 'Código incorrecto.'}), 400

        req.phone_verified_at = datetime.now()
        req.otp_code = None
        db.session.add(req)
        db.session.commit()
        session.pop('verify_otp_failures', None)
        return jsonify({'ok': True, 'message': 'Correo verificado'})

    @app.route('/api/verify/upload-video', methods=['POST'])
    @login_required
    def verify_upload_video():
        if is_user_verified(current_user):
            return jsonify({'error': 'Cuenta ya verificada.'}), 400

        if is_rate_limited(f'verify_upload_video:user:{current_user.id}', limit=8, window_seconds=600):
            return jsonify({'error': 'Demasiados intentos. Intenta de nuevo más tarde.'}), 429

        req = get_or_create_verification(current_user)
        if req.status == 'pending':
            return jsonify({'error': 'Tu verificación está en revisión.'}), 400
        file = request.files.get('video')
        if not file or not getattr(file, 'filename', ''):
            return jsonify({'error': 'Selecciona un video válido.'}), 400
        # Defense-in-depth for this endpoint specifically (global limit is 32MB)
        if request.content_length and int(request.content_length) > 32 * 1024 * 1024:
            return jsonify({'error': 'El video excede el tamaño permitido.'}), 413
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {'.mp4', '.mov', '.webm', '.m4v'}:
            return jsonify({'error': 'Formato no soportado. Usa MP4/MOV/WEBM.'}), 400
        folder = ensure_verification_folder()
        unique_name = f"{uuid4().hex}{ext}"
        save_path = os.path.join(folder, unique_name)
        try:
            file.save(save_path)
        except Exception:
            return jsonify({'error': 'No se pudo guardar el video.'}), 500
        req.video_filename = f"verify/{unique_name}"
        db.session.add(req)
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Video cargado.'})

    @app.route('/api/verify/submit', methods=['POST'])
    @login_required
    def verify_submit():
        if is_user_verified(current_user):
            return jsonify({'error': 'Cuenta ya verificada.'}), 400
        req = get_or_create_verification(current_user)
        if not req.phone_verified_at:
            return jsonify({'error': 'Verifica tu correo primero.'}), 400
        if not req.video_filename:
            return jsonify({'error': 'Sube tu video de verificación.'}), 400
        req.status = 'pending'
        req.submitted_at = datetime.now()
        db.session.add(req)
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Solicitud enviada. Te avisaremos cuando sea revisada.'})

    @app.route('/api/search')
    def api_search():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        q = (request.args.get('q') or '').strip()
        kind = (request.args.get('type') or 'both').lower()
        results = {'users': [], 'posts': []}
        if not q:
            return jsonify(results)

        # Buscar usuarios
        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()

        if kind in ('both', 'users'):
            users_q = User.query.filter(User.username.ilike(f'%{q}%'))
            if blocked_ids:
                users_q = users_q.filter(~User.id.in_(blocked_ids))
            users = users_q.order_by(User.created_at.desc()).limit(10).all()
            for u in users:
                results['users'].append({
                    'username': u.username,
                    'profile_pic': url_for('uploaded_file', filename=u.profile_pic) if u.profile_pic else None,
                    'posts_count': len(u.posts),
                })

        # Buscar posts por caption, tags o ubicación
        if kind in ('both', 'posts'):
            # Primero por caption/ubicación
            posts_q = public_posts_query(Post.query.filter(
                (Post.caption.ilike(f'%{q}%')) |
                (Post.location_name.ilike(f'%{q}%')) |
                (Post.city.ilike(f'%{q}%')) |
                (Post.country.ilike(f'%{q}%'))
            )).order_by(Post.created_at.desc()).limit(50)
            if blocked_ids:
                posts_q = posts_q.filter(~Post.user_id.in_(blocked_ids))
            posts = posts_q.all()

            # Si el término empieza con '#', buscar por tag
            try:
                search_tag = q[1:].lower() if q.startswith('#') else q.lower()
            except Exception:
                search_tag = q.lower()

            if search_tag:
                tag = Tag.query.filter(Tag.name.ilike(f'%{search_tag}%')).first()
                if tag:
                    # combinar sin duplicar
                    tag_posts = getattr(tag, 'posts', [])
                    for p in tag_posts:
                        if p not in posts and is_public_post(p) and (not blocked_ids or p.user_id not in blocked_ids):
                            posts.append(p)

            for p in posts[:50]:
                # Parse categories from JSON
                categories = []
                if getattr(p, 'categories', None):
                    try:
                        import json
                        categories = json.loads(p.categories)
                    except Exception:
                        categories = []

                loc = public_location_for_post(p, current_user)
                results['posts'].append({
                    'id': p.id,
                    'username': getattr(p.author, 'username', 'unknown'),
                    'caption': p.caption,
                    'image_url': url_for('uploaded_file', filename=p.image_filename),
                    'created_at': p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
                    'likes_count': p.get_likes_count(),
                    'comments_count': p.get_comments_count(),
                    'latitude': loc.get('lat'),
                    'longitude': loc.get('lng'),
                    'location_name': loc.get('name'),
                    'location_visibility': loc.get('visibility'),
                    'tags': [t.name for t in getattr(p, 'tags', [])] if hasattr(p, 'tags') else [],
                    'categories': categories,
                })

        return jsonify(results)

    @app.route('/api/hotspots')
    def api_hotspots():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Devuelve agregaciones por zona para visualizar hotspots de peligro.

        Parámetros opcionales:
            lat, lng, radius_km -> Si vienen, filtra por radio (aprox.).
            precision -> número de decimales para agrupar (def. 3 ~ 100m aprox.)
            category -> filtra por categoría predefinida (texto)
        """
        def match_category(post: Post, category: str | None) -> bool:
            if not category:
                return True
            cat = (category or '').strip().lower()
            if not cat:
                return True
            # Palabras clave por categoría
            cat_map = {
                'poca iluminación': ['iluminacion', 'iluminación', 'luz', 'oscuro', 'alumbrado'],
                'banquetas en mal estado': ['banqueta', 'banquetas', 'acera', 'aceras', 'pavimento', 'bache', 'baches'],
                'zonas inseguras': ['asalto', 'robo', 'insegura', 'inseguras', 'peligro', 'violencia', 'acoso'],
                'baldios': ['baldio', 'baldío', 'baldios', 'baldíos', 'lote', 'abandonado'],
            }
            keys = cat_map.get(cat, [])
            if not keys:
                return True
            # Por tags
            try:
                tag_names = [t.name.lower() for t in getattr(post, 'tags', []) or []]
                if any(k in tag_names for k in keys):
                    return True
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            # Por caption
            try:
                text = (post.caption or '').lower()
                if any(k in text for k in keys):
                    return True
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            # Finalmente check categories list from DB
            try:
                import json
                db_cats = json.loads(getattr(post, 'categories', '[]') or '[]')
                # Direct match
                if any(c.lower() == cat for c in db_cats):
                    return True
                # Keyword match against db categories
                for db_c in db_cats:
                    if any(k in db_c.lower() for k in keys):
                        return True
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            return False
        def within_radius(p_lat, p_lng, c_lat, c_lng, radius_km=1.0):
            try:
                from math import cos, radians, sqrt
                # Aproximación plana (válida para radios pequeños)
                dx = (p_lng - c_lng) * cos(radians((p_lat + c_lat) / 2)) * 111.32
                dy = (p_lat - c_lat) * 110.57
                dist = sqrt(dx*dx + dy*dy)
                return dist <= radius_km
            except Exception:
                return False

        c_lat = request.args.get('lat', type=float)
        c_lng = request.args.get('lng', type=float)
        radius = request.args.get('radius_km', 2.0, type=float)
        precision = request.args.get('precision', 3, type=int)
        category = request.args.get('category')

        q = Post.query
        posts = [p for p in q.all() if is_public_post(p)]
        buckets = {}

        for p in posts:
            if not match_category(p, category):
                continue
            if p.latitude is None or p.longitude is None:
                continue
            if c_lat is not None and c_lng is not None:
                if not within_radius(p.latitude, p.longitude, c_lat, c_lng, radius):
                    continue
            key = (round(p.latitude, precision), round(p.longitude, precision))
            info = buckets.get(key)
            if not info:
                info = {
                    'lat': key[0],
                    'lng': key[1],
                    'count': 0,
                    'likes': 0,
                    'tags': {},
                }
                buckets[key] = info
            info['count'] += 1
            try:
                info['likes'] += p.get_likes_count()
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            # Contar etiquetas
            if hasattr(p, 'tags'):
                for t in (p.tags or []):
                    info['tags'][t.name] = info['tags'].get(t.name, 0) + 1

        # Serializar
        payload = []
        for key, info in buckets.items():
            payload.append({
                'lat': info['lat'],
                'lng': info['lng'],
                'count': info['count'],
                'likes': info['likes'],
                'top_tags': sorted(info['tags'].items(), key=lambda x: x[1], reverse=True)[:3],
            })
        payload.sort(key=lambda x: x['count'], reverse=True)
        return jsonify({'hotspots': payload})

    @app.route('/api/posts-in-radius')
    def api_posts_in_radius():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Devuelve posts dentro de un radio aproximado (km) desde un centro lat/lng.

        Parámetros:
            lat (float), lng (float), radius_km (float, default 0.2)
        """
        c_lat = request.args.get('lat', type=float)
        c_lng = request.args.get('lng', type=float)
        radius = request.args.get('radius_km', 0.2, type=float)
        category = request.args.get('category')
        if c_lat is None or c_lng is None:
            return jsonify({'posts': []})

        def within_radius(p_lat, p_lng, c_lat, c_lng, radius_km=1.0):
            try:
                from math import cos, radians, sqrt
                dx = (p_lng - c_lng) * cos(radians((p_lat + c_lat) / 2)) * 111.32
                dy = (p_lat - c_lat) * 110.57
                dist = sqrt(dx*dx + dy*dy)
                return dist <= radius_km
            except Exception:
                return False

        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        posts = [
            p for p in Post.query.order_by(Post.created_at.desc()).all()
            if is_public_post(p) and (not blocked_ids or p.user_id not in blocked_ids)
        ]
        data = []
        for p in posts:
            # Reutilizar la lógica de categoría definida en api_hotspots
            def match_category_local(post: Post, category: str | None) -> bool:
                if not category:
                    return True
                cat = (category or '').strip().lower()
                if not cat:
                    return True
                cat_map = {
                    'poca iluminación': ['iluminacion', 'iluminación', 'luz', 'oscuro', 'alumbrado'],
                    'banquetas en mal estado': ['banqueta', 'banquetas', 'acera', 'aceras', 'pavimento', 'bache', 'baches'],
                    'zonas inseguras': ['asalto', 'robo', 'insegura', 'inseguras', 'peligro', 'violencia', 'acoso'],
                    'baldios': ['baldio', 'baldío', 'baldios', 'baldíos', 'lote', 'abandonado'],
                }
                keys = cat_map.get(cat, [])
                if not keys:
                    return True
                try:
                    tag_names = [t.name.lower() for t in getattr(post, 'tags', []) or []]
                    if any(k in tag_names for k in keys):
                        return True
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
                try:
                    text = (post.caption or '').lower()
                    if any(k in text for k in keys):
                        return True
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
                # Finalmente check categories list from DB
                try:
                    import json
                    db_cats = json.loads(getattr(post, 'categories', '[]') or '[]')
                    # Direct match
                    if any(c.lower() == cat for c in db_cats):
                        return True
                    # Keyword match against db categories
                    for db_c in db_cats:
                        if any(k in db_c.lower() for k in keys):
                            return True
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
                return False

            if not match_category_local(p, category):
                continue
            if p.latitude is None or p.longitude is None:
                continue
            if within_radius(p.latitude, p.longitude, c_lat, c_lng, radius):
                # Parse categories from JSON
                categories = []
                if getattr(p, 'categories', None):
                    try:
                        import json
                        categories = json.loads(p.categories)
                    except Exception:
                        categories = []

                try:
                    loc = public_location_for_post(p, current_user)
                    data.append({
                        'id': p.id,
                        'username': getattr(p.author, 'username', 'unknown'),
                        'caption': p.caption,
                        'image_url': url_for('uploaded_file', filename=p.image_filename),
                        'created_at': p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
                        'likes_count': p.get_likes_count(),
                        'comments_count': p.get_comments_count(),
                        'latitude': loc.get('lat'),
                        'longitude': loc.get('lng'),
                        'location_name': loc.get('name'),
                        'location_visibility': loc.get('visibility'),
                        'categories': categories,
                    })
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
        return jsonify({'posts': data})

    @app.route('/api/posts-by-city')
    def api_posts_by_city():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Filtra posts por ciudad usando coordenadas."""
        city = (request.args.get('city') or '').strip().lower()

        # Bounding boxes para cada municipio (lat_min, lat_max, lng_min, lng_max)
        city_bounds = {
            'monterrey': (25.60, 25.75, -100.42, -100.25),
            'san-pedro': (25.62, 25.70, -100.45, -100.35),
            'guadalupe': (25.65, 25.72, -100.28, -100.18),
            'apodaca': (25.73, 25.82, -100.25, -100.12),
            'escobedo': (25.75, 25.85, -100.38, -100.28),
            'santa-catarina': (25.62, 25.72, -100.52, -100.42),
        }

        def in_bounds(lat, lng, bounds):
            if lat is None or lng is None:
                return False
            lat_min, lat_max, lng_min, lng_max = bounds
            return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max

        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        posts_all = [
            p for p in Post.query.order_by(Post.created_at.desc()).all()
            if is_public_post(p) and (not blocked_ids or p.user_id not in blocked_ids)
        ]

        if city and city != 'all':
            bounds = city_bounds.get(city)
            if bounds:
                filtered = [p for p in posts_all if in_bounds(p.latitude, p.longitude, bounds)]
            else:
                filtered = [p for p in posts_all if p.city and city in p.city.lower()]
        else:
            filtered = posts_all

        data = []
        for p in filtered[:50]:
            try:
                author = p.author
                pic = url_for('static', filename='images/default_avatar.jpg')
                if author and author.profile_pic and author.profile_pic != 'default.jpg':
                    pic = url_for('uploaded_file', filename=author.profile_pic)
                loc = public_location_for_post(p, current_user)
                data.append({
                    'id': p.id,
                    'username': author.username if author else 'unknown',
                    'profile_pic': pic,
                    'caption': p.caption,
                    'image_url': url_for('uploaded_file', filename=p.image_filename),
                    'likes_count': p.get_likes_count(),
                    'comments_count': p.get_comments_count(),
                    'location_name': loc.get('name'),
                    'latitude': loc.get('lat'),
                    'longitude': loc.get('lng'),
                    'location_visibility': loc.get('visibility'),
                    'liked_by_me': p.is_liked_by(current_user) if current_user.is_authenticated else False,
                })
            except Exception as exc:
                _debug_log_suppressed('suppressed bare exception', exc)
        return jsonify({'posts': data})

    @app.route('/api/reports/nearby')
    @login_required
    def api_reports_nearby():
        """Devuelve reportes (posts con categorías) publicados recientemente dentro de un radio (km).

        Uso (cliente):
            /api/reports/nearby?lat=...&lng=...&radius_km=1&since=epoch_ms

        Notas:
        - Respeta visibilidad de ubicación (hidden no se incluye).
        - Excluye posts del propio usuario y de usuarios bloqueados.
        - "Recientemente" se define por publish_at (cuando el post se hace público).
        """
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403

        c_lat = request.args.get('lat', type=float)
        c_lng = request.args.get('lng', type=float)
        radius = request.args.get('radius_km', 1.0, type=float)
        since_ms = request.args.get('since', type=int)

        if c_lat is None or c_lng is None:
            return jsonify({'reports': []})

        since_dt = None
        if since_ms and since_ms > 0:
            try:
                since_dt = datetime.fromtimestamp(float(since_ms) / 1000.0)
            except Exception:
                since_dt = None

        def distance_km(p_lat: float, p_lng: float, c_lat: float, c_lng: float) -> float:
            from math import cos, radians, sqrt
            dx = (p_lng - c_lng) * cos(radians((p_lat + c_lat) / 2)) * 111.32
            dy = (p_lat - c_lat) * 110.57
            return sqrt(dx * dx + dy * dy)

        # Bounding box rápido para evitar escanear demasiado.
        try:
            from math import cos, radians
            lat_delta = float(radius) / 110.57
            lng_delta = float(radius) / (111.32 * max(0.01, cos(radians(float(c_lat)))))
        except Exception:
            lat_delta = float(radius) / 110.57
            lng_delta = float(radius) / 111.32

        blocked_ids = blocked_user_ids_for(current_user)

        q = public_posts_query(Post.query)
        q = q.filter(
            Post.user_id != current_user.id,
            Post.latitude.isnot(None),
            Post.longitude.isnot(None),
            Post.categories.isnot(None),
            Post.categories != '',
            Post.latitude.between(c_lat - lat_delta, c_lat + lat_delta),
            Post.longitude.between(c_lng - lng_delta, c_lng + lng_delta),
        )
        if blocked_ids:
            q = q.filter(~Post.user_id.in_(blocked_ids))

        if since_dt is not None:
            q = q.filter(or_(
                and_(Post.publish_at.isnot(None), Post.publish_at > since_dt),
                and_(Post.publish_at.is_(None), Post.created_at > since_dt),
            ))

        q = q.order_by(Post.publish_at.desc(), Post.created_at.desc()).limit(60)
        posts = q.all()

        out = []
        for p in posts:
            try:
                # Respeta visibilidad de ubicación (y aproximación para no-admin).
                loc = public_location_for_post(p, current_user)
                p_lat = loc.get('lat')
                p_lng = loc.get('lng')
                if p_lat is None or p_lng is None:
                    continue

                dist = float(distance_km(float(p_lat), float(p_lng), float(c_lat), float(c_lng)))
                if dist > float(radius):
                    continue

                # Parse categories from JSON
                categories = []
                try:
                    import json
                    categories = json.loads(getattr(p, 'categories', '[]') or '[]') or []
                except Exception:
                    categories = []
                if not categories:
                    continue

                published_at = getattr(p, 'publish_at', None) or getattr(p, 'created_at', None)
                out.append({
                    'id': p.id,
                    'username': getattr(getattr(p, 'author', None), 'username', 'unknown'),
                    'caption': p.caption or '',
                    'image_url': url_for('uploaded_file', filename=p.image_filename),
                    'published_at': published_at.isoformat() if published_at else None,
                    'distance_km': dist,
                    'categories': categories,
                    'location_name': loc.get('name'),
                    'location_visibility': loc.get('visibility'),
                })
            except Exception as exc:
                _debug_log_suppressed('suppressed exception in report aggregation', exc)

        return jsonify({'reports': out})

    @app.route('/api/stats')
    def api_stats():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        users_count = User.query.count()
        posts_count = Post.query.count()
        likes_count = Like.query.count()
        comments_count = Comment.query.count()
        # Top tags
        top_tags = []
        try:
            tags = Tag.query.all()
            pairs = [(t.name, len(getattr(t, 'posts', []))) for t in tags]
            top_tags = sorted(pairs, key=lambda x: x[1], reverse=True)[:10]
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        return jsonify({
            'users': users_count,
            'posts': posts_count,
            'likes': likes_count,
            'comments': comments_count,
            'top_tags': top_tags,
        })

    def _ensure_default_chat_room():
        room = ChatRoom.query.order_by(ChatRoom.id.asc()).first()
        if not room:
            admin_user = User.query.filter_by(username='admin').first()
            room = ChatRoom(
                name='Chat General',
                is_private=False,
                is_approved=True,
                messages_open=True,
                image_filename=None,
                description='Sala pública de la comunidad',
                created_by=admin_user.id if admin_user else None,
            )
            db.session.add(room)
            db.session.commit()
        return room

    # --- Chat API Routes ---

    @app.route('/api/chat/rooms')
    @login_required
    def api_chat_rooms():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Get all chat rooms (public to everyone)"""
        try:
            _ensure_default_chat_room()

            rooms = []
            all_rooms = ChatRoom.query.filter(ChatRoom.is_approved == True).order_by(ChatRoom.created_at.desc()).all()  # noqa: E712
            blocked_ids = blocked_user_ids_for(current_user)
            participants = {p.room_id: p for p in ChatParticipant.query.filter_by(user_id=current_user.id).all()}
            created_new = False

            for room in all_rooms:
                if room.created_by in blocked_ids:
                    continue

                participant = participants.get(room.id)
                if not participant:
                    participant = ChatParticipant(user_id=current_user.id, room_id=room.id)
                    db.session.add(participant)
                    participants[room.id] = participant
                    created_new = True

                # Get last message
                last_message = ChatMessage.query.filter_by(room_id=room.id).order_by(
                    ChatMessage.created_at.desc()
                ).first()

                # Count unread messages (exclude my own + deleted + blocked users)
                last_read = participant.last_read_at or utc_now_naive()
                unread_q = ChatMessage.query.filter_by(room_id=room.id).filter(
                    ChatMessage.created_at > last_read,
                    ChatMessage.user_id != current_user.id,
                    ChatMessage.is_deleted.is_(False),
                )
                if blocked_ids:
                    unread_q = unread_q.filter(~ChatMessage.user_id.in_(blocked_ids))
                unread_count = unread_q.count()
                last_unread_message_data = None
                if unread_count > 0:
                    last_unread = unread_q.order_by(ChatMessage.created_at.desc()).first()
                    if last_unread:
                        last_unread_attachment_url = None
                        if last_unread.attachment_filename:
                            last_unread_attachment_url = url_for('uploaded_file', filename=last_unread.attachment_filename)
                        last_unread_message_data = {
                            'id': last_unread.id,
                            'content': last_unread.content,
                            'username': last_unread.user.username if last_unread.user else None,
                            'created_at': last_unread.created_at.isoformat() if last_unread.created_at else None,
                            'message_type': last_unread.message_type,
                            'attachment_name': last_unread.attachment_name,
                            'attachment_url': last_unread_attachment_url,
                            'attachment_mime': last_unread.attachment_mime,
                            'is_deleted': False,
                        }

                image_url = url_for('static', filename='uploads/avatar.png')
                if getattr(room, 'image_filename', None) and room.image_filename != 'avatar.png':
                    image_url = url_for('uploaded_file', filename=room.image_filename)
                is_owner = room.created_by == current_user.id
                can_post = True
                if getattr(room, 'messages_open', True) is False:
                    can_post = current_user.username == 'admin' or is_owner
                last_is_deleted = bool(getattr(last_message, 'is_deleted', False)) if last_message else False
                rooms.append({
                    'id': room.id,
                    'name': room.name,
                    'is_private': room.is_private,
                    'description': room.description or '',
                    'image_url': image_url,
                    'created_by': room.created_by,
                    'messages_open': getattr(room, 'messages_open', True),
                    'can_post': can_post,
                    'last_message': {
                        'content': '' if last_is_deleted else (last_message.content if last_message else None),
                        'username': last_message.user.username if last_message else None,
                        'created_at': last_message.created_at.isoformat() if last_message else None,
                        'message_type': last_message.message_type if last_message else None,
                        'attachment_name': None if last_is_deleted else (last_message.attachment_name if last_message else None),
                        'attachment_url': url_for('uploaded_file', filename=last_message.attachment_filename) if last_message and last_message.attachment_filename and not last_is_deleted else None,
                        'is_deleted': last_is_deleted,
                    } if last_message else None,
                    'last_unread_message': last_unread_message_data,
                    'unread_count': unread_count,
                    'participants_count': len(room.participants),
                })

            if created_new:
                db.session.commit()

            return jsonify({'rooms': rooms})
        except Exception as e:
            if app.debug:
                print('DEBUG api_chat_rooms error:', e)
            return jsonify({'error': 'Error loading chat rooms'}), 500

    @app.route('/api/chat/room/<int:room_id>/read', methods=['POST'])
    @login_required
    def api_chat_room_mark_read(room_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Mark a room as read (updates participant.last_read_at)."""
        try:
            room = ChatRoom.query.get_or_404(room_id)
            if not room.is_approved:
                return jsonify({'error': 'Sala pendiente de aprobación'}), 403
            if room.created_by and is_user_blocked_between(current_user.id, room.created_by):
                return jsonify({'error': 'No tienes acceso a esta sala.'}), 403

            participant = ChatParticipant.query.filter_by(user_id=current_user.id, room_id=room_id).first()
            if not participant:
                participant = ChatParticipant(user_id=current_user.id, room_id=room_id)
                db.session.add(participant)

            participant.last_read_at = utc_now_naive()
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_chat_room_mark_read error:', e)
            return jsonify({'error': 'Error marking room as read'}), 500

    @app.route('/api/chat/room/<int:room_id>/messages')
    @login_required
    def api_chat_messages(room_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Get messages for a specific room"""
        try:
            room = ChatRoom.query.get_or_404(room_id)
            if not room.is_approved:
                return jsonify({'error': 'Sala pendiente de aprobación'}), 403
            if room.created_by and is_user_blocked_between(current_user.id, room.created_by):
                return jsonify({'error': 'No tienes acceso a esta sala.'}), 403

            # Ensure participant exists (public rooms)
            participant = ChatParticipant.query.filter_by(user_id=current_user.id, room_id=room_id).first()
            if not participant:
                participant = ChatParticipant(user_id=current_user.id, room_id=room_id)
                db.session.add(participant)
                db.session.commit()

            # Update last read time
            participant.last_read_at = utc_now_naive()
            db.session.commit()

            # Get messages with pagination
            page = request.args.get('page', 1, type=int)
            per_page = 50
            messages_query = ChatMessage.query.filter_by(room_id=room_id).order_by(ChatMessage.created_at.desc())
            messages_paginated = messages_query.paginate(page=page, per_page=per_page, error_out=False)

            messages = []
            for msg in messages_paginated.items:
                if is_user_blocked_between(current_user.id, msg.user_id):
                    continue
                is_deleted = bool(getattr(msg, 'is_deleted', False))
                attachment_url = None
                attachment_name = None
                attachment_mime = None
                if not is_deleted and msg.attachment_filename:
                    attachment_url = url_for('uploaded_file', filename=msg.attachment_filename)
                    attachment_name = msg.attachment_name
                    attachment_mime = msg.attachment_mime
                messages.append({
                    'id': msg.id,
                    'content': '' if is_deleted else msg.content,
                    'username': msg.user.username,
                    'user_id': msg.user.id,
                    'user_avatar': url_for('uploaded_file', filename=msg.user.profile_pic) if msg.user.profile_pic and msg.user.profile_pic != 'default.jpg' else url_for('static', filename='images/default_avatar.jpg'),
                    'created_at': msg.created_at.isoformat(),
                    'message_type': msg.message_type,
                    'attachment_name': attachment_name,
                    'attachment_url': attachment_url,
                    'attachment_mime': attachment_mime,
                    'is_deleted': is_deleted,
                })

            # Reverse to show oldest first
            messages.reverse()

            return jsonify({
                'messages': messages,
                'has_more': messages_paginated.has_prev,  # Since we're paginating backwards
                'page': page
            })
        except Exception as e:
            if app.debug:
                print('DEBUG api_chat_messages error:', e)
            return jsonify({'error': 'Error loading messages'}), 500

    @app.route('/api/chat/room/<int:room_id>/send', methods=['POST'])
    @login_required
    def api_chat_send(room_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        if is_user_temp_muted(current_user):
            return jsonify(temp_mute_error_payload('Tienes una restricción temporal para enviar mensajes.')), 403
        """Send a message to a room"""
        try:
            room = ChatRoom.query.get_or_404(room_id)
            if not room.is_approved:
                return jsonify({'error': 'Sala pendiente de aprobación'}), 403
            if room.created_by and is_user_blocked_between(current_user.id, room.created_by):
                return jsonify({'error': 'No puedes enviar mensajes en esta sala.'}), 403
            if not getattr(room, 'messages_open', True):
                if current_user.username != 'admin' and room.created_by != current_user.id:
                    return jsonify({'error': 'Solo el admin y el creador pueden enviar mensajes en esta sala.'}), 403

            # Ensure participant exists (public rooms)
            participant = ChatParticipant.query.filter_by(user_id=current_user.id, room_id=room_id).first()
            if not participant:
                participant = ChatParticipant(user_id=current_user.id, room_id=room_id)
                db.session.add(participant)
                db.session.commit()

            attachment_file = request.files.get('attachment') if request.files else None
            if attachment_file:
                original_name = attachment_file.filename or ''
                if not allowed_chat_attachment(original_name):
                    return jsonify({'error': 'Tipo de archivo no permitido'}), 400
                ext = original_name.rsplit('.', 1)[1].lower()
                filename = secure_filename(original_name)
                unique_filename = f"{uuid4()}.{ext}"

                content = (request.form.get('content') or '').strip()
                if content and contains_abusive_language(content):
                    apply_abuse_strike(current_user)
                    db.session.commit()
                    return jsonify({'error': 'El mensaje contiene lenguaje no permitido'}), 400

                ensure_upload_folder()
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                attachment_file.save(file_path)
                message_type = 'image' if ext in {'png', 'jpg', 'jpeg'} else 'file'
                message = ChatMessage(
                    content=content or '',
                    user_id=current_user.id,
                    room_id=room_id,
                    message_type=message_type,
                    attachment_filename=unique_filename,
                    attachment_name=original_name,
                    attachment_mime=attachment_file.mimetype
                )
            else:
                data = request.get_json() or {}
                content = (data.get('content') or '').strip()
                if not content:
                    return jsonify({'error': 'Message content required'}), 400
                if contains_abusive_language(content):
                    apply_abuse_strike(current_user)
                    db.session.commit()
                    return jsonify({'error': 'El mensaje contiene lenguaje no permitido'}), 400

                # Create message
                message = ChatMessage(
                    content=content,
                    user_id=current_user.id,
                    room_id=room_id,
                    message_type='text'
                )
            db.session.add(message)
            db.session.commit()

            message_data = {
                'id': message.id,
                'content': message.content,
                'username': current_user.username,
                'user_id': current_user.id,
                'user_avatar': url_for('uploaded_file', filename=current_user.profile_pic) if current_user.profile_pic and current_user.profile_pic != 'default.jpg' else url_for('static', filename='images/default_avatar.jpg'),
                'created_at': message.created_at.isoformat(),
                'message_type': message.message_type,
                'room_id': room_id,
                'attachment_name': message.attachment_name,
                'attachment_url': url_for('uploaded_file', filename=message.attachment_filename) if message.attachment_filename else None,
                'attachment_mime': message.attachment_mime,
                'is_deleted': False,
            }

            try:
                socketio.emit('new_message', message_data, room=f'room_{room_id}')
            except Exception as e:
                if app.debug:
                    print('DEBUG api_chat_send emit error:', e)

            return jsonify({
                'success': True,
                'message': message_data
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_chat_send error:', e)
            return jsonify({'error': 'Error sending message'}), 500

    @app.route('/api/chat/room/<int:room_id>/update', methods=['POST'])
    @login_required
    def api_chat_room_update(room_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Update chat room metadata (admin or creator only)."""
        room = ChatRoom.query.get_or_404(room_id)
        if current_user.username != 'admin' and room.created_by != current_user.id:
            return jsonify({'error': 'Acceso denegado'}), 403

        description = (request.form.get('description') or '').strip()
        room.description = description
        messages_open_raw = request.form.get('messages_open')
        if messages_open_raw is not None:
            room.messages_open = messages_open_raw == 'true'

        file = request.files.get('photo')
        if file and getattr(file, 'filename', ''):
            filename = secure_filename(file.filename)
            if not allowed_file(filename):
                return jsonify({'error': 'Tipo de archivo no permitido'}), 400
            unique_name = f"{uuid4().hex}.{filename.rsplit('.', 1)[1].lower()}"
            upload_folder = ensure_upload_folder()
            file.save(os.path.join(upload_folder, unique_name))
            room.image_filename = unique_name

        db.session.commit()

        image_url = url_for('static', filename='uploads/avatar.png')
        if getattr(room, 'image_filename', None) and room.image_filename != 'avatar.png':
            image_url = url_for('uploaded_file', filename=room.image_filename)

        return jsonify({
            'success': True,
            'room': {
                'id': room.id,
                'name': room.name,
                'description': room.description or '',
                'image_url': image_url,
                'created_by': room.created_by,
                'messages_open': getattr(room, 'messages_open', True),
            }
        })

    @app.route('/api/chat/create-room', methods=['POST'])
    @login_required
    def api_chat_create_room():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Create a new chat room"""
        try:
            data = request.get_json()
            room_name = data.get('name', '').strip()
            # All rooms are public for everyone
            is_private = False

            if not room_name:
                return jsonify({'error': 'Room name required'}), 400

            # Check if room name already exists
            existing = ChatRoom.query.filter_by(name=room_name).first()
            if existing:
                return jsonify({'error': 'Room name already exists'}), 400

            # Create room
            is_approved = True if current_user.username == 'admin' else False
            room = ChatRoom(
                name=room_name,
                is_private=is_private,
                is_approved=is_approved,
                messages_open=True,
                image_filename=None,
                description='',
                created_by=current_user.id
            )
            db.session.add(room)
            db.session.flush()  # Get room ID

            # Add creator as participant
            participant = ChatParticipant(user_id=current_user.id, room_id=room.id)
            db.session.add(participant)
            db.session.commit()

            if not is_approved:
                return jsonify({
                    'success': True,
                    'pending': True,
                    'message': 'El administrador tiene que autorizar el chat que acabas de crear, esto puede tardar hasta 24 horas hábiles.'
                })

            return jsonify({
                'success': True,
                'room': {
                    'id': room.id,
                    'name': room.name,
                    'is_private': room.is_private,
                    'participants_count': 1,
                }
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_chat_create_room error:', e)
            return jsonify({'error': 'Error creating room'}), 500

    @app.route('/api/chat/room/<int:room_id>/join', methods=['POST'])
    @login_required
    def api_chat_join_room(room_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Join a chat room"""
        try:
            room = ChatRoom.query.get_or_404(room_id)
            if not room.is_approved:
                return jsonify({'error': 'Sala pendiente de aprobación'}), 403
            if room.created_by and is_user_blocked_between(current_user.id, room.created_by):
                return jsonify({'error': 'No puedes unirte a esta sala.'}), 403

            # Check if already participant
            existing = ChatParticipant.query.filter_by(user_id=current_user.id, room_id=room_id).first()
            if existing:
                return jsonify({'error': 'Already a participant'}), 400

            # Add participant
            participant = ChatParticipant(user_id=current_user.id, room_id=room_id)
            db.session.add(participant)
            db.session.commit()

            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_chat_join_room error:', e)
            return jsonify({'error': 'Error joining room'}), 500

    @app.route('/api/chat/users')
    @login_required
    def api_chat_users():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Get list of users for chat"""
        try:
            users = User.query.filter(User.id != current_user.id).all()
            user_list = []
            for user in users:
                user_list.append({
                    'id': user.id,
                    'username': user.username,
                    'profile_pic': url_for('uploaded_file', filename=user.profile_pic) if user.profile_pic else None,
                })
            return jsonify({'users': user_list})
        except Exception as e:
            if app.debug:
                print('DEBUG api_chat_users error:', e)
            return jsonify({'error': 'Error loading users'}), 500

    # --- SocketIO Event Handlers for Real-time Chat ---
    # Join/leave only. Sending messages happens via the HTTP API to enforce
    # verification, mute rules, and room permissions.

    @socketio.on('join_room')
    def handle_join_room(data):
        """Handle user joining a chat room (subscribe to broadcasts)."""
        try:
            room_id = data.get('room_id') if isinstance(data, dict) else None
            silent_join = bool(data.get('silent')) if isinstance(data, dict) else False
            if not room_id:
                return
            if not current_user.is_authenticated:
                return

            room = ChatRoom.query.get(room_id)
            if not room or not room.is_approved:
                return
            if room.created_by and is_user_blocked_between(current_user.id, room.created_by):
                return

            participant = ChatParticipant.query.filter_by(user_id=current_user.id, room_id=room_id).first()
            if room.is_private and not participant:
                return
            if not participant:
                participant = ChatParticipant(user_id=current_user.id, room_id=room_id)
                db.session.add(participant)
                db.session.commit()

            join_room(f'room_{room_id}')
            if not silent_join:
                emit('user_joined', {
                    'username': current_user.username,
                    'room_id': room_id
                }, room=f'room_{room_id}')
        except Exception as e:
            if app.debug:
                print('DEBUG socket join_room error:', e)

    @socketio.on('leave_room')
    def handle_leave_room(data):
        """Handle user leaving a chat room (unsubscribe)."""
        try:
            room_id = data.get('room_id') if isinstance(data, dict) else None
            if not room_id:
                return
            if not current_user.is_authenticated:
                return

            leave_room(f'room_{room_id}')
            emit('user_left', {
                'username': current_user.username,
                'room_id': room_id
            }, room=f'room_{room_id}')
        except Exception as e:
            if app.debug:
                print('DEBUG socket leave_room error:', e)

    @app.route('/api/transit-route')
    def api_transit_route_local():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Buscador de rutas locales basado en archivos JSON"""
        start_lat = request.args.get('start_lat')
        start_lng = request.args.get('start_lng')
        dest_lat = request.args.get('dest_lat')
        dest_lng = request.args.get('dest_lng')

        if not all([start_lat, start_lng, dest_lat, dest_lng]):
            return jsonify({'error': 'Faltan coordenadas'}), 400

        try:
            start_lat = float(start_lat)
            start_lng = float(start_lng)
            dest_lat = float(dest_lat)
            dest_lng = float(dest_lng)
        except ValueError:
            return jsonify({'error': 'Coordenadas inválidas'}), 400

        def haversine(lat1, lon1, lat2, lon2):
            """Calcula distancia en metros entre dos coordenadas"""
            R = 6371000  # Radio de la Tierra en metros
            dLat = radians(lat2 - lat1)
            dLon = radians(lon2 - lon1)
            a = sin(dLat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dLon / 2)**2
            c = 2 * asin(sqrt(a))
            return R * c

        def get_closest_point_on_route(route_coords, target_lat, target_lng):
            """Encuentra el punto más cercano en la ruta y su índice"""
            best_idx = -1
            min_dist = float('inf')
            
            for i, (lat, lng) in enumerate(route_coords):
                dist = haversine(target_lat, target_lng, lat, lng)
                if dist < min_dist:
                    min_dist = dist
                    best_idx = i
            
            return best_idx, min_dist

        # Configuración
        MAX_WALK_DIST = 5000  # Metros máximos para caminar hacia/desde la parada (Increased for testing)
        routes_dir = os.path.join(app.root_path, 'routes')
        
        best_route = None
        min_total_walk = float('inf')

        # Buscar en todos los archivos JSON
        route_files = glob.glob(os.path.join(routes_dir, '*.json'))
        
        print(f"Buscando rutas en {len(route_files)} archivos...")

        for file_path in route_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                    data = content.get('data', {})
                    ways = data.get('ways', [])
                    route_name = data.get('name', 'Ruta desconocida')

                    # Aplanar geometría (unir todos los segmentos)
                    full_path = []
                    for way in ways:
                        # Asegurar formato [lat, lng]
                        points = way.get('geometry', [])
                        # A veces geometry viene como [[lat,lng],...] directamente
                        full_path.extend(points)

                    if not full_path:
                        continue

                    # Encontrar mejor punto de subida (cerca del inicio)
                    start_idx, start_dist = get_closest_point_on_route(full_path, start_lat, start_lng)
                    
                    # Encontrar mejor punto de bajada (cerca del destino)
                    end_idx, end_dist = get_closest_point_on_route(full_path, dest_lat, dest_lng)

                    # Validaciones:
                    # 1. Ambos puntos deben estar dentro del umbral de caminata
                    if start_dist > MAX_WALK_DIST or end_dist > MAX_WALK_DIST:
                        continue

                    # 2. El punto de bajada debe estar DESPUÉS del punto de subida (dirección correcta)
                    # Se permite un margen pequeño de error si es el mismo punto
                    if end_idx <= start_idx:
                        continue

                    total_walk = start_dist + end_dist
                    
                    # Si es la mejor opción hasta ahora, guardarla
                    if total_walk < min_total_walk:
                        min_total_walk = total_walk
                        
                        # Cortar solo el segmento del viaje
                        segment = full_path[start_idx : end_idx + 1]
                        
                        best_route = {
                            'found': True,
                            'name': route_name,
                            'geometry': segment,
                            'walk_start_dist': round(start_dist),
                            'walk_end_dist': round(end_dist),
                            'transit_dist': round(haversine(start_lat, start_lng, dest_lat, dest_lng)), # Aprox
                            'details': {
                                'start_idx': start_idx,
                                'end_idx': end_idx
                            }
                        }

            except Exception as e:
                print(f"Error leyendo ruta {file_path}: {e}")
                continue

        if best_route:
            return jsonify(best_route)
        else:
            return jsonify({
                'found': False, 
                'error': 'No se encontró ninguna ruta cercana en la base de datos local.'
            })

    @app.route('/api/transit')
    def api_transit():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Rutas y paradas de camión (OSM/Overpass) para el área metropolitana.

        Devuelve un resumen de relaciones de rutas (id, ref, name, operator)
        y paradas (id, nombre, lat, lon) dentro del bbox por defecto de
        Monterrey y municipios aledaños. Usa un cache local en instance/ para
        reducir llamadas a Overpass.

        Parámetros opcionales:
            bbox: "south,west,north,east". Si no se da, se usa por defecto
                  25.30,-100.80,26.10,-99.90
            force: 1 para forzar recarga del cache
        """
        import json
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        import time

        # BBox por defecto (Monterrey y AMG): south,west,north,east
        bbox_str = request.args.get('bbox') or '25.30,-100.80,26.10,-99.90'
        try:
            south, west, north, east = [float(x) for x in bbox_str.split(',')]
        except Exception:
            return jsonify({'error': 'bbox inválido'}), 400

        force = request.args.get('force') == '1'

        # Cache en instance
        try:
            os.makedirs(app.instance_path, exist_ok=True)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        cache_path = os.path.join(app.instance_path, 'overpass_transit_cache.json')
        now = int(time.time())
        ttl = 12 * 3600  # 12h

        if not force:
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                if cached and (now - int(cached.get('ts', 0))) < ttl and cached.get('bbox') == [south, west, north, east]:
                    return jsonify({'bbox': cached.get('bbox'), 'routes': cached.get('routes', []), 'stops': cached.get('stops', [])})
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        # Overpass query: relaciones de ruta (bus/tram) y sus paradas
        # Nota: devolvemos solo resumen de rutas, la geometría detallada se pide aparte.
        q = f"""
        [out:json][timeout:25];
        (
          relation["type"="route"]["route"~"bus|trolleybus|tram"]({south},{west},{north},{east});
        );
        out ids tags;
        node(r)["highway"="bus_stop"];
        out tags; 
        node(r)["public_transport"="platform"]["bus"="yes"];
        out tags;
        """.strip()

        try:
            data = urlencode({'data': q}).encode('utf-8')
            req = Request('https://overpass-api.de/api/interpreter', data=data, headers={'User-Agent': 'VioletaApp/1.0 (+contact@example.com)'})
            with urlopen(req, timeout=30) as resp:  # nosec B310
                j = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if app.debug:
                print('Overpass error:', e)
            return jsonify({'routes': [], 'stops': []})

        routes = []
        stops = []
        for el in j.get('elements', []):
            t = el.get('type')
            if t == 'relation':
                tags = el.get('tags', {}) or {}
                routes.append({
                    'id': el.get('id'),
                    'ref': tags.get('ref'),
                    'name': tags.get('name'),
                    'operator': tags.get('operator'),
                    'network': tags.get('network'),
                    'route': tags.get('route'),
                })
            elif t == 'node':
                tags = el.get('tags', {}) or {}
                nm = tags.get('name') or tags.get('ref') or 'Parada'
                stops.append({
                    'id': el.get('id'),
                    'name': nm,
                    'lat': el.get('lat'),
                    'lon': el.get('lon'),
                })

        payload = {'bbox': [south, west, north, east], 'routes': routes, 'stops': stops}

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({'ts': now, 'bbox': [south, west, north, east], 'routes': routes, 'stops': stops}, f, ensure_ascii=False)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        return jsonify(payload)

    @app.route('/api/transit/route/<int:rel_id>')
    def api_transit_route(rel_id: int):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Devuelve la geometría (ways) de una ruta (relation id) desde Overpass.

        Respuesta: { id, ref, name, ways: [ { id, geometry: [[lat,lng], ...] } ] }
        Cachea por 12h en instance/.
        """
        import json
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        import time

        try:
            os.makedirs(app.instance_path, exist_ok=True)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        cache_path = os.path.join(app.instance_path, f'overpass_route_{rel_id}.json')
        now = int(time.time())
        ttl = 12 * 3600

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            if cached and (now - int(cached.get('ts', 0))) < ttl:
                return jsonify(cached.get('data'))
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        q = f"""
        [out:json][timeout:25];
        relation({rel_id});
        out ids tags;
        way(r);
        out tags geom;
        """.strip()

        try:
            data = urlencode({'data': q}).encode('utf-8')
            req = Request('https://overpass-api.de/api/interpreter', data=data, headers={'User-Agent': 'VioletaApp/1.0 (+contact@example.com)'})
            with urlopen(req, timeout=30) as resp:  # nosec B310
                j = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if app.debug:
                print('Overpass route error:', e)
            return jsonify({'id': rel_id, 'ways': []})

        ref = None
        name = None
        ways = []
        for el in j.get('elements', []):
            if el.get('type') == 'relation':
                tags = el.get('tags', {}) or {}
                ref = tags.get('ref')
                name = tags.get('name')
        for el in j.get('elements', []):
            if el.get('type') == 'way':
                geom = el.get('geometry') or []
                coords = []
                for pt in geom:
                    lat = pt.get('lat'); lon = pt.get('lon')
                    if lat is None or lon is None: continue
                    coords.append([lat, lon])
                if coords:
                    ways.append({'id': el.get('id'), 'geometry': coords})

        data = {'id': rel_id, 'ref': ref, 'name': name, 'ways': ways}
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({'ts': now, 'data': data}, f, ensure_ascii=False)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        return jsonify(data)

    @app.route('/api/transit/route/<int:rel_id>/stops')
    def api_transit_route_stops(rel_id: int):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Devuelve las paradas (nodos) que son miembros de la ruta dada.

        Respuesta: { id, stops: [ { id, name, lat, lon } ] }
        Cachea por 12h en instance/.
        """
        import json
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        import time

        try:
            os.makedirs(app.instance_path, exist_ok=True)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        cache_path = os.path.join(app.instance_path, f'overpass_route_{rel_id}_stops.json')
        now = int(time.time())
        ttl = 12 * 3600

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            if cached and (now - int(cached.get('ts', 0))) < ttl:
                return jsonify(cached.get('data'))
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        q = f"""
        [out:json][timeout:25];
        relation({rel_id});
        node(r)["highway"="bus_stop"];
        out ids tags center;
        node(r)["public_transport"="platform"]["bus"="yes"];
        out ids tags center;
        """.strip()

        try:
            data = urlencode({'data': q}).encode('utf-8')
            req = Request('https://overpass-api.de/api/interpreter', data=data, headers={'User-Agent': 'VioletaApp/1.0 (+contact@example.com)'})
            with urlopen(req, timeout=30) as resp:  # nosec B310
                j = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if app.debug:
                print('Overpass route stops error:', e)
            return jsonify({'id': rel_id, 'stops': []})

        stops = []
        for el in j.get('elements', []):
            if el.get('type') == 'node':
                tags = el.get('tags', {}) or {}
                nm = tags.get('name') or tags.get('ref') or 'Parada'
                stops.append({
                    'id': el.get('id'),
                    'name': nm,
                    'lat': el.get('lat'),
                    'lon': el.get('lon'),
                })

        data = {'id': rel_id, 'stops': stops}
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({'ts': now, 'data': data}, f, ensure_ascii=False)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        return jsonify(data)

    @app.route('/like/<int:post_id>', methods=['POST'])
    @login_required
    def like(post_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        if is_user_temp_muted(current_user):
            return jsonify({'ok': False, **temp_mute_error_payload('Tienes una restricción temporal de interacción.')}), 403
        post = Post.query.get_or_404(post_id)
        if is_user_blocked_between(current_user.id, post.user_id):
            return jsonify({'ok': False, 'error': 'No puedes interactuar con esta cuenta.'}), 403
        if not is_public_post(post):
            return jsonify({'ok': False, 'error': 'Publicación no disponible'}), 404
        if not can_user_interact_post(post, current_user, 'like'):
            return jsonify({'ok': False, 'error': 'La autora limitó los likes en esta publicación.'}), 403
        existing = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first()
        liked = False
        try:
            if existing:
                db.session.delete(existing)
                db.session.commit()
            else:
                like = Like()  # type: ignore
                like.user_id = current_user.id
                like.post_id = post.id
                db.session.add(like)
                db.session.commit()
                liked = True
            return jsonify({'liked': liked, 'likes_count': post.get_likes_count()})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG like error:', e)
            return jsonify({'ok': False, 'error': 'No se pudo actualizar el like.'}), 400

    @app.route('/comment/<int:post_id>', methods=['POST'])
    @login_required
    def comment(post_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        if is_user_temp_muted(current_user):
            return jsonify({'ok': False, **temp_mute_error_payload('Tienes una restricción temporal de interacción.')}), 403
        form = CommentForm()
        content = safe_field(form, 'content')
        if not content:
            return jsonify({'ok': False, 'error': 'Contenido vacío o formulario inválido'}), 400
        if contains_abusive_language(content):
            apply_abuse_strike(current_user)
            db.session.commit()
            return jsonify({'ok': False, 'error': 'Tu comentario contiene lenguaje no permitido.'}), 400
        post = Post.query.get_or_404(post_id)
        if is_user_blocked_between(current_user.id, post.user_id):
            return jsonify({'ok': False, 'error': 'No puedes interactuar con esta cuenta.'}), 403
        if not is_public_post(post):
            return jsonify({'ok': False, 'error': 'Publicación no disponible'}), 404
        if not can_user_interact_post(post, current_user, 'comment'):
            return jsonify({'ok': False, 'error': 'La autora desactivó los comentarios en esta publicación.'}), 403
        try:
            c = Comment()  # type: ignore
            c.content = content
            c.user_id = current_user.id
            c.post = post
            db.session.add(c)
            db.session.commit()
            return jsonify({
                'ok': True,
                'comment': {
                    'id': c.id,
                    'username': current_user.username,
                    'profile_pic': _avatar_url(current_user),
                    'content': c.content,
                    'created_at': c.created_at.isoformat(),
                },
                'comments_count': post.get_comments_count(),
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG comment error:', e)
            return jsonify({'ok': False, 'error': 'No se pudo guardar el comentario'}), 400

    @app.route('/share/<int:post_id>', methods=['POST'])
    @login_required
    def share(post_id):
        if is_user_temp_muted(current_user):
            return jsonify({'ok': False, **temp_mute_error_payload('Tienes una restricción temporal de interacción.')}), 403
        form = ShareForm()
        receiver_username = safe_field(form, 'receiver_username')
        message = safe_field(form, 'message') or ''
        if message and contains_abusive_language(message):
            apply_abuse_strike(current_user)
            db.session.commit()
            return jsonify({'ok': False, 'error': 'Tu mensaje contiene lenguaje no permitido'}), 400
        if not receiver_username:
            return jsonify({'ok': False, 'error': 'Usuaria destinataria inválida'}), 400
        receiver = User.query.filter_by(username=receiver_username).first()
        if not receiver:
            return jsonify({'ok': False, 'error': 'La usuaria destinataria no existe'}), 404
        if is_user_blocked_between(current_user.id, receiver.id):
            return jsonify({'ok': False, 'error': 'No puedes compartir con esta cuenta.'}), 403
        post = Post.query.get_or_404(post_id)
        if is_user_blocked_between(current_user.id, post.user_id):
            return jsonify({'ok': False, 'error': 'No puedes compartir esta publicación.'}), 403
        if not is_public_post(post):
            return jsonify({'ok': False, 'error': 'Publicación no disponible'}), 404
        try:
            s = Share()  # type: ignore
            s.sender_id = current_user.id
            s.receiver_id = receiver.id
            s.post_id = post.id
            s.message = message
            db.session.add(s)
            db.session.commit()
            return jsonify({'ok': True})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG share error:', e)
            return jsonify({'ok': False, 'error': 'No se pudo compartir la publicación'}), 400

    REPORT_REASONS = [
        'Información falso',
        'La imagen no corresponde al evento',
        'La imagen fue hecha con IA',
        'Descripción con lenguaje verbal insultante',
        'La ubicación no corresponde al lugar donde se tomó la foto',
    ]

    @app.route('/report_post/<int:post_id>', methods=['POST'])
    @login_required
    def report_post(post_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        if is_user_temp_muted(current_user):
            return jsonify(temp_mute_error_payload('Tienes una restricción temporal de interacción.')), 403
        data = request.get_json(silent=True) or request.form or {}
        reason = (data.get('reason') or '').strip()
        details = (data.get('details') or '').strip()

        if reason not in REPORT_REASONS:
            return jsonify({'ok': False, 'error': 'Categoría inválida'}), 400

        post = Post.query.get_or_404(post_id)
        if is_user_blocked_between(current_user.id, post.user_id):
            return jsonify({'ok': False, 'error': 'No puedes reportar contenido de esta cuenta.'}), 403
        existing = Report.query.filter_by(post_id=post.id, reporter_id=current_user.id).first()

        try:
            if existing:
                existing.reason = reason
                existing.details = details or None
                existing.status = 'pending'
                existing.admin_note = None
                existing.resolved_at = None
                existing.resolved_by = None
                report = existing
            else:
                report = Report()  # type: ignore
                report.post_id = post.id
                report.reporter_id = current_user.id
                report.reason = reason
                report.details = details or None
                report.status = 'pending'
                db.session.add(report)

            meta = PostMeta.query.filter_by(post_id=post.id).first()
            if not meta:
                meta = PostMeta()  # type: ignore
                meta.post_id = post.id
            meta.show_public = False
            db.session.add(meta)

            db.session.commit()
            return jsonify({'ok': True, 'message': 'Reporte enviado', 'report_id': report.id, 'status': report.status})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG report_post error:', e)
            return jsonify({'ok': False, 'error': 'No se pudo enviar el reporte'}), 400

    @app.route('/api/my/reports')
    @login_required
    def my_reports():
        try:
            rows = Report.query.filter_by(reporter_id=current_user.id).order_by(Report.created_at.desc()).all()
            items = []
            for r in rows:
                p = r.post
                image_url = None
                if p and getattr(p, 'image_filename', None):
                    image_url = url_for('uploaded_file', filename=p.image_filename)
                items.append({
                    'id': r.id,
                    'post_id': r.post_id,
                    'reason': r.reason,
                    'details': r.details or '',
                    'status': r.status or 'pending',
                    'admin_note': r.admin_note or '',
                    'created_at': r.created_at.isoformat() if r.created_at else None,
                    'resolved_at': r.resolved_at.isoformat() if r.resolved_at else None,
                    'image_url': image_url,
                })
            return jsonify({'reports': items})
        except Exception as e:
            if app.debug:
                print('DEBUG my_reports error:', e)
            return jsonify({'error': 'No se pudo cargar el estado de tus reportes'}), 500

    @app.route('/delete/<int:post_id>', methods=['POST'])
    @login_required
    def delete_post(post_id):
        post = Post.query.get_or_404(post_id)
        if post.user_id != current_user.id:
            flash('No tienes permiso para eliminar esta publicación.', 'danger')
            return redirect(url_for('profile'))
        if post.created_at and utc_now_naive() - post.created_at > timedelta(hours=1):
            flash('Solo puedes eliminar una publicación dentro de la primera hora.', 'danger')
            return redirect(url_for('profile'))
        try:
            # Delete the image file if exists
            if post.image_filename:
                upload_folder = ensure_upload_folder()
                image_path = os.path.join(upload_folder, post.image_filename)
                if os.path.exists(image_path):
                    os.remove(image_path)
            # Delete the post (cascade will handle related records)
            db.session.delete(post)
            db.session.commit()
            flash('Publicación eliminada.', 'success')
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG delete error:', e)
            flash('No se pudo eliminar la publicación.', 'danger')
        return redirect(url_for('profile'))

    @app.route('/nueva-pagina')
    def nueva_pagina():
        return render_template('nueva_pagina.html')

    @app.route('/profile')
    @login_required
    def profile():
        user = current_user
        # Ordenar posts por fecha (más recientes primero)
        user_posts = sorted(user.posts, key=lambda p: p.created_at or 0, reverse=True)
        now = datetime.now()
        for p in user_posts:
            p.can_delete = bool(p.created_at and (now - p.created_at) <= timedelta(hours=1))
            p.is_pending = bool(getattr(p, 'publish_at', None) and getattr(p, 'publish_at') > now)
        report_count = len(user_posts)
        total_likes = sum((p.get_likes_count() for p in user_posts), 0)
        total_comments = sum((p.get_comments_count() for p in user_posts), 0)
        return render_template(
            'profile.html',
            user=user,
            posts=user_posts,
            report_count=report_count,
            total_likes=total_likes,
            total_comments=total_comments,
        )

    @app.route('/admin')
    @login_required
    def admin_panel():
        if current_user.username != 'admin':
            flash('Acceso denegado. Solo para administradores.', 'error')
            return redirect(url_for('index'))

        process_overdue_checkins()

        # Get all users and posts for admin management
        users = User.query.all()
        posts = Post.query.all()
        # Ensure at least one public chat room exists
        try:
            _ensure_default_chat_room()
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        chat_rooms = ChatRoom.query.order_by(ChatRoom.created_at.desc()).all()
        pending_rooms = [r for r in chat_rooms if not getattr(r, 'is_approved', True)]

        verifications = VerificationRequest.query.order_by(VerificationRequest.created_at.desc()).all()
        pending_verifications = [v for v in verifications if getattr(v, 'status', '') == 'pending']

        checkins = SafetyCheckin.query.order_by(SafetyCheckin.started_at.desc()).limit(200).all()

        # Calculate statistics
        total_likes = sum(post.get_likes_count() for post in posts)
        total_comments = sum(post.get_comments_count() for post in posts)

        return render_template(
            'admin.html',
            users=users,
            posts=posts,
            total_likes=total_likes,
            total_comments=total_comments,
            chat_rooms=chat_rooms,
            pending_rooms=pending_rooms,
            verifications=verifications,
            pending_verifications=pending_verifications,
            panic_events=PanicEvent.query.filter_by(status='open').order_by(PanicEvent.created_at.desc()).all(),
            checkins=checkins,
        )

    @app.route('/admin/reports_timeseries')
    @login_required
    def admin_reports_timeseries():
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        days = request.args.get('days', default=7, type=int)
        if days not in (7, 15, 30):
            days = 7

        today = utc_now_naive().date()
        start_date = today - timedelta(days=days - 1)
        start_dt = datetime.combine(start_date, datetime.min.time())

        posts = Post.query.filter(
            Post.created_at >= start_dt,
            Post.categories.isnot(None),
            Post.categories != '',
        ).all()
        date_to_index = {
            start_date + timedelta(days=idx): idx
            for idx in range(days)
        }

        def extract_categories(cats_raw):
            if not cats_raw:
                return set()
            try:
                cats = json.loads(cats_raw)
            except Exception:
                return set()
            if not isinstance(cats, list):
                return set()

            normalized = set()
            for c in cats:
                if c is None:
                    continue
                raw = str(c).strip()
                if not raw:
                    continue
                key = raw.casefold()
                if key in ('baldios', 'baldío', 'baldio', 'baldíos'):
                    normalized.add('Baldíos')
                elif key in ('poca iluminacion', 'poca iluminación'):
                    normalized.add('Poca iluminación')
                elif key in ('banquetas en mal estado',):
                    normalized.add('Banquetas en mal estado')
                elif key in ('zonas inseguras',):
                    normalized.add('Zonas inseguras')
                else:
                    normalized.add(raw)
            return normalized

        # category -> [count_day_0 ... count_day_n]
        counts_by_category = {}
        for post in posts:
            created = getattr(post, 'created_at', None)
            if not created:
                continue
            idx = date_to_index.get(created.date())
            if idx is None:
                continue
            categories = extract_categories(getattr(post, 'categories', None))
            for category in categories:
                if category not in counts_by_category:
                    counts_by_category[category] = [0] * days
                counts_by_category[category][idx] += 1

        categories = []
        for name, series in counts_by_category.items():
            total = sum(series)
            if total <= 0:
                continue
            categories.append({
                'name': name,
                'counts': series,
                'total': total,
            })

        categories.sort(key=lambda item: item['total'], reverse=True)
        totals = [
            sum(item['counts'][day_idx] for item in categories)
            for day_idx in range(days)
        ]
        labels = [
            (start_date + timedelta(days=idx)).strftime('%d/%m')
            for idx in range(days)
        ]
        label_dates = [
            (start_date + timedelta(days=idx)).isoformat()
            for idx in range(days)
        ]

        return jsonify({
            'days': days,
            'labels': labels,
            'label_dates': label_dates,
            'categories': categories,
            'totals': totals,
            'total_reports': int(sum(totals)),
            'total_posts': int(sum(totals)),
            'updated_at': utc_now_naive().isoformat(),
        })

    @app.route('/admin/verify/<int:req_id>/approve', methods=['POST'])
    @login_required
    def admin_approve_verification(req_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        req = VerificationRequest.query.get_or_404(req_id)
        req.status = 'approved'
        req.reviewed_at = datetime.now()
        req.reviewed_by = current_user.id
        user = User.query.get(req.user_id)
        if user:
            user.is_verified = True
        db.session.add(req)
        db.session.commit()
        return jsonify({'success': True})

    @app.route('/admin/verify/<int:req_id>/reject', methods=['POST'])
    @login_required
    def admin_reject_verification(req_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        req = VerificationRequest.query.get_or_404(req_id)
        req.status = 'rejected'
        req.reviewed_at = datetime.now()
        req.reviewed_by = current_user.id
        user = User.query.get(req.user_id)
        if user:
            user.is_verified = False
        db.session.add(req)
        db.session.commit()
        return jsonify({'success': True})

    def safe_remove_upload(filename: str | None):
        if not filename:
            return
        if filename.startswith('http'):
            return
        if 'default_avatar' in filename or filename.endswith('default.jpg'):
            return
        name = filename
        if name.startswith('/uploads/'):
            name = name.split('/uploads/', 1)[1]
        if name.startswith('uploads/'):
            name = name.split('uploads/', 1)[1]
        upload_folder = ensure_upload_folder()
        file_path = os.path.join(upload_folder, name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
    def delete_user_and_related(target_user: User):
        # Verification requests + videos
        reqs = VerificationRequest.query.filter_by(user_id=target_user.id).all()
        for req in reqs:
            safe_remove_upload(req.video_filename)
            db.session.delete(req)

        # Nullify reviewer references
        VerificationRequest.query.filter_by(reviewed_by=target_user.id).update(
            {'reviewed_by': None}, synchronize_session=False
        )

        # Shares (sent/received)
        Share.query.filter(
            (Share.sender_id == target_user.id) | (Share.receiver_id == target_user.id)
        ).delete(synchronize_session=False)

        # Reports created by user
        Report.query.filter_by(reporter_id=target_user.id).delete(synchronize_session=False)
        # User blocks created by or targeting user
        UserBlock.query.filter(
            (UserBlock.blocker_id == target_user.id) | (UserBlock.blocked_id == target_user.id)
        ).delete(synchronize_session=False)

        # Chat rooms created by user (remove attachments)
        rooms = ChatRoom.query.filter_by(created_by=target_user.id).all()
        room_ids = [room.id for room in rooms]
        for room in rooms:
            if room.image_filename:
                safe_remove_upload(room.image_filename)
            for msg in room.messages:
                if msg.attachment_filename:
                    safe_remove_upload(msg.attachment_filename)
            db.session.delete(room)

        # Messages by user outside removed rooms
        msg_query = ChatMessage.query.filter(ChatMessage.user_id == target_user.id)
        if room_ids:
            msg_query = msg_query.filter(~ChatMessage.room_id.in_(room_ids))
        messages = msg_query.all()
        for msg in messages:
            if msg.attachment_filename:
                safe_remove_upload(msg.attachment_filename)
            db.session.delete(msg)

        # Clean deleted_by references
        ChatMessage.query.filter(ChatMessage.deleted_by == target_user.id).update(
            {'deleted_by': None}, synchronize_session=False
        )

        # Remove chat participations
        ChatParticipant.query.filter_by(user_id=target_user.id).delete(synchronize_session=False)

        # Posts + images
        posts = Post.query.filter_by(user_id=target_user.id).all()
        post_ids = [post.id for post in posts]
        if post_ids:
            Share.query.filter(Share.post_id.in_(post_ids)).delete(synchronize_session=False)
            Report.query.filter(Report.post_id.in_(post_ids)).delete(synchronize_session=False)
            db.session.execute(post_tag.delete().where(post_tag.c.post_id.in_(post_ids)))
        for post in posts:
            if post.image_filename:
                safe_remove_upload(post.image_filename)
            db.session.delete(post)

        # Profile picture
        safe_remove_upload(target_user.profile_pic)

        # Finally delete user
        db.session.delete(target_user)

    @app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
    @login_required
    def admin_delete_user(user_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        user = User.query.get_or_404(user_id)
        if user.username == 'admin':
            return jsonify({'error': 'No puedes eliminar al administrador'}), 400

        try:
            delete_user_and_related(user)
            db.session.commit()
            return jsonify({'success': True, 'message': f'Usuaria {user.username} eliminada'})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_delete_user error:', e)
            return jsonify({'error': 'No se pudo eliminar la usuaria'}), 500

    @app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
    @login_required
    def admin_delete_post(post_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        post = Post.query.get_or_404(post_id)
        db.session.delete(post)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Publicación eliminada'})

    @app.route('/admin/restore_post/<int:post_id>', methods=['POST'])
    @login_required
    def admin_restore_post(post_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        meta = PostMeta.query.filter_by(post_id=post_id).first()
        if not meta:
            return jsonify({'error': 'No hay reporte para restaurar'}), 404

        meta.show_public = True
        db.session.add(meta)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Publicación restaurada'})

    @app.route('/admin/update_post_location/<int:post_id>', methods=['POST'])
    @login_required
    def admin_update_post_location(post_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        post = Post.query.get_or_404(post_id)
        payload = request.get_json(silent=True) or request.form

        lat = parse_float(payload.get('latitude'))
        lng = parse_float(payload.get('longitude'))
        if not valid_coords(lat, lng):
            return jsonify({'error': 'Coordenadas inválidas'}), 400

        location_name = (payload.get('location_name') or payload.get('address') or '').strip()
        city = (payload.get('city') or '').strip()
        country = (payload.get('country') or '').strip()

        post.latitude = lat
        post.longitude = lng
        post.location_name = location_name or post.location_name
        post.city = city or post.city
        post.country = country or post.country

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_update_post_location error:', exc)
            return jsonify({'error': 'No se pudo actualizar la ubicación'}), 500

        return jsonify({
            'success': True,
            'message': 'Ubicación actualizada',
            'post_id': post.id,
            'latitude': post.latitude,
            'longitude': post.longitude,
            'location_name': post.location_name
        })

    @app.route('/admin/change_username/<int:user_id>', methods=['POST'])
    @login_required
    def admin_change_username(user_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        user = User.query.get_or_404(user_id)
        new_username = request.form.get('new_username', '').strip()

        if not new_username:
            return jsonify({'error': 'Nombre de usuaria requerido'}), 400

        # Check if username already exists
        existing = User.query.filter_by(username=new_username).first()
        if existing and existing.id != user_id:
            return jsonify({'error': 'El nombre de usuaria ya existe'}), 400

        user.username = new_username
        db.session.commit()
        return jsonify({'success': True, 'message': f'Nombre de usuaria cambiado a {new_username}'})

    @app.route('/admin/change_user_photo/<int:user_id>', methods=['POST'])
    @login_required
    def admin_change_user_photo(user_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        user = User.query.get_or_404(user_id)

        bio = (request.form.get('bio') or '').strip()
        file = request.files.get('photo')

        if not file or file.filename == '':
            if bio == '':
                return jsonify({'error': 'No se seleccionó archivo'}), 400
            user.bio = bio
            db.session.commit()
            return jsonify({'success': True, 'message': 'Descripción actualizada'})

        # Defense-in-depth: normalize and validate filename again.
        photo_filename = (file.filename or '').strip()
        if not photo_filename:
            return jsonify({'error': 'No se seleccionó archivo'}), 400

        if file and allowed_file(photo_filename):
            filename = secure_filename(photo_filename)
            unique_filename = str(uuid4()) + '.' + filename.rsplit('.', 1)[1].lower()
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)

            user.profile_pic = unique_filename
            if bio != '':
                user.bio = bio
            db.session.commit()
            return jsonify({'success': True, 'message': 'Foto de perfil actualizada', 'photo_url': url_for('uploaded_file', filename=unique_filename)})
        else:
            return jsonify({'error': 'Tipo de archivo no permitido'}), 400

    @app.route('/admin/approve_chat_room/<int:room_id>', methods=['POST'])
    @login_required
    def admin_approve_chat_room(room_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        room = ChatRoom.query.get_or_404(room_id)
        room.is_approved = True
        db.session.commit()
        return jsonify({'success': True})

    @app.route('/admin/delete_chat_room/<int:room_id>', methods=['POST'])
    @login_required
    def admin_delete_chat_room(room_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        room = ChatRoom.query.get_or_404(room_id)
        db.session.delete(room)
        db.session.commit()
        return jsonify({'success': True})

    @app.route('/admin/clear_chat_room/<int:room_id>', methods=['POST'])
    @login_required
    def admin_clear_chat_room(room_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        room = ChatRoom.query.get_or_404(room_id)
        upload_folder = ensure_upload_folder()

        try:
            messages = ChatMessage.query.filter_by(room_id=room_id).all()
            for msg in messages:
                filename = getattr(msg, 'attachment_filename', None)
                if filename:
                    file_path = os.path.join(upload_folder, filename)
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except Exception as exc:
                        _debug_log_suppressed('suppressed exception', exc)
            ChatMessage.query.filter_by(room_id=room_id).delete(synchronize_session=False)
            db.session.commit()

            try:
                socketio.emit('room_cleared', {'room_id': room.id}, room=f'room_{room.id}')
            except Exception as e:
                if app.debug:
                    print('DEBUG room_cleared emit error:', e)

            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_clear_chat_room error:', e)
            return jsonify({'error': 'No se pudo vaciar el chat'}), 500

    @app.route('/api/chat/message/<int:message_id>/delete', methods=['POST'])
    @login_required
    def api_chat_delete_message(message_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        try:
            message = ChatMessage.query.get_or_404(message_id)
            room = ChatRoom.query.get_or_404(message.room_id)

            is_admin = current_user.username == 'admin'
            is_owner = room.created_by == current_user.id
            is_sender = message.user_id == current_user.id

            if message.user.username == 'admin' and not is_admin:
                return jsonify({'error': 'No tienes permiso para eliminar mensajes del admin'}), 403

            allowed = False
            if is_admin:
                allowed = True
            elif is_owner:
                allowed = True
            elif is_sender and message.created_at:
                allowed = (utc_now_naive() - message.created_at) <= timedelta(minutes=10)

            if not allowed:
                return jsonify({'error': 'No tienes permiso para eliminar este mensaje'}), 403

            if getattr(message, 'is_deleted', False):
                return jsonify({'success': True})

            upload_folder = ensure_upload_folder()
            if message.attachment_filename:
                file_path = os.path.join(upload_folder, message.attachment_filename)
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
            message.content = ''
            message.is_deleted = True
            message.deleted_at = utc_now_naive()
            message.deleted_by = current_user.id
            message.attachment_filename = None
            message.attachment_name = None
            message.attachment_mime = None
            db.session.commit()

            try:
                socketio.emit('message_deleted', {
                    'room_id': room.id,
                    'message_id': message.id
                }, room=f'room_{room.id}')
            except Exception as e:
                if app.debug:
                    print('DEBUG message_deleted emit error:', e)

            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_chat_delete_message error:', e)
            return jsonify({'error': 'No se pudo eliminar el mensaje'}), 500

    @app.route('/admin/bulk_delete_users', methods=['POST'])
    @login_required
    def admin_bulk_delete_users():
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        data = request.get_json() or {}
        ids = data.get('ids') or []
        deleted = 0
        try:
            for uid in ids:
                user = User.query.get(uid)
                if not user or user.username == 'admin':
                    continue
                delete_user_and_related(user)
                deleted += 1
            db.session.commit()
            return jsonify({'success': True, 'deleted': deleted})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_bulk_delete_users error:', e)
            return jsonify({'error': 'No se pudieron eliminar usuarias'}), 500

    @app.route('/admin/bulk_delete_posts', methods=['POST'])
    @login_required
    def admin_bulk_delete_posts():
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        data = request.get_json() or {}
        ids = data.get('ids') or []
        deleted = 0
        for pid in ids:
            post = Post.query.get(pid)
            if not post:
                continue
            db.session.delete(post)
            deleted += 1
        db.session.commit()
        return jsonify({'success': True, 'deleted': deleted})

    @app.route('/admin/bulk_restore_posts', methods=['POST'])
    @login_required
    def admin_bulk_restore_posts():
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        data = request.get_json() or {}
        ids = data.get('ids') or []
        restored = 0
        for pid in ids:
            post = Post.query.get(pid)
            if not post:
                continue
            if not post.meta:
                post.meta = PostMeta(post_id=post.id)
            post.meta.show_public = True
            restored += 1
        db.session.commit()
        return jsonify({'success': True, 'restored': restored})

    @app.route('/admin/bulk_delete_chat_rooms', methods=['POST'])
    @login_required
    def admin_bulk_delete_chat_rooms():
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        data = request.get_json() or {}
        ids = data.get('ids') or []
        deleted = 0
        for rid in ids:
            room = ChatRoom.query.get(rid)
            if not room:
                continue
            db.session.delete(room)
            deleted += 1
        db.session.commit()
        return jsonify({'success': True, 'deleted': deleted})

    @app.route('/admin/report_details/<int:post_id>')
    @login_required
    def admin_report_details(post_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403
        post = Post.query.get_or_404(post_id)
        author = post.author
        author_pic = url_for('static', filename='images/default_avatar.jpg')
        if author and author.profile_pic and author.profile_pic != 'default.jpg':
            author_pic = url_for('uploaded_file', filename=author.profile_pic)

        image_url = url_for('uploaded_file', filename=post.image_filename)
        likes_count = post.get_likes_count()
        comments_count = post.get_comments_count()

        comments = []
        for c in post.comments:
            comments.append({
                'username': c.author.username if c.author else 'unknown',
                'content': c.content,
                'created_at': c.created_at.isoformat() if c.created_at else None,
            })

        reports = []
        for r in post.reports:
            reports.append({
                'id': r.id,
                'reason': r.reason,
                'details': r.details or '',
                'reporter': r.reporter.username if r.reporter else 'unknown',
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'status': r.status or 'pending',
                'admin_note': r.admin_note or '',
                'resolved_at': r.resolved_at.isoformat() if r.resolved_at else None,
                'resolved_by': r.resolver.username if getattr(r, 'resolver', None) else None,
            })

        return jsonify({
            'post': {
                'id': post.id,
                'image_url': image_url,
                'caption': post.caption or '',
                'created_at': post.created_at.isoformat() if post.created_at else None,
                'author': {
                    'username': author.username if author else 'unknown',
                    'profile_pic': author_pic
                },
                'location': {
                    'name': post.location_name or '',
                    'city': post.city or '',
                    'country': post.country or '',
                    'lat': post.latitude,
                    'lng': post.longitude
                },
                'likes_count': likes_count,
                'comments_count': comments_count
            },
            'comments': comments,
            'reports': reports
        })

    @app.route('/admin/report/<int:report_id>/status', methods=['POST'])
    @login_required
    def admin_update_report_status(report_id):
        if current_user.username != 'admin':
            return jsonify({'error': 'Acceso denegado'}), 403

        data = request.get_json(silent=True) or request.form or {}
        status = (data.get('status') or '').strip().lower()
        admin_note = (data.get('admin_note') or '').strip()
        allowed = {'pending', 'reviewing', 'resolved', 'dismissed'}
        if status not in allowed:
            return jsonify({'error': 'Estado inválido'}), 400

        report = Report.query.get_or_404(report_id)
        report.status = status
        report.admin_note = admin_note or None

        if status in {'resolved', 'dismissed'}:
            report.resolved_at = datetime.now()
            report.resolved_by = current_user.id
        else:
            report.resolved_at = None
            report.resolved_by = None

        db.session.add(report)
        db.session.commit()
        return jsonify({'success': True, 'status': report.status})

    @app.route('/profile/edit', methods=['GET', 'POST'])
    @login_required
    def edit_profile():
        user = current_user
        error = None
        if request.method == 'POST':
            bio = (request.form.get('bio') or '').strip()
            # Limitar longitud para evitar textos enormes
            if len(bio) > 300:
                error = 'La biografía debe tener máximo 300 caracteres.'
            else:
                user.bio = bio

            file = request.files.get('profile_pic')
            b64data = (request.form.get('profile_pic_data') or '').strip()
            if file and getattr(file, 'filename', ''):
                # Defense-in-depth: normalize and validate filename again.
                profile_filename = (file.filename or '').strip()
                if not profile_filename:
                    error = 'Formato de imagen no permitido.'
                elif not allowed_file(profile_filename):
                    error = 'Formato de imagen no permitido.'
                else:
                    upload_folder = ensure_upload_folder()
                    from werkzeug.utils import secure_filename as _sf
                    name = _sf(profile_filename)
                    _, ext = os.path.splitext(name)
                    ext = ext.lower()
                    unique_name = f"{uuid4().hex}{ext}"
                    save_path = os.path.join(upload_folder, unique_name)
                    old_pic = (user.profile_pic or '').strip()
                    try:
                        file.save(save_path)
                        user.profile_pic = unique_name
                        # Intentar eliminar la foto anterior si no es la por defecto
                        try:
                            if old_pic and old_pic.lower() != 'default.jpg':
                                old_path = os.path.join(upload_folder, old_pic)
                                if os.path.exists(old_path):
                                    os.remove(old_path)
                        except Exception as exc:
                            _debug_log_suppressed('suppressed exception', exc)
                    except Exception:
                        error = 'No se pudo guardar la foto de perfil.'
            elif b64data.startswith('data:image/'):
                # Guardar desde base64 (fallback para navegadores que bloquean File API programática)
                try:
                    import base64
                    upload_folder = ensure_upload_folder()
                    # Detectar extensión simple
                    mime = b64data.split(';')[0].split(':')[1]
                    ext = '.jpg'
                    if 'png' in mime:
                        ext = '.png'
                    elif 'webp' in mime:
                        ext = '.webp'
                    unique_name = f"{uuid4().hex}{ext}"
                    data_part = b64data.split(',')[1]
                    raw = base64.b64decode(data_part)
                    save_path = os.path.join(upload_folder, unique_name)
                    with open(save_path, 'wb') as f:
                        f.write(raw)
                    old_pic = (user.profile_pic or '').strip()
                    user.profile_pic = unique_name
                    try:
                        if old_pic and old_pic.lower() != 'default.jpg':
                            old_path = os.path.join(upload_folder, old_pic)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                    except Exception as exc:
                        _debug_log_suppressed('suppressed exception', exc)
                except Exception:
                    error = 'No se pudo procesar la imagen recortada.'

            if not error:
                try:
                    db.session.add(user)
                    db.session.commit()
                    flash('Foto de perfil actualizada', 'success')
                    return redirect(url_for('user_profile', username=user.username))
                except Exception:
                    db.session.rollback()
                    error = 'No se pudo guardar el perfil.'

        return render_template('profile_edit.html', user=user, error=error)

    @app.route('/api/profile/avatar', methods=['POST'])
    @login_required
    def api_profile_avatar():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Actualiza el avatar del usuario autenticado vía fetch(FormData).

        Acepta:
          - files['image'] (Blob/archivo recortado)
          - form['image_b64'] o form['profile_pic_data'] (dataURL base64)

        Responde JSON: { ok: true, url: <nuevo_url> }
        """
        user = current_user
        upload_folder = ensure_upload_folder()

        import base64
        file = request.files.get('image')
        b64 = request.form.get('image_b64') or request.form.get('profile_pic_data') or ''

        max_avatar_bytes = 8 * 1024 * 1024
        new_name = None
        try:
            if file and getattr(file, 'filename', ''):
                # Defense-in-depth: normalize and validate filename again.
                avatar_filename = (file.filename or '').strip()
                if not avatar_filename or not allowed_file(avatar_filename):
                    return jsonify({'ok': False, 'error': 'Formato de imagen no permitido.'}), 400

                # Guardar desde archivo
                name = secure_filename(avatar_filename)
                _, ext = os.path.splitext(name)
                ext = ext.lower() or '.jpg'
                new_name = f"{uuid4().hex}{ext}"
                file.save(os.path.join(upload_folder, new_name))
            elif b64.startswith('data:image/'):
                # Guardar desde base64
                mime = b64.split(';')[0].split(':')[1]
                ext = '.jpg'
                if 'png' in mime:
                    ext = '.png'
                elif 'webp' in mime:
                    ext = '.webp'
                elif 'jpeg' in mime or 'jpg' in mime:
                    ext = '.jpg'
                else:
                    return jsonify({'ok': False, 'error': 'Formato de imagen no permitido.'}), 400

                new_name = f"{uuid4().hex}{ext}"
                data_part = b64.split(',')[1]
                raw = base64.b64decode(data_part)
                if len(raw) > max_avatar_bytes:
                    return jsonify({'ok': False, 'error': 'La imagen excede el tamaño permitido.'}), 400
                with open(os.path.join(upload_folder, new_name), 'wb') as f:
                    f.write(raw)
            else:
                return jsonify({'ok': False, 'error': 'Imagen inválida'}), 400

            # Borrar anterior si aplica
            old = (user.profile_pic or '').strip()
            user.profile_pic = new_name
            db.session.add(user)
            db.session.commit()

            try:
                if old and old.lower() != 'default.jpg':
                    old_path = os.path.join(upload_folder, old)
                    if os.path.exists(old_path):
                        os.remove(old_path)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            url = url_for('uploaded_file', filename=new_name)
            return jsonify({'ok': True, 'url': url})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG avatar api error:', e)
            return jsonify({'ok': False, 'error': 'No se pudo actualizar el avatar.'}), 500

    @app.route('/user/<username>')
    def user_profile(username):
        user = User.query.filter_by(username=username).first_or_404()
        if current_user.is_authenticated and current_user.id != user.id and is_user_blocked_between(current_user.id, user.id):
            abort(404)
        user_posts = sorted(user.posts, key=lambda p: p.created_at or 0, reverse=True)
        now = datetime.now()
        for p in user_posts:
            p.can_delete = bool(p.created_at and (now - p.created_at) <= timedelta(hours=1))
            p.is_pending = bool(getattr(p, 'publish_at', None) and getattr(p, 'publish_at') > now)
        is_self = (current_user.is_authenticated and current_user.id == user.id)
        if not is_self and (not current_user.is_authenticated or current_user.username != 'admin'):
            user_posts = [p for p in user_posts if is_public_post(p)]
        report_count = len(user_posts)
        total_likes = sum((p.get_likes_count() for p in user_posts), 0)
        total_comments = sum((p.get_comments_count() for p in user_posts), 0)
        return render_template(
            'user_profile.html',
            user=user,
            posts=user_posts,
            report_count=report_count,
            total_likes=total_likes,
            total_comments=total_comments,
            is_self=is_self
        )

    @app.route('/api/user/block/<int:target_user_id>', methods=['POST'])
    @login_required
    def api_block_user(target_user_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403

        target = User.query.get_or_404(target_user_id)
        if target.id == current_user.id:
            return jsonify({'error': 'No puedes bloquearte a ti misma.'}), 400
        if target.username == 'admin':
            return jsonify({'error': 'No puedes bloquear esta cuenta.'}), 400

        relation = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=target.id).first()
        if not relation:
            relation = UserBlock(blocker_id=current_user.id, blocked_id=target.id, is_muted=False)
            db.session.add(relation)

        db.session.commit()
        return jsonify({'ok': True, 'blocked': True})

    @app.route('/api/user/unblock/<int:target_user_id>', methods=['POST'])
    @login_required
    def api_unblock_user(target_user_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403

        relation = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=target_user_id).first()
        if relation:
            db.session.delete(relation)
            db.session.commit()
        return jsonify({'ok': True, 'blocked': False})

    @app.route('/api/user/mute/<int:target_user_id>', methods=['POST'])
    @login_required
    def api_mute_user(target_user_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403

        target = User.query.get_or_404(target_user_id)
        if target.id == current_user.id:
            return jsonify({'error': 'No puedes silenciarte a ti misma.'}), 400
        if target.username == 'admin':
            return jsonify({'error': 'No puedes silenciar esta cuenta.'}), 400

        relation = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=target.id).first()
        if not relation:
            relation = UserBlock(blocker_id=current_user.id, blocked_id=target.id, is_muted=True)
            db.session.add(relation)
        else:
            relation.is_muted = True
            db.session.add(relation)

        db.session.commit()
        return jsonify({'ok': True, 'muted': True})

    @app.route('/api/user/unmute/<int:target_user_id>', methods=['POST'])
    @login_required
    def api_unmute_user(target_user_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403

        relation = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=target_user_id).first()
        if relation:
            relation.is_muted = False
            db.session.add(relation)
            db.session.commit()
        return jsonify({'ok': True, 'muted': False})

    @app.route('/api/user/safety-state/<int:target_user_id>')
    @login_required
    def api_user_safety_state(target_user_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        relation = UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=target_user_id).first()
        return jsonify({
            'blocked': bool(relation),
            'muted': bool(relation.is_muted) if relation else False,
        })

    @app.route('/safety')
    @login_required
    def safety_center():
        if current_user.is_authenticated and not is_user_verified(current_user):
            flash(VERIFY_REQUIRED_MSG, 'info')
            return redirect(url_for('verify_identity'))
        process_overdue_checkins(current_user.id)
        blocked_rows = UserBlock.query.filter_by(blocker_id=current_user.id).order_by(UserBlock.created_at.desc()).all()
        blocked_users = []
        for row in blocked_rows:
            u = row.blocked
            if not u:
                continue
            blocked_users.append({
                'id': u.id,
                'username': u.username,
                'profile_pic': url_for('uploaded_file', filename=u.profile_pic) if u.profile_pic and u.profile_pic != 'default.jpg' else url_for('static', filename='images/default_avatar.jpg'),
                'is_muted': bool(row.is_muted),
            })

        contacts = SafetyContact.query.filter_by(user_id=current_user.id).order_by(SafetyContact.is_primary.desc(), SafetyContact.created_at.desc()).all()
        active_checkin = SafetyCheckin.query.filter_by(user_id=current_user.id, status='active').order_by(SafetyCheckin.started_at.desc()).first()

        # Historial de trayectos finalizados (arrived). Numeración por orden de llegada.
        arrived_all = SafetyCheckin.query.filter_by(user_id=current_user.id, status='arrived').order_by(
            SafetyCheckin.arrived_at.asc(),
            SafetyCheckin.id.asc(),
        ).all()
        seq_map = {c.id: idx + 1 for idx, c in enumerate(arrived_all)}
        arrived_recent = list(reversed(arrived_all))[:30]
        trip_items = []
        for c in arrived_recent:
            n = seq_map.get(c.id, 1)
            default_title = f"Trayecto {n}"
            raw_title = (getattr(c, 'title', None) or '').strip()
            display_title = raw_title or default_title
            when_dt = c.arrived_at or c.started_at or c.expires_at
            trip_items.append({
                'id': c.id,
                'title': raw_title,
                'default_title': default_title,
                'display_title': display_title,
                'destination': c.destination or '',
                'when_dt': when_dt,
                'summary_url': url_for('checkin_summary', checkin_id=c.id),
            })
        return render_template(
            'safety.html',
            blocked_users=blocked_users,
            contacts=contacts,
            active_checkin=active_checkin,
            trip_items=trip_items,
        )

    @app.route('/safety/checkin/<int:checkin_id>/summary')
    @login_required
    def checkin_summary(checkin_id: int):
        if current_user.is_authenticated and not is_user_verified(current_user):
            flash(VERIFY_REQUIRED_MSG, 'info')
            return redirect(url_for('verify_identity'))
        checkin = SafetyCheckin.query.get_or_404(checkin_id)
        if current_user.username != 'admin' and checkin.user_id != current_user.id:
            abort(403)

        rows = CheckinRoutePoint.query.filter_by(checkin_id=checkin.id).order_by(
            CheckinRoutePoint.recorded_at.asc(),
            CheckinRoutePoint.id.asc(),
        ).all()

        points = []
        for r in rows:
            dt = r.recorded_at or r.created_at or utc_now_naive()
            points.append({
                'lat': float(r.latitude),
                'lng': float(r.longitude),
                'ts': dt,  # naive UTC
            })

        def haversine_m(lat1, lon1, lat2, lon2) -> float:
            R = 6371000.0
            d_lat = radians(lat2 - lat1)
            d_lon = radians(lon2 - lon1)
            a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
            c = 2 * asin(sqrt(a))
            return R * c

        total_m = 0.0
        max_speed_kmh = 0.0
        duration_sec = 0.0
        segments = []

        if len(points) >= 2:
            start_ts = points[0]['ts']
            end_ts = points[-1]['ts']
            duration_sec = max(0.0, (end_ts - start_ts).total_seconds())

            prev = points[0]
            segment_window_sec = 60
            seg_idx = 0
            seg_start_ts = start_ts
            seg_dist_m = 0.0
            seg_first_ts = start_ts
            seg_last_ts = start_ts

            for curr in points[1:]:
                dt_s = (curr['ts'] - prev['ts']).total_seconds()
                if dt_s <= 0:
                    prev = curr
                    continue

                d_m = haversine_m(prev['lat'], prev['lng'], curr['lat'], curr['lng'])
                total_m += d_m

                speed_kmh = (d_m / dt_s) * 3.6
                if speed_kmh > max_speed_kmh:
                    max_speed_kmh = speed_kmh

                # Segmentación por ventanas de tiempo (aprox. 1 min)
                if (prev['ts'] - seg_start_ts).total_seconds() >= segment_window_sec:
                    seg_dur = max(0.0, (seg_last_ts - seg_first_ts).total_seconds())
                    if seg_dur > 0:
                        segments.append({
                            'idx': seg_idx + 1,
                            'start_ts': seg_first_ts,
                            'end_ts': seg_last_ts,
                            'distance_km': seg_dist_m / 1000.0,
                            'speed_kmh': (seg_dist_m / seg_dur) * 3.6,
                        })
                    seg_idx += 1
                    seg_start_ts = prev['ts']
                    seg_dist_m = 0.0
                    seg_first_ts = prev['ts']

                seg_dist_m += d_m
                seg_last_ts = curr['ts']
                prev = curr

            # cerrar último segmento
            seg_dur = max(0.0, (seg_last_ts - seg_first_ts).total_seconds())
            if seg_dur > 0 and seg_dist_m > 0:
                segments.append({
                    'idx': seg_idx + 1,
                    'start_ts': seg_first_ts,
                    'end_ts': seg_last_ts,
                    'distance_km': seg_dist_m / 1000.0,
                    'speed_kmh': (seg_dist_m / seg_dur) * 3.6,
                })

        distance_km = total_m / 1000.0
        avg_speed_kmh = (distance_km / (duration_sec / 3600.0)) if duration_sec > 0 else 0.0

        points_payload = []
        for p in points:
            ts_ms = int(p['ts'].replace(tzinfo=timezone.utc).timestamp() * 1000)
            points_payload.append([p['lat'], p['lng'], ts_ms])

        return render_template(
            'checkin_summary.html',
            checkin=checkin,
            route_points=points_payload,
            stats={
                'distance_km': distance_km,
                'duration_sec': duration_sec,
                'avg_speed_kmh': avg_speed_kmh,
                'max_speed_kmh': max_speed_kmh,
            },
            segments=segments,
        )

    @app.route('/emergency')
    def emergency_call():
        contacts_count = 0
        if current_user.is_authenticated:
            contacts_count = SafetyContact.query.filter_by(user_id=current_user.id).count()
        return render_template(
            'emergency.html',
            emergency_number='8125898477',
            contacts_count=contacts_count,
        )

    @app.route('/api/safety/emergency/trigger', methods=['POST'])
    def api_emergency_trigger():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403

        payload = request.get_json(silent=True) or request.form or {}
        lat = parse_float(payload.get('lat'))
        lng = parse_float(payload.get('lng'))
        emergency_number = '8125898477'

        user_label = 'Una usuaria de Violeta'
        contacts = []
        if current_user.is_authenticated:
            user_label = f"@{current_user.username}"
            contacts = SafetyContact.query.filter_by(user_id=current_user.id).order_by(
                SafetyContact.is_primary.desc(),
                SafetyContact.created_at.asc()
            ).all()

        sms_body, maps_url = build_emergency_message(user_label, lat, lng)

        sent_count = 0
        for contact in contacts:
            if send_sms_via_twilio(contact.phone, sms_body):
                sent_count += 1

        if current_user.is_authenticated and contacts:
            primary = contacts[0]
            event = PanicEvent(
                user_id=current_user.id,
                contact_name=primary.name,
                contact_phone=primary.phone,
                latitude=lat,
                longitude=lng,
                note='Activación rápida desde botón 911',
                status='open',
            )
            db.session.add(event)
            db.session.commit()

        return jsonify({
            'ok': True,
            'emergency_number': emergency_number,
            'contacts_total': len(contacts),
            'contacts_notified': sent_count,
            'maps_url': maps_url,
            'sms_auto_enabled': sent_count > 0,
            'message': 'Protocolo de emergencia activado.',
        })

    @app.route('/api/safety/contact', methods=['POST'])
    @login_required
    def api_add_safety_contact():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        payload = request.get_json(silent=True) or request.form or {}
        name = (payload.get('name') or '').strip()
        relationship = (payload.get('relationship') or '').strip()
        phone = normalize_phone_simple(payload.get('phone'))

        if len(name) < 2:
            return jsonify({'ok': False, 'error': 'Nombre inválido'}), 400
        if not phone:
            return jsonify({'ok': False, 'error': 'Teléfono inválido. Usa un número real.'}), 400

        existing = SafetyContact.query.filter_by(user_id=current_user.id, phone=phone).first()
        if existing:
            return jsonify({'ok': False, 'error': 'Ese contacto ya existe'}), 400

        is_primary = SafetyContact.query.filter_by(user_id=current_user.id).count() == 0
        contact = SafetyContact(
            user_id=current_user.id,
            name=name,
            phone=phone,
            relationship=relationship or None,
            is_primary=is_primary,
        )
        db.session.add(contact)
        db.session.commit()
        return jsonify({'ok': True, 'contact_id': contact.id})

    @app.route('/api/safety/contact/<int:contact_id>/delete', methods=['POST'])
    @login_required
    def api_delete_safety_contact(contact_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        contact = SafetyContact.query.get_or_404(contact_id)
        if contact.user_id != current_user.id and current_user.username != 'admin':
            return jsonify({'ok': False, 'error': 'Acceso denegado'}), 403
        was_primary = bool(contact.is_primary)
        owner_id = contact.user_id
        db.session.delete(contact)
        db.session.commit()

        if was_primary:
            nxt = SafetyContact.query.filter_by(user_id=owner_id).order_by(SafetyContact.created_at.asc()).first()
            if nxt:
                nxt.is_primary = True
                db.session.add(nxt)
                db.session.commit()

        return jsonify({'ok': True})

    @app.route('/api/safety/contact/<int:contact_id>/primary', methods=['POST'])
    @login_required
    def api_set_primary_safety_contact(contact_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        contact = SafetyContact.query.get_or_404(contact_id)
        if contact.user_id != current_user.id:
            return jsonify({'ok': False, 'error': 'Acceso denegado'}), 403

        SafetyContact.query.filter_by(user_id=current_user.id).update({'is_primary': False}, synchronize_session=False)
        contact.is_primary = True
        db.session.add(contact)
        db.session.commit()
        return jsonify({'ok': True})

    @app.route('/api/safety/checkin/start', methods=['POST'])
    @login_required
    def api_start_checkin():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        payload = request.get_json(silent=True) or request.form or {}
        try:
            eta_minutes = int(payload.get('eta_minutes') or 30)
        except (TypeError, ValueError):
            eta_minutes = 30
        eta_minutes = max(5, min(180, eta_minutes))

        destination = (payload.get('destination') or '').strip()[:180]
        note = (payload.get('note') or '').strip()[:255]
        lat = parse_float(payload.get('lat'))
        lng = parse_float(payload.get('lng'))

        primary = SafetyContact.query.filter_by(user_id=current_user.id, is_primary=True).first()
        if not primary:
            primary = SafetyContact.query.filter_by(user_id=current_user.id).order_by(SafetyContact.created_at.asc()).first()
        if not primary:
            return jsonify({'ok': False, 'error': 'Primero agrega un contacto de confianza.'}), 400

        active_rows = SafetyCheckin.query.filter_by(user_id=current_user.id, status='active').all()
        now = datetime.now()
        for row in active_rows:
            row.status = 'cancelled'
            row.cancelled_at = now
            db.session.add(row)

        expires_at = now + timedelta(minutes=eta_minutes)
        checkin = SafetyCheckin(
            user_id=current_user.id,
            contact_name=primary.name,
            contact_phone=primary.phone,
            destination=destination or None,
            note=note or None,
            eta_minutes=eta_minutes,
            latitude=lat,
            longitude=lng,
            expires_at=expires_at,
            status='active',
        )
        db.session.add(checkin)
        db.session.commit()

        return jsonify({
            'ok': True,
            'checkin_id': checkin.id,
            'expires_at': checkin.expires_at.isoformat() if checkin.expires_at else None,
            'message': f'Check-in iniciado por {eta_minutes} minutos.',
        })

    @app.route('/api/safety/checkin/arrived', methods=['POST'])
    @login_required
    def api_arrived_checkin():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        checkin = SafetyCheckin.query.filter_by(user_id=current_user.id, status='active').order_by(SafetyCheckin.started_at.desc()).first()
        if not checkin:
            return jsonify({'ok': False, 'error': 'No hay un check-in activo.'}), 400

        # Set default title on arrival if empty: "Trayecto N"
        try:
            raw_title = (getattr(checkin, 'title', None) or '').strip()
        except Exception:
            raw_title = ''
        if not raw_title:
            prev_arrived = SafetyCheckin.query.filter_by(user_id=current_user.id, status='arrived').count()
            try:
                checkin.title = f"Trayecto {prev_arrived + 1}"
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        checkin.status = 'arrived'
        checkin.arrived_at = datetime.now()
        db.session.add(checkin)
        db.session.commit()
        return jsonify({
            'ok': True,
            'checkin_id': checkin.id,
            'summary_url': url_for('checkin_summary', checkin_id=checkin.id),
            'message': 'Check-in cerrado. Marcado como llegada segura.',
        })

    @app.route('/api/safety/checkin/cancel', methods=['POST'])
    @login_required
    def api_cancel_checkin():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        checkin = SafetyCheckin.query.filter_by(user_id=current_user.id, status='active').order_by(SafetyCheckin.started_at.desc()).first()
        if not checkin:
            return jsonify({'ok': False, 'error': 'No hay un check-in activo.'}), 400

        checkin.status = 'cancelled'
        checkin.cancelled_at = datetime.now()
        db.session.add(checkin)
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Check-in cancelado.'})

    @app.route('/api/safety/checkin/<int:checkin_id>/title', methods=['POST'])
    @login_required
    def api_checkin_title(checkin_id: int):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        payload = request.get_json(silent=True) or request.form or {}
        title = (payload.get('title') or '').strip()
        if title and len(title) > 180:
            title = title[:180]

        checkin = SafetyCheckin.query.get_or_404(checkin_id)
        if current_user.username != 'admin' and checkin.user_id != current_user.id:
            return jsonify({'ok': False, 'error': 'Acceso denegado.'}), 403
        if checkin.status != 'arrived':
            return jsonify({'ok': False, 'error': 'Solo puedes renombrar trayectos finalizados.'}), 400

        checkin.title = title or None
        db.session.add(checkin)
        db.session.commit()
        return jsonify({'ok': True, 'title': checkin.title or ''})

    @app.route('/api/safety/checkin/<int:checkin_id>/route/point', methods=['POST'])
    @login_required
    def api_checkin_route_point(checkin_id: int):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        payload = request.get_json(silent=True) or request.form or {}
        lat = parse_float(payload.get('lat'))
        lng = parse_float(payload.get('lng'))
        ts_ms = payload.get('ts_ms') or payload.get('ts') or payload.get('timestamp')
        speed_kmh = parse_float(payload.get('speed_kmh'))
        accuracy_m = parse_float(payload.get('accuracy_m'))

        if lat is None or lng is None:
            return jsonify({'ok': False, 'error': 'Coordenadas inválidas.'}), 400

        checkin = SafetyCheckin.query.get_or_404(checkin_id)
        if current_user.username != 'admin' and checkin.user_id != current_user.id:
            return jsonify({'ok': False, 'error': 'Acceso denegado.'}), 403
        if checkin.status != 'active':
            return jsonify({'ok': False, 'error': 'El check-in ya no está activo.'}), 400

        recorded_at = None
        try:
            if ts_ms is not None and str(ts_ms).strip() != '':
                recorded_at = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            recorded_at = None
        if recorded_at is None:
            recorded_at = utc_now_naive()

        point = CheckinRoutePoint(
            checkin_id=checkin.id,
            recorded_at=recorded_at,
            latitude=float(lat),
            longitude=float(lng),
            speed_kmh=float(speed_kmh) if speed_kmh is not None else None,
            accuracy_m=float(accuracy_m) if accuracy_m is not None else None,
        )
        db.session.add(point)
        db.session.commit()
        return jsonify({'ok': True, 'point_id': point.id})

    @app.route('/api/safety/checkin/<int:checkin_id>/route/points')
    @login_required
    def api_checkin_route_points(checkin_id: int):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        checkin = SafetyCheckin.query.get_or_404(checkin_id)
        if current_user.username != 'admin' and checkin.user_id != current_user.id:
            return jsonify({'ok': False, 'error': 'Acceso denegado.'}), 403

        rows = CheckinRoutePoint.query.filter_by(checkin_id=checkin.id).order_by(
            CheckinRoutePoint.recorded_at.asc(),
            CheckinRoutePoint.id.asc(),
        ).all()

        points = []
        for r in rows:
            dt = r.recorded_at or r.created_at or utc_now_naive()
            ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
            points.append({
                'lat': r.latitude,
                'lng': r.longitude,
                'ts_ms': ts_ms,
                'speed_kmh': r.speed_kmh,
                'accuracy_m': r.accuracy_m,
            })

        return jsonify({
            'ok': True,
            'checkin': {
                'id': checkin.id,
                'status': checkin.status,
                'destination': checkin.destination,
            },
            'points': points,
        })

    @app.route('/admin/panic/<int:panic_id>/resolve', methods=['POST'])
    @login_required
    def admin_resolve_panic(panic_id):
        if current_user.username != 'admin':
            return jsonify({'ok': False, 'error': 'Acceso denegado'}), 403

        event = PanicEvent.query.get_or_404(panic_id)
        event.status = 'resolved'
        event.resolved_at = datetime.now()
        event.resolved_by = current_user.id
        db.session.add(event)
        db.session.commit()
        return jsonify({'ok': True})

    # CLI helper para inicializar DB
    @app.cli.command('init-db')
    def init_db():
        db.create_all()
        ensure_chatroom_schema()
        ensure_post_schema()
        ensure_postmeta_schema()
        ensure_report_schema()
        ensure_user_schema()
        ensure_userblock_schema()
        ensure_safety_schema()
        print('Base de datos inicializada')

    @app.cli.command('geocode-missing')
    def geocode_missing():
        """Rellena coordenadas aproximadas para posts sin GPS usando Nominatim.

        Uso (desde el directorio del proyecto):
            flask --app app:create_app geocode-missing

        Variables de entorno opcionales:
            NOMINATIM_USER_AGENT  -> User-Agent a usar en la petición
            GEOCODE_LIMIT         -> Máx. posts a procesar (def. 50)
            GEOCODE_SLEEP         -> Segundos de espera entre peticiones (def. 1.2)
        """
        import json
        import time
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        # Respeto básico a Nominatim (1 req/seg)
        limit = int(os.environ.get('GEOCODE_LIMIT', '50') or '50')
        sleep_sec = float(os.environ.get('GEOCODE_SLEEP', '1.2') or '1.2')
        ua = os.environ.get('NOMINATIM_USER_AGENT') or 'VioletaApp/1.0 (+contact@example.com)'

        # Cache simple en instance/
        try:
            os.makedirs(app.instance_path, exist_ok=True)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        cache_path = os.path.join(app.instance_path, 'geocode_cache.json')
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except Exception:
            cache = {}

        def cache_get(q: str):
            return cache.get(q.lower().strip())

        def cache_put(q: str, value):
            cache[q.lower().strip()] = value
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        def build_query_from_post(p: Post) -> str:
            parts = []
            if getattr(p, 'location_name', None):
                parts.append(p.location_name)
            if getattr(p, 'city', None):
                parts.append(p.city)
            if getattr(p, 'country', None):
                parts.append(p.country)
            return ', '.join([x for x in parts if x])

        def geocode(q: str):
            if not q:
                return None
            cached = cache_get(q)
            if cached:
                return cached
            params = {
                'format': 'json',
                'q': q,
                'addressdetails': 1,
                'limit': 1,
                'accept-language': 'es',
            }
            url = f"https://nominatim.openstreetmap.org/search?{urlencode(params)}"
            req = Request(url, headers={'User-Agent': ua})
            try:
                with urlopen(req, timeout=6) as resp:  # nosec B310
                    data = json.loads(resp.read().decode('utf-8'))
                    if isinstance(data, list) and data:
                        item = data[0]
                        result = {
                            'lat': item.get('lat'),
                            'lng': item.get('lon'),
                            'address': item.get('address') or {},
                            'display_name': item.get('display_name') or '',
                        }
                        cache_put(q, result)
                        return result
            except Exception as e:
                print('Geocode error:', e)
            # Guardar fallo para no reintentar en esta sesión
            cache_put(q, None)
            return None

        q = Post.query.filter((Post.latitude.is_(None)) | (Post.longitude.is_(None)))
        to_process = q.order_by(Post.created_at.desc()).limit(limit).all()
        if not to_process:
            print('No hay posts pendientes de geocodificar.')
            return

        print(f'Procesando hasta {len(to_process)} posts sin coordenadas…')
        updated = 0
        skipped = 0

        for i, p in enumerate(to_process, 1):
            query_str = build_query_from_post(p)
            if not query_str:
                print(f'[{i}] Post {p.id}: sin datos de ubicación (location_name/city/country). Omitido.')
                skipped += 1
                continue

            print(f'[{i}] Post {p.id}: buscando "{query_str}"…', end=' ')
            info = geocode(query_str)
            # Respetar rate limit de Nominatim
            time.sleep(sleep_sec)

            if not info or not info.get('lat') or not info.get('lng'):
                print('sin resultados')
                skipped += 1
                continue

            try:
                lat = float(info['lat'])
                lng = float(info['lng'])
            except Exception:
                print('resultado inválido')
                skipped += 1
                continue

            p.latitude = lat
            p.longitude = lng

            addr = info.get('address') or {}
            # Completar etiquetas si faltan
            if not p.location_name:
                street = addr.get('road') or addr.get('pedestrian') or addr.get('footway')
                town = addr.get('city') or addr.get('town') or addr.get('village')
                state = addr.get('state')
                parts = [x for x in [street, town, state] if x]
                name = ', '.join(parts) if parts else info.get('display_name')
                if name:
                    # Etiquetar como aproximada para distinguir en UI
                    if 'aprox' not in name.lower():
                        name = f"{name} (aprox.)"
                    p.location_name = name
            else:
                # Ya existía un nombre; marcarlo como aproximado sin perder el texto original
                if 'aprox' not in (p.location_name or '').lower():
                    p.location_name = f"{p.location_name} (aprox.)"
            if not p.city:
                p.city = addr.get('city') or addr.get('town') or addr.get('village')
            if not p.country:
                p.country = addr.get('country')

            try:
                db.session.add(p)
                db.session.commit()
                updated += 1
                print(f'OK -> ({lat:.6f}, {lng:.6f})')
            except Exception as e:
                db.session.rollback()
                print('error al guardar:', e)
                skipped += 1

        print(f'Listo. Posts actualizados: {updated}. Omitidos: {skipped}.')

    with app.app_context():
        try:
            db.create_all()
            ensure_chatroom_schema()
            ensure_post_schema()
            ensure_postmeta_schema()
            ensure_report_schema()
            ensure_user_schema()
            ensure_userblock_schema()
            ensure_safety_schema()
        except Exception as e:
            if app.debug:
                print('DEBUG startup schema error:', e)

    return app, socketio

# Expose app and socketio for Flask CLI and direct execution
app, socketio = create_app()

if __name__ == '__main__':
    # Puerto 8000 por defecto para evitar conflicto con 5000 (AirPlay)
    port = int(os.environ.get('PORT', 8000))
    with app.app_context():
        ensure_folder = app.config.get('UPLOAD_FOLDER')
        if not ensure_folder:
            ensure_folder = os.path.join(os.path.dirname(__file__), 'uploads')
            app.config['UPLOAD_FOLDER'] = ensure_folder
        os.makedirs(ensure_folder, exist_ok=True)
        db.create_all()
        ensure_chatroom_schema()
        ensure_post_schema()
        ensure_postmeta_schema()
        ensure_report_schema()
        ensure_user_schema()
        ensure_userblock_schema()
        ensure_safety_schema()
    # Ejecutar con SocketIO (si no hay eventlet/gevent, usa Werkzeug). 
    # allow_unsafe_werkzeug=True evita el warning en modo desarrollo
    socketio.run(
        app,
        host=os.environ.get('HOST', '127.0.0.1'),
        port=port,
        debug=app.config.get('DEBUG', False),
        allow_unsafe_werkzeug=bool(app.config.get('DEBUG', False)),
    )
