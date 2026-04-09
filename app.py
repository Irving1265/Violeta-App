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
from jinja2 import FileSystemBytecodeCache
from werkzeug.utils import secure_filename
from models import db, User, UserBlock, SafetyContact, PanicEvent, SafetyCheckin, CheckinRoutePoint, Post, Comment, Like, Share, Tag, PostMeta, ChatRoom, ChatParticipant, ChatMessage, ChatMessageReport, CommentReport, ModerationStrike, Report, VerificationRequest, AuditLog, post_tag
from sqlalchemy import or_, and_, text, func, inspect, insert
from sqlalchemy.orm import selectinload
from config import Config
from forms import LoginForm, RegisterForm, PostForm, CommentForm, ShareForm
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict, deque
import json
import csv
import io
import glob
import mimetypes
import smtplib
import base64
import hashlib
import re
from functools import wraps
try:
    import redis
except Exception:  # pragma: no cover - optional runtime dependency
    redis = None
from email.message import EmailMessage
import secrets
import threading
import time
from flask_mail import Mail, Message
from math import radians, cos, sin, asin, sqrt
from urllib.parse import urlencode, quote
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


def chat_message_deleted_reason(message: ChatMessage | None, reported_ids: set[int] | None = None) -> str | None:
    if not message or not getattr(message, 'is_deleted', False):
        return None
    if reported_ids is not None:
        return 'reported' if message.id in reported_ids else 'deleted'
    try:
        for report in getattr(message, 'reports', None) or []:
            if getattr(report, 'status', None) in ('reviewing', 'struck'):
                return 'reported'
        return 'deleted'
    except Exception:
        return 'deleted'

def get_request_ip() -> str:
    forwarded_for = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    real_ip = (request.headers.get('X-Real-IP') or '').strip()
    remote = (request.remote_addr or '').strip()
    return forwarded_for or real_ip or remote or 'unknown'


def get_request_user_agent() -> str:
    raw = (request.headers.get('User-Agent') or '').strip()
    if len(raw) > 255:
        return raw[:255]
    return raw


def serialize_audit_details(details) -> str | None:
    if details is None:
        return None
    payload = details
    if not isinstance(payload, (dict, list)):
        payload = {'value': str(payload)}
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        try:
            fallback = {'value': str(details)}
            return json.dumps(fallback, ensure_ascii=False, sort_keys=True)
        except Exception:
            return None


def record_audit_event(
    event_type: str,
    *,
    actor=None,
    target_user=None,
    workspace: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    route: str | None = None,
    method: str | None = None,
    summary: str | None = None,
    details=None,
) -> None:
    normalized_event = (event_type or '').strip().lower()
    if not normalized_event:
        return
    if normalized_event == 'workspace.view':
        actor_id = getattr(actor, 'id', None) or getattr(current_user, 'id', None)
        throttle_bucket = f"audit:view:{actor_id or 'anon'}:{(workspace or '').strip().lower() or 'workspace'}:{(route or request.path or '').strip() or '/'}"
        if is_rate_limited(throttle_bucket, limit=1, window_seconds=20):
            return
    actor_user = actor
    if actor_user is None and getattr(current_user, 'is_authenticated', False):
        actor_user = current_user
    values = {
        'actor_id': getattr(actor_user, 'id', None),
        'target_user_id': getattr(target_user, 'id', None) if target_user is not None else None,
        'event_type': normalized_event,
        'workspace': (workspace or '').strip().lower() or None,
        'resource_type': (resource_type or '').strip().lower() or None,
        'resource_id': int(resource_id) if resource_id is not None else None,
        'route': (route or request.path or '').strip()[:255] or None,
        'method': (method or request.method or '').strip().upper()[:10] or None,
        'ip_address': get_request_ip()[:64],
        'user_agent': get_request_user_agent(),
        'summary': (summary or '').strip()[:255] or None,
        'details': serialize_audit_details(details),
        'created_at': utc_now_naive(),
    }
    try:
        with db.engine.begin() as connection:
            connection.execute(insert(AuditLog.__table__).values(**values))
    except Exception as exc:
        _debug_log_suppressed('suppressed audit exception', exc)

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
    """Ensure user table has the columns required by access control and moderation."""
    try:
        engine = db.engine
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        if 'user' not in tables:
            return
        dialect = engine.dialect.name
        user_table = '"user"' if dialect == 'postgresql' else 'user'
        datetime_type = 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME'
        bool_true = 'TRUE' if dialect == 'postgresql' else '1'
        with engine.begin() as conn:
            cols = {col['name'] for col in inspector.get_columns('user')}
            if 'is_verified' not in cols:
                conn.execute(text(f"ALTER TABLE {user_table} ADD COLUMN is_verified BOOLEAN DEFAULT {bool_true}"))
            if 'abuse_strikes' not in cols:
                conn.execute(text(f"ALTER TABLE {user_table} ADD COLUMN abuse_strikes INTEGER DEFAULT 0"))
            if 'muted_until' not in cols:
                conn.execute(text(f"ALTER TABLE {user_table} ADD COLUMN muted_until {datetime_type}"))
            if 'last_abuse_at' not in cols:
                conn.execute(text(f"ALTER TABLE {user_table} ADD COLUMN last_abuse_at {datetime_type}"))
            if 'roles' not in cols:
                conn.execute(text(f"ALTER TABLE {user_table} ADD COLUMN roles TEXT"))
            conn.execute(text(f"UPDATE {user_table} SET is_verified = {bool_true} WHERE is_verified IS NULL"))
            conn.execute(text(f"UPDATE {user_table} SET abuse_strikes = 0 WHERE abuse_strikes IS NULL"))
            conn.execute(text(
                f"UPDATE {user_table} SET roles = 'super_admin' "
                "WHERE lower(username) = 'admin' AND (roles IS NULL OR trim(roles) = '')"
            ))
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
def ensure_moderation_schema():
    """Ensure moderation-related columns exist on already-created tables."""
    try:
        engine = db.engine
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        if not tables:
            return

        dialect = engine.dialect.name
        datetime_type = 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME'
        bool_default = 'FALSE' if dialect == 'postgresql' else '0'
        user_table = '"user"' if dialect == 'postgresql' else 'user'

        with engine.begin() as conn:
            if 'user' in tables:
                user_cols = {col['name'] for col in inspector.get_columns('user')}
                if 'abuse_strikes' not in user_cols:
                    conn.execute(text(f'ALTER TABLE {user_table} ADD COLUMN abuse_strikes INTEGER DEFAULT 0'))
                if 'muted_until' not in user_cols:
                    conn.execute(text(f'ALTER TABLE {user_table} ADD COLUMN muted_until {datetime_type}'))
                if 'last_abuse_at' not in user_cols:
                    conn.execute(text(f'ALTER TABLE {user_table} ADD COLUMN last_abuse_at {datetime_type}'))
                if 'permanently_banned_at' not in user_cols:
                    conn.execute(text(f'ALTER TABLE {user_table} ADD COLUMN permanently_banned_at {datetime_type}'))
                if 'permanent_ban_reason' not in user_cols:
                    conn.execute(text(f'ALTER TABLE {user_table} ADD COLUMN permanent_ban_reason VARCHAR(255)'))
                conn.execute(text(f'UPDATE {user_table} SET abuse_strikes = 0 WHERE abuse_strikes IS NULL'))

            if 'comment' in tables:
                comment_cols = {col['name'] for col in inspector.get_columns('comment')}
                if 'is_hidden' not in comment_cols:
                    conn.execute(text(f'ALTER TABLE comment ADD COLUMN is_hidden BOOLEAN DEFAULT {bool_default}'))
                if 'hidden_at' not in comment_cols:
                    conn.execute(text(f'ALTER TABLE comment ADD COLUMN hidden_at {datetime_type}'))
                if 'hidden_by' not in comment_cols:
                    conn.execute(text('ALTER TABLE comment ADD COLUMN hidden_by INTEGER'))
                if 'hidden_reason' not in comment_cols:
                    conn.execute(text('ALTER TABLE comment ADD COLUMN hidden_reason VARCHAR(32)'))
                conn.execute(text('UPDATE comment SET is_hidden = 0 WHERE is_hidden IS NULL'))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_moderation_schema error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)


def ensure_performance_indexes():
    """Create pragmatic indexes for the hottest feed/comment queries."""
    try:
        engine = db.engine
        dialect = engine.dialect.name
        like_table = '"like"' if dialect == 'postgresql' else 'like'
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_post_created_at ON post (created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_post_publish_at ON post (publish_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_post_user_created_at ON post (user_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_post_lat_lng ON post (latitude, longitude)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_comment_post_created_at ON comment (post_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_comment_user_id ON comment (user_id)"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_like_post_id ON {like_table} (post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_message_room_id ON chat_message (room_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_message_room_created_at ON chat_message (room_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_message_room_is_deleted_created_at ON chat_message (room_id, is_deleted, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_participant_user_room ON chat_participant (user_id, room_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_participant_room_id ON chat_participant (room_id)"))
    except Exception as e:
        try:
            if 'app' in globals() and getattr(app, 'debug', False):
                print('DEBUG ensure_performance_indexes error:', e)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)


def ensure_startup_schema():
    """Run the lightweight schema/index sync needed in dev and prod."""
    db.create_all()
    ensure_chatroom_schema()
    ensure_post_schema()
    ensure_postmeta_schema()
    ensure_report_schema()
    ensure_user_schema()
    ensure_userblock_schema()
    ensure_safety_schema()
    ensure_moderation_schema()
    ensure_performance_indexes()
    try:
        purge_expired_audit_logs()
    except Exception as exc:
        _debug_log_suppressed('suppressed audit purge exception', exc)


AUDIT_DEFAULT_RETENTION_DAYS = 365
AUDIT_DEFAULT_VISIBLE_LIMIT = 250
AUDIT_MAX_VISIBLE_LIMIT = 500
AUDIT_MAX_EXPORT_LIMIT = 5000
AUDIT_DAYS_FILTER_OPTIONS = (7, 30, 90, 180, 365, 0)
AUDIT_WORKSPACE_FILTER_OPTIONS = ('admin', 'verification', 'moderation', 'safety')
AUDIT_EVENT_FILTER_HINTS = (
    'workspace.view',
    'user_roles.update',
    'verification.approve',
    'verification.reject',
    'report_details.view',
    'safety.route_points.view',
    'panic.resolve',
)


def audit_log_retention_days() -> int:
    raw = os.environ.get('AUDIT_LOG_RETENTION_DAYS', str(AUDIT_DEFAULT_RETENTION_DAYS))
    try:
        value = int(str(raw).strip() or AUDIT_DEFAULT_RETENTION_DAYS)
    except Exception:
        value = AUDIT_DEFAULT_RETENTION_DAYS
    return max(0, min(3650, value))


def audit_log_visible_limit() -> int:
    raw = os.environ.get('AUDIT_LOG_VISIBLE_LIMIT', str(AUDIT_DEFAULT_VISIBLE_LIMIT))
    try:
        value = int(str(raw).strip() or AUDIT_DEFAULT_VISIBLE_LIMIT)
    except Exception:
        value = AUDIT_DEFAULT_VISIBLE_LIMIT
    return max(50, min(AUDIT_MAX_VISIBLE_LIMIT, value))


def audit_log_export_limit() -> int:
    raw = os.environ.get('AUDIT_LOG_EXPORT_LIMIT', str(AUDIT_MAX_EXPORT_LIMIT))
    try:
        value = int(str(raw).strip() or AUDIT_MAX_EXPORT_LIMIT)
    except Exception:
        value = AUDIT_MAX_EXPORT_LIMIT
    return max(100, min(AUDIT_MAX_EXPORT_LIMIT, value))


def purge_expired_audit_logs(retention_days: int | None = None) -> int:
    retention = audit_log_retention_days() if retention_days is None else int(retention_days)
    if retention <= 0:
        return 0
    cutoff = utc_now_naive() - timedelta(days=retention)
    deleted = (
        AuditLog.query
        .filter(AuditLog.created_at.isnot(None), AuditLog.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return int(deleted or 0)


def parse_audit_days_filter(value) -> int:
    try:
        parsed = int(str(value).strip() or '30')
    except Exception:
        parsed = 30
    return parsed if parsed in AUDIT_DAYS_FILTER_OPTIONS else 30


def build_audit_filters_from_request() -> dict:
    return {
        'workspace': (request.args.get('audit_workspace') or '').strip().lower(),
        'event_type': (request.args.get('audit_event') or '').strip().lower(),
        'actor_username': (request.args.get('audit_actor') or '').strip(),
        'target_username': (request.args.get('audit_target') or '').strip(),
        'days': parse_audit_days_filter(request.args.get('audit_days')),
        'tab': (request.args.get('tab') or '').strip().lower(),
    }


def audit_filters_to_query_params(filters: dict | None = None) -> dict:
    payload = dict(filters or {})
    params = {}
    if payload.get('workspace'):
        params['audit_workspace'] = payload['workspace']
    if payload.get('event_type'):
        params['audit_event'] = payload['event_type']
    if payload.get('actor_username'):
        params['audit_actor'] = payload['actor_username']
    if payload.get('target_username'):
        params['audit_target'] = payload['target_username']
    params['audit_days'] = str(payload.get('days', 30))
    params['tab'] = payload.get('tab') or 'auditoria'
    return params


def build_audit_log_query(filters: dict | None = None, *, include_related: bool = True, limit: int | None = None):
    payload = dict(filters or {})
    query = AuditLog.query
    if include_related:
        query = query.options(
            selectinload(AuditLog.actor),
            selectinload(AuditLog.target_user),
        )

    workspace = (payload.get('workspace') or '').strip().lower()
    if workspace:
        query = query.filter(AuditLog.workspace == workspace)

    event_type = (payload.get('event_type') or '').strip().lower()
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)

    actor_username = (payload.get('actor_username') or '').strip().lower()
    if actor_username:
        actor_ids = db.session.query(User.id).filter(func.lower(User.username).like(f'%{actor_username}%'))
        query = query.filter(AuditLog.actor_id.in_(actor_ids))

    target_username = (payload.get('target_username') or '').strip().lower()
    if target_username:
        target_ids = db.session.query(User.id).filter(func.lower(User.username).like(f'%{target_username}%'))
        query = query.filter(AuditLog.target_user_id.in_(target_ids))

    days = parse_audit_days_filter(payload.get('days'))
    if days > 0:
        cutoff = utc_now_naive() - timedelta(days=days)
        query = query.filter(AuditLog.created_at >= cutoff)

    query = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    final_limit = audit_log_visible_limit() if limit is None else int(limit)
    if final_limit > 0:
        query = query.limit(final_limit)
    return query


def audit_filter_option_payloads() -> dict:
    try:
        rows = (
            db.session.query(AuditLog.workspace, AuditLog.event_type)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(2000)
            .all()
        )
    except Exception:
        rows = []
    workspaces = {item for item in AUDIT_WORKSPACE_FILTER_OPTIONS}
    event_types = {item for item in AUDIT_EVENT_FILTER_HINTS}
    for workspace, event_type in rows:
        if workspace:
            workspaces.add(str(workspace).strip().lower())
        if event_type:
            event_types.add(str(event_type).strip().lower())
    return {
        'workspaces': sorted(workspaces),
        'event_types': sorted(event_types),
        'days': list(AUDIT_DAYS_FILTER_OPTIONS),
    }


def resolve_initial_admin_tab(available_tabs, fallback='users') -> str:
    requested = (request.args.get('tab') or '').strip().lower()
    if requested and requested in (available_tabs or []):
        return requested
    return fallback if fallback in (available_tabs or []) else ((available_tabs or [fallback])[0])


ROLE_SUPER_ADMIN = 'super_admin'
ROLE_VERIFICATION_REVIEWER = 'verification_reviewer'
ROLE_MODERATION_REVIEWER = 'moderation_reviewer'
ROLE_SAFETY_OPERATOR = 'safety_operator'
ROLE_SUPPORT_READONLY = 'support_readonly'

PERM_ADMIN_PANEL_VIEW = 'admin.panel.view'
PERM_ACCOUNT_BYPASS_RESTRICTIONS = 'account.bypass_restrictions'
PERM_CONTENT_UNRESTRICTED = 'content.unrestricted'
PERM_CONTENT_REVIEW_PRIVATE = 'content.review_private'
PERM_USERS_MANAGE = 'users.manage'
PERM_VERIFICATION_REVIEW = 'verification.review'
PERM_POSTS_MANAGE = 'posts.manage'
PERM_CHAT_ROOMS_MANAGE = 'chat.rooms.manage'
PERM_CHAT_ROOMS_OVERRIDE = 'chat.rooms.override'
PERM_CHAT_MESSAGES_MODERATE = 'chat.messages.moderate'
PERM_REPORTS_REVIEW = 'reports.review'
PERM_SAFETY_VIEW_ANY = 'safety.view_any'
PERM_SAFETY_RESOLVE_PANIC = 'safety.resolve_panic'
PERM_STAFF_BADGE = 'staff.badge'
PERM_PROTECTED_STAFF = 'staff.protected'

ROLE_PERMISSIONS = {
    ROLE_SUPER_ADMIN: {'*'},
    ROLE_VERIFICATION_REVIEWER: {
        PERM_VERIFICATION_REVIEW,
    },
    ROLE_MODERATION_REVIEWER: {
        PERM_CONTENT_REVIEW_PRIVATE,
        PERM_REPORTS_REVIEW,
        PERM_CHAT_ROOMS_MANAGE,
        PERM_CHAT_MESSAGES_MODERATE,
    },
    ROLE_SAFETY_OPERATOR: {
        PERM_SAFETY_VIEW_ANY,
        PERM_SAFETY_RESOLVE_PANIC,
    },
    ROLE_SUPPORT_READONLY: set(),
}

STAFF_ROLE_OPTIONS = (
    {
        'key': ROLE_SUPER_ADMIN,
        'label': 'Súper admin',
        'description': 'Acceso total y gestión de roles.',
    },
    {
        'key': ROLE_VERIFICATION_REVIEWER,
        'label': 'Verificación',
        'description': 'Revisión de identidad y elegibilidad.',
    },
    {
        'key': ROLE_MODERATION_REVIEWER,
        'label': 'Moderación',
        'description': 'Reportes, restauraciones y strikes.',
    },
    {
        'key': ROLE_SAFETY_OPERATOR,
        'label': 'Safety',
        'description': 'Check-ins, trayectos y pánico.',
    },
    {
        'key': ROLE_SUPPORT_READONLY,
        'label': 'Soporte',
        'description': 'Consulta operativa de solo lectura.',
    },
)


def user_role_names(user) -> set[str]:
    if not user or not getattr(user, 'is_authenticated', False):
        return set()
    roles: set[str] = set()
    try:
        if hasattr(user, 'role_set'):
            roles = {role.strip().lower() for role in user.role_set() if str(role).strip()}
        else:
            raw = (getattr(user, 'roles', None) or '').strip()
            roles = {
                chunk.strip().lower()
                for chunk in raw.split(',')
                if chunk.strip()
            }
    except Exception:
        roles = set()
    if not roles and str(getattr(user, 'username', '')).strip().lower() == 'admin':
        roles.add(ROLE_SUPER_ADMIN)
    return roles


def user_has_role(user, role: str) -> bool:
    normalized = (role or '').strip().lower()
    if not normalized:
        return False
    return normalized in user_role_names(user)


def user_has_any_role(user, *roles: str) -> bool:
    current = user_role_names(user)
    if not current:
        return False
    for role in roles:
        normalized = (role or '').strip().lower()
        if normalized and normalized in current:
            return True
    return False


def user_has_permission(user, permission: str) -> bool:
    normalized = (permission or '').strip().lower()
    if not normalized:
        return False
    roles = user_role_names(user)
    if not roles:
        return False
    for role in roles:
        permissions = ROLE_PERMISSIONS.get(role, set())
        if '*' in permissions or normalized in permissions:
            return True
    return False


def user_is_super_admin(user) -> bool:
    return user_has_role(user, ROLE_SUPER_ADMIN)


def user_is_protected_staff(user) -> bool:
    return user_has_permission(user, PERM_PROTECTED_STAFF)


def user_has_staff_badge(user) -> bool:
    return user_has_permission(user, PERM_STAFF_BADGE)


def user_can_override_content_controls(user) -> bool:
    return user_has_permission(user, PERM_CONTENT_UNRESTRICTED)


def user_can_review_private_content(user) -> bool:
    return user_has_permission(user, PERM_CONTENT_REVIEW_PRIVATE) or user_can_override_content_controls(user)


def user_can_access_admin_panel(user) -> bool:
    return user_has_permission(user, PERM_ADMIN_PANEL_VIEW)


def permission_required(permission: str, *, json_only: bool = False, flash_message: str = 'Acceso denegado.'):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                wants_json = json_only or request.path.startswith('/api/') or 'application/json' in (request.headers.get('Accept') or '')
                if wants_json:
                    return jsonify({'error': 'Inicia sesión para continuar.'}), 401
                return redirect(url_for('login'))
            if user_has_permission(current_user, permission):
                return fn(*args, **kwargs)
            wants_json = json_only or request.path.startswith('/api/') or 'application/json' in (request.headers.get('Accept') or '')
            if wants_json:
                return jsonify({'error': flash_message}), 403
            flash(flash_message, 'error')
            return redirect(url_for('index'))
        return wrapper
    return decorator


def staff_role_payloads():
    return [dict(item) for item in STAFF_ROLE_OPTIONS]


def count_super_admin_users() -> int:
    try:
        users = User.query.all()
    except Exception:
        return 0
    return sum(1 for user in users if user_is_super_admin(user))


def is_user_verified(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return True
    if user_has_permission(user, PERM_ACCOUNT_BYPASS_RESTRICTIONS):
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


def moderation_badge_level(user) -> int:
    if not user:
        return 0
    if user_is_protected_staff(user):
        return 0
    strikes = int(getattr(user, 'abuse_strikes', 0) or 0)
    if strikes >= 2:
        return 2
    if strikes >= 1:
        return 1
    return 0


def is_user_permanently_banned(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user_has_permission(user, PERM_ACCOUNT_BYPASS_RESTRICTIONS):
        return False
    return bool(getattr(user, 'permanently_banned_at', None))


def _clear_expired_moderation_restriction(user):
    if not user or user_has_permission(user, PERM_ACCOUNT_BYPASS_RESTRICTIONS):
        return
    until = getattr(user, 'muted_until', None)
    if until and until <= utc_now_naive():
        user.muted_until = None
        db.session.add(user)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def user_restriction_state(user, *, auto_clear: bool = False):
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    if user_has_permission(user, PERM_ACCOUNT_BYPASS_RESTRICTIONS):
        return None

    now = utc_now_naive()
    if getattr(user, 'permanently_banned_at', None):
        return {
            'type': 'permanent',
            'message': 'Tu cuenta fue bloqueada de manera permanente por reincidencia grave en el incumplimiento de las reglas de la comunidad.',
            'until': None,
            'remaining_seconds': None,
        }

    until = getattr(user, 'muted_until', None)
    if not until:
        return None
    if until <= now:
        if auto_clear:
            _clear_expired_moderation_restriction(user)
        return None

    remaining_seconds = max(0, int((until - now).total_seconds()))
    return {
        'type': 'temporary',
        'message': 'Tu cuenta se encuentra suspendida temporalmente por infringir las reglas de la comunidad.',
        'until': until,
        'remaining_seconds': remaining_seconds,
    }


def is_user_temp_muted(user) -> bool:
    state = user_restriction_state(user)
    return bool(state and state.get('type') == 'temporary')


def remaining_mute_seconds(user) -> int:
    state = user_restriction_state(user)
    if not state or state.get('type') != 'temporary':
        return 0
    return int(state.get('remaining_seconds') or 0)


def apply_abuse_strike(
    user,
    reason: str = 'abusive_language',
    *,
    issued_by=None,
    source_type: str = 'system',
    source_id: int | None = None,
    source_label: str | None = None,
    details: str | None = None,
    content_excerpt: str | None = None,
):
    if not user:
        return {'applied': False, 'reason': 'invalid_user', 'strike': None, 'strike_count': 0, 'consequence': 'none'}
    if user_is_protected_staff(user):
        return {'applied': False, 'reason': 'admin_immune', 'strike': None, 'strike_count': 0, 'consequence': 'none'}
    if is_user_permanently_banned(user):
        return {'applied': False, 'reason': 'already_banned', 'strike': None, 'strike_count': int(getattr(user, 'abuse_strikes', 0) or 0), 'consequence': 'permanent_ban'}

    now = utc_now_naive()
    day_start = datetime(now.year, now.month, now.day)
    day_end = day_start + timedelta(days=1)
    existing_today = ModerationStrike.query.filter(
        ModerationStrike.user_id == user.id,
        ModerationStrike.created_at >= day_start,
        ModerationStrike.created_at < day_end,
    ).order_by(ModerationStrike.created_at.desc()).first()
    if existing_today:
        return {
            'applied': False,
            'reason': 'daily_limit',
            'strike': existing_today,
            'strike_count': int(getattr(user, 'abuse_strikes', 0) or 0),
            'consequence': 'none',
        }

    strikes = int(getattr(user, 'abuse_strikes', 0) or 0) + 1
    user.abuse_strikes = strikes
    user.last_abuse_at = now

    consequence = 'warning'
    if strikes == 1:
        consequence = 'warning'
    elif strikes == 2:
        user.muted_until = now + timedelta(days=7)
        consequence = 'temporary_ban'
    else:
        user.permanently_banned_at = now
        user.permanent_ban_reason = (reason or 'moderation_strike')[:255]
        user.muted_until = None
        consequence = 'permanent_ban'

    strike = ModerationStrike(
        user_id=user.id,
        issued_by=getattr(issued_by, 'id', issued_by),
        source_type=(source_type or 'system')[:32],
        source_id=source_id,
        source_label=(source_label or '')[:255] or None,
        reason=(reason or 'Incumplimiento de reglas')[:255],
        details=details or None,
        content_excerpt=content_excerpt or None,
        strike_number=strikes,
        consequence=consequence,
        created_at=now,
    )
    db.session.add(user)
    db.session.add(strike)
    return {
        'applied': True,
        'reason': 'ok',
        'strike': strike,
        'strike_count': strikes,
        'consequence': consequence,
    }


def temp_mute_error_payload(prefix: str = 'Tu cuenta se encuentra suspendida temporalmente.'):
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
    if user_can_override_content_controls(user):
        return True
    return getattr(post, 'user_id', None) == getattr(user, 'id', None)


def normalize_location_visibility(value: str | None, is_admin_user: bool) -> str:
    val = (value or '').strip().lower()
    allowed = {'exact', 'approx', 'hidden'}
    if val not in allowed:
        return 'exact'
    return val


def normalize_capture_motion_state(value: str | None) -> str:
    val = (value or '').strip().lower()
    if val in {'stationary', 'walking'}:
        return val
    if val in {'blocked', 'vehicle', 'driving', 'cycling', 'running'}:
        return 'blocked'
    return 'unknown'


def public_location_approx_meters() -> int:
    raw = str(os.environ.get('PUBLIC_LOCATION_APPROX_METERS', '25')).strip()
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        value = 25
    return max(10, min(250, value))


def approximate_public_coords(lat, lng) -> tuple[float | None, float | None]:
    try:
        if lat is None or lng is None:
            return None, None
        lat_value = float(lat)
        lng_value = float(lng)
    except (TypeError, ValueError):
        return None, None

    meters = float(public_location_approx_meters())
    lat_step = meters / 111_320.0
    cos_lat = max(abs(cos(radians(lat_value))), 0.1)
    lng_step = meters / (111_320.0 * cos_lat)

    snapped_lat = round(lat_value / lat_step) * lat_step if lat_step > 0 else lat_value
    snapped_lng = round(lng_value / lng_step) * lng_step if lng_step > 0 else lng_value
    return round(snapped_lat, 6), round(snapped_lng, 6)


def approximate_location_label(city: str | None, country: str | None) -> str:
    safe_city = (city or '').strip()
    safe_country = (country or '').strip()
    if safe_city and safe_country:
        return f"Zona aproximada en {safe_city}, {safe_country}"
    if safe_city:
        return f"Zona aproximada en {safe_city}"
    if safe_country:
        return f"Zona aproximada en {safe_country}"
    return 'Zona aproximada'


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
        if user_can_review_private_content(viewer) or getattr(viewer, 'id', None) == getattr(post, 'user_id', None):
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
        approx_lat, approx_lng = approximate_public_coords(lat, lng)
        return {
            'lat': approx_lat,
            'lng': approx_lng,
            'name': approximate_location_label(city, country),
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
    jinja_cache_dir = os.path.join(app.instance_path, 'jinja-cache')
    os.makedirs(jinja_cache_dir, exist_ok=True)
    app.jinja_env.bytecode_cache = FileSystemBytecodeCache(jinja_cache_dir, '%s.cache')

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
            'user_restriction_state': user_restriction_state(current_user, auto_clear=True),
        }

    @app.context_processor
    def inject_safety_publish_policy():
        return {'safety_publish_policy': safety_publish_policy_payload()}

    @app.context_processor
    def inject_access_control():
        return {
            'user_role_names': user_role_names,
            'user_has_permission': user_has_permission,
            'user_has_role': user_has_role,
            'user_is_super_admin': user_is_super_admin,
            'user_is_protected_staff': user_is_protected_staff,
            'user_has_staff_badge': user_has_staff_badge,
            'staff_role_options': staff_role_payloads(),
            'current_user_is_super_admin': user_is_super_admin(current_user),
            'current_user_can_access_admin_panel': user_can_access_admin_panel(current_user),
            'current_user_can_override_content_controls': user_can_override_content_controls(current_user),
            'current_user_can_review_private_content': user_can_review_private_content(current_user),
        }

    @app.before_request
    def enforce_account_restrictions():
        if not current_user.is_authenticated:
            return None
        if user_has_permission(current_user, PERM_ACCOUNT_BYPASS_RESTRICTIONS):
            return None

        state = user_restriction_state(current_user, auto_clear=True)
        if not state:
            return None

        endpoint = (request.endpoint or '').strip()
        allowed = {
            'logout',
            'account_restricted',
            'static',
        }
        if endpoint in allowed or endpoint.startswith('static'):
            return None

        payload = {
            'error': state.get('message') or 'Tu cuenta tiene una restricción activa.',
            'restriction': {
                'type': state.get('type'),
                'remaining_seconds': state.get('remaining_seconds'),
                'until': state.get('until').isoformat() if state.get('until') else None,
            }
        }
        wants_json = request.path.startswith('/api/') or 'application/json' in (request.headers.get('Accept') or '')
        if wants_json:
            return jsonify(payload), 423
        return redirect(url_for('account_restricted'))

    @login_manager.user_loader
    def load_user(user_id):
        # Compatible con SQLAlchemy 2.x (Query.get es legacy)
        try:
            return db.session.get(User, int(user_id))
        except Exception as exc:
            db.session.rollback()
            _debug_log_suppressed('suppressed exception', exc)
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


    def public_upload_storage_enabled() -> bool:
        return (
            (app.config.get('UPLOAD_BACKEND') or '').strip().lower() == 'supabase'
            and bool((app.config.get('SUPABASE_URL') or '').strip())
            and bool((app.config.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip())
            and bool((app.config.get('SUPABASE_STORAGE_BUCKET') or '').strip())
        )

    def public_upload_storage_path(filename: str | None) -> str | None:
        normalized = (filename or '').replace('\\', '/').lstrip('/')
        if not normalized or normalized.startswith('verify/'):
            return None
        return normalized

    def public_upload_storage_url(filename: str | None) -> str | None:
        storage_path = public_upload_storage_path(filename)
        if not storage_path or not public_upload_storage_enabled():
            return None
        base_url = (app.config.get('SUPABASE_URL') or '').rstrip('/')
        bucket = (app.config.get('SUPABASE_STORAGE_BUCKET') or '').strip()
        return f"{base_url}/storage/v1/object/public/{quote(bucket, safe='')}/{quote(storage_path, safe='/')}"

    def local_public_upload_url(filename: str | None) -> str | None:
        storage_path = public_upload_storage_path(filename)
        if not storage_path:
            return None
        folder = ensure_upload_folder()
        static_root = os.path.abspath(app.static_folder or '')
        if not static_root:
            return None
        file_path = os.path.abspath(os.path.join(folder, storage_path))
        try:
            relative_path = os.path.relpath(file_path, static_root)
        except ValueError:
            return None
        if relative_path.startswith('..'):
            return None
        return url_for('static', filename=relative_path.replace(os.sep, '/'))

    def sync_public_upload_to_storage(filename: str | None, *, local_path: str | None = None, mime_type: str | None = None) -> bool:
        storage_path = public_upload_storage_path(filename)
        if not storage_path:
            return True
        if not public_upload_storage_enabled():
            return True

        if not local_path:
            local_path = os.path.join(ensure_upload_folder(), storage_path)
        if not os.path.exists(local_path):
            return False

        api_key = (app.config.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
        base_url = (app.config.get('SUPABASE_URL') or '').rstrip('/')
        bucket = (app.config.get('SUPABASE_STORAGE_BUCKET') or '').strip()
        if not mime_type:
            mime_type = mimetypes.guess_type(local_path)[0] or 'application/octet-stream'

        with open(local_path, 'rb') as fh:
            payload = fh.read()

        req = Request(
            f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(storage_path, safe='/')}",
            data=payload,
            headers={
                'Authorization': f'Bearer {api_key}',
                'apikey': api_key,
                'Content-Type': mime_type,
                'x-upsert': 'true',
            },
            method='POST',
        )
        try:
            with urlopen(req, timeout=30) as resp:  # nosec B310
                status = getattr(resp, 'status', None) or resp.getcode()
                return status in (200, 201)
        except HTTPError as exc:
            if app.debug:
                try:
                    detail = exc.read().decode('utf-8', errors='replace')
                except Exception:
                    detail = str(exc)
                print(f'DEBUG: Supabase Storage HTTPError syncing {storage_path}: {detail}')
            return False
        except URLError as exc:
            if app.debug:
                print(f'DEBUG: Supabase Storage URLError syncing {storage_path}: {exc}')
            return False
        except Exception as exc:
            if app.debug:
                print(f'DEBUG: Supabase Storage sync error for {storage_path}: {exc}')
            return False

    def delete_public_upload_from_storage(filename: str | None) -> None:
        storage_path = public_upload_storage_path(filename)
        if not storage_path or not public_upload_storage_enabled():
            return
        api_key = (app.config.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
        base_url = (app.config.get('SUPABASE_URL') or '').rstrip('/')
        bucket = (app.config.get('SUPABASE_STORAGE_BUCKET') or '').strip()
        req = Request(
            f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(storage_path, safe='/')}",
            headers={
                'Authorization': f'Bearer {api_key}',
                'apikey': api_key,
            },
            method='DELETE',
        )
        try:
            with urlopen(req, timeout=15):  # nosec B310
                return
        except HTTPError as exc:
            if exc.code == 404:
                return
            if app.debug:
                try:
                    detail = exc.read().decode('utf-8', errors='replace')
                except Exception:
                    detail = str(exc)
                print(f'DEBUG: Supabase Storage HTTPError deleting {storage_path}: {detail}')
        except Exception as exc:
            if app.debug:
                print(f'DEBUG: Supabase Storage delete error for {storage_path}: {exc}')

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

    def strip_image_metadata_in_place(image_path: str) -> bool:
        """Re-save common image formats without EXIF/ICC metadata."""
        _, ext = os.path.splitext(image_path or '')
        ext = ext.lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}:
            return False

        try:
            from PIL import Image, ImageOps
        except Exception:
            return False

        tmp_path = f'{image_path}.sanitized'
        try:
            with Image.open(image_path) as im:
                normalized = ImageOps.exif_transpose(im)
                output = normalized.copy()
                target_format = 'JPEG'
                save_kwargs: dict[str, object] = {}

                if ext in {'.jpg', '.jpeg'}:
                    target_format = 'JPEG'
                    if output.mode not in ('RGB', 'L'):
                        output = output.convert('RGB')
                    save_kwargs = {'quality': 92, 'optimize': True}
                elif ext == '.png':
                    target_format = 'PNG'
                    if output.mode not in ('RGB', 'RGBA', 'L'):
                        output = output.convert('RGBA')
                    save_kwargs = {'optimize': True}
                elif ext == '.webp':
                    target_format = 'WEBP'
                    if output.mode not in ('RGB', 'RGBA', 'L'):
                        output = output.convert('RGBA')
                    save_kwargs = {'quality': 92, 'method': 6}
                elif ext == '.bmp':
                    target_format = 'BMP'
                    if output.mode not in ('RGB', 'RGBA', 'L'):
                        output = output.convert('RGB')

                output.save(tmp_path, format=target_format, **save_kwargs)

            os.replace(tmp_path, image_path)
            return True
        except Exception as exc:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception as cleanup_exc:
                _debug_log_suppressed('suppressed exception', cleanup_exc)
            if app.debug:
                print('DEBUG: metadata strip failed:', exc)
            return False

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

    def _summarize_moderation_text(raw: str | None, limit: int = 220) -> str:
        txt = ' '.join((raw or '').strip().split())
        if not txt:
            return 'Sin extracto disponible.'
        if len(txt) <= limit:
            return txt
        return txt[: limit - 1].rstrip() + '…'

    def _format_moderation_dt(dt: datetime | None) -> str:
        if not dt:
            return 'Sin fecha'
        return dt.strftime('%d/%m/%Y %H:%M')

    def send_moderation_notice_email(user: User, strike: ModerationStrike) -> bool:
        recipient = (getattr(user, 'email', '') or '').strip()
        if not recipient:
            return False

        all_strikes = ModerationStrike.query.filter_by(user_id=user.id).order_by(ModerationStrike.created_at.asc()).all()
        consequence = (strike.consequence or 'warning').strip().lower()
        if consequence == 'permanent_ban':
            subject = 'Tu cuenta fue bloqueada permanentemente - Violeta'
            headline = 'Bloqueamos tu cuenta de manera permanente por acumulación de 3 strikes.'
        elif consequence == 'temporary_ban':
            subject = 'Tu cuenta fue suspendida temporalmente - Violeta'
            headline = 'Tu cuenta fue suspendida temporalmente durante 7 días por reincidencia en el incumplimiento de las reglas de la comunidad.'
        else:
            subject = 'Recibiste un strike en Violeta'
            headline = 'Registramos un strike en tu cuenta por contenido que infringe las reglas de la comunidad.'

        history_lines = []
        history_html = []
        for item in all_strikes:
            label = item.source_label or item.source_type
            excerpt = _summarize_moderation_text(item.content_excerpt)
            created = _format_moderation_dt(item.created_at)
            history_lines.append(
                f"- Strike {item.strike_number}: {label} | {item.reason} | {created}\n"
                f"  Extracto: {excerpt}"
            )
            history_html.append(
                f'<li style="margin:0 0 10px 0;">'
                f'<strong>Strike {item.strike_number}</strong> · {label}<br>'
                f'<span style="color:#d8b4fe;">{item.reason}</span> · {created}<br>'
                f'<span style="color:#f5f3ff;">{excerpt}</span>'
                f'</li>'
            )

        strike_label = strike.source_label or strike.source_type
        strike_excerpt = _summarize_moderation_text(strike.content_excerpt)
        strike_created = _format_moderation_dt(strike.created_at)
        warning_line = ''
        consequence_html = ''
        if consequence == 'temporary_ban':
            warning_line = '\nLa suspensión finalizará automáticamente en 7 días.'
            consequence_html = '<div style="margin-top:10px;color:#fde68a;"><strong>Consecuencia:</strong> suspensión temporal de 7 días.</div>'
        elif consequence == 'permanent_ban':
            warning_line = '\nEl bloqueo es definitivo y responde a la acumulación de 3 strikes.'
            consequence_html = '<div style="margin-top:10px;color:#fca5a5;"><strong>Consecuencia:</strong> bloqueo permanente.</div>'

        text_body = (
            f"Hola {getattr(user, 'username', 'usuaria')},\n\n"
            f"{headline}\n\n"
            f"Contenido sancionado: {strike_label}\n"
            f"Fecha y hora: {strike_created}\n"
            f"Motivo: {strike.reason}\n"
            f"Extracto: {strike_excerpt}\n"
            f"Detalle del reporte: {strike.details or 'Sin detalle adicional.'}\n"
            f"Strikes acumulados: {getattr(user, 'abuse_strikes', 0)}"
            f"{warning_line}\n\n"
            "Historial relevante:\n"
            f"{'\\n\\n'.join(history_lines)}\n\n"
            "Si consideras que esto es un error, responde a este correo.\n\n"
            "Equipo Violeta"
        )

        html_body = (
            '<html><body style="font-family:Inter,Arial,sans-serif;background:#0f1020;color:#f3f4f6;padding:20px;">'
            '<div style="max-width:620px;margin:0 auto;background:#1b1d35;border:1px solid rgba(167,139,250,.35);border-radius:16px;padding:24px;">'
            f'<h2 style="margin:0 0 12px 0;color:#f5d0fe;">{subject}</h2>'
            f'<p style="margin:0 0 16px 0;">Hola <strong>{getattr(user, "username", "usuaria")}</strong>.</p>'
            f'<p style="margin:0 0 16px 0;color:#e9d5ff;">{headline}</p>'
            '<div style="padding:14px 16px;border-radius:14px;background:rgba(139,92,246,.12);border:1px solid rgba(216,180,254,.25);margin-bottom:18px;">'
            f'<div><strong>Contenido sancionado:</strong> {strike_label}</div>'
            f'<div><strong>Fecha y hora:</strong> {strike_created}</div>'
            f'<div><strong>Motivo:</strong> {strike.reason}</div>'
            f'<div><strong>Extracto:</strong> {strike_excerpt}</div>'
            f'<div><strong>Detalle del reporte:</strong> {strike.details or "Sin detalle adicional."}</div>'
            f'<div><strong>Strikes acumulados:</strong> {getattr(user, "abuse_strikes", 0)}</div>'
            f'{consequence_html}'
            '</div>'
            '<h3 style="margin:0 0 10px 0;color:#c4b5fd;font-size:1rem;">Historial relevante</h3>'
            f'<ul style="padding-left:18px;margin:0 0 18px 0;">{"".join(history_html)}</ul>'
            '<p style="margin:0;color:#cbd5e1;">Si consideras que esto es un error, responde a este correo.</p>'
            '</div></body></html>'
        )
        return send_email_message(subject, [recipient], text_body, html_body)


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
        if str(os.environ.get('ENABLE_USER_EXPORT', '')).strip().lower() not in {'1', 'true', 'yes', 'on'}:
            return
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
                    writer.writerow(['username', 'email', 'posts_count', 'is_verified'])
                writer.writerow([
                    user.username,
                    user.email,
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

    def get_emergency_number() -> str:
        value = (os.environ.get('EMERGENCY_NUMBER') or '911').strip()
        return value or '911'

    def send_twilio_message(to_value: str, from_value: str, body: str) -> bool:
        sid = (os.environ.get('TWILIO_ACCOUNT_SID') or '').strip()
        token = (os.environ.get('TWILIO_AUTH_TOKEN') or '').strip()
        if not sid or not token or not to_value or not from_value or not body:
            return False

        try:
            payload = urlencode({
                'To': to_value,
                'From': from_value,
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
                print('DEBUG twilio message error:', e)
            return False

    def send_whatsapp_via_twilio(to_phone: str, body: str) -> bool:
        from_phone = (os.environ.get('TWILIO_WHATSAPP_FROM_NUMBER') or '').strip()
        if not from_phone:
            return False
        return send_twilio_message(f'whatsapp:{to_phone}', f'whatsapp:{from_phone}', body)

    def send_sms_via_twilio(to_phone: str, body: str) -> bool:
        from_phone = (os.environ.get('TWILIO_FROM_NUMBER') or '').strip()
        if not from_phone:
            return False
        return send_twilio_message(to_phone, from_phone, body)

    def valid_coords(lat, lng):
        try:
            if lat is None or lng is None:
                return False
            return -90.0 <= float(lat) <= 90.0 and -180.0 <= float(lng) <= 180.0
        except Exception:
            return False

    def safety_publish_min_delay_minutes() -> int:
        raw = str(os.environ.get('SAFETY_PUBLISH_MIN_DELAY_MINUTES', '15')).strip()
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            value = 15
        return max(5, min(120, value))

    def safety_publish_distance_meters() -> int:
        raw = str(os.environ.get('SAFETY_PUBLISH_DISTANCE_METERS', '200')).strip()
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            value = 200
        return max(25, min(5000, value))

    def safety_publish_fallback_minutes() -> int:
        raw = str(os.environ.get('SAFETY_PUBLISH_FALLBACK_MINUTES', '60')).strip()
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            value = 60
        return max(safety_publish_min_delay_minutes(), min(24 * 60, value))

    def safety_publish_policy_payload():
        return {
            'min_delay_minutes': safety_publish_min_delay_minutes(),
            'distance_meters': safety_publish_distance_meters(),
            'fallback_minutes': safety_publish_fallback_minutes(),
        }

    def safety_publish_min_ready_at(post) -> datetime:
        created_at = getattr(post, 'created_at', None) or datetime.now()
        return created_at + timedelta(minutes=safety_publish_min_delay_minutes())

    def safety_publish_fallback_at(post) -> datetime:
        created_at = getattr(post, 'created_at', None) or datetime.now()
        return created_at + timedelta(minutes=safety_publish_fallback_minutes())

    def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        d_lat = radians(lat2 - lat1)
        d_lng = radians(lng2 - lng1)
        a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
        return 6371000.0 * 2 * asin(sqrt(a))

    def pending_safety_posts_for_user(user):
        if not user or not getattr(user, 'is_authenticated', False):
            return []
        if user_can_override_content_controls(user):
            return []
        now = datetime.now()
        return (
            Post.query
            .options(selectinload(Post.meta))
            .filter_by(user_id=user.id)
            .filter(Post.publish_at.isnot(None), Post.publish_at > now)
            .order_by(Post.created_at.asc())
            .limit(30)
            .all()
        )

    def summarize_pending_safety_posts_for_user(user):
        now = datetime.now()
        posts = pending_safety_posts_for_user(user)
        next_due_at = None
        needs_location_check = False
        fallback_due_count = 0
        missing_post_location_count = 0

        for post in posts:
            min_ready_at = safety_publish_min_ready_at(post)
            fallback_at = safety_publish_fallback_at(post)
            if not valid_coords(getattr(post, 'latitude', None), getattr(post, 'longitude', None)):
                missing_post_location_count += 1
            if now >= fallback_at:
                fallback_due_count += 1
            elif now >= min_ready_at:
                needs_location_check = True

            candidate_due_at = fallback_at if now >= min_ready_at else min_ready_at
            if next_due_at is None or candidate_due_at < next_due_at:
                next_due_at = candidate_due_at

        next_check_in_sec = None
        if next_due_at is not None and next_due_at > now:
            next_check_in_sec = max(1, int((next_due_at - now).total_seconds()))

        return {
            'pending_count': len(posts),
            'needs_location_check': needs_location_check,
            'fallback_due_count': fallback_due_count,
            'missing_post_location_count': missing_post_location_count,
            'next_check_in_sec': next_check_in_sec,
            'policy': safety_publish_policy_payload(),
        }

    def invalidate_post_discovery_caches():
        invalidate_runtime_response_cache('hotspots')
        invalidate_runtime_response_cache('posts_in_radius')
        invalidate_runtime_response_cache('posts_by_city')
        invalidate_runtime_response_cache('feed_sidebar')
        _feed_sidebar_cache.clear()

    def try_release_pending_safety_posts_for_user(user, current_lat=None, current_lng=None):
        now = datetime.now()
        posts = pending_safety_posts_for_user(user)
        released = []
        distance_threshold = float(safety_publish_distance_meters())
        can_check_distance = valid_coords(current_lat, current_lng)

        for post in posts:
            min_ready_at = safety_publish_min_ready_at(post)
            fallback_at = safety_publish_fallback_at(post)
            reason = None
            distance_m = None

            if now >= fallback_at:
                reason = 'fallback'
            elif now >= min_ready_at and can_check_distance and valid_coords(post.latitude, post.longitude):
                distance_m = haversine_distance_m(
                    float(post.latitude),
                    float(post.longitude),
                    float(current_lat),
                    float(current_lng),
                )
                if distance_m >= distance_threshold:
                    reason = 'distance'

            if not reason:
                continue

            post.publish_at = now
            db.session.add(post)
            released.append({
                'id': post.id,
                'reason': reason,
                'distance_meters': int(round(distance_m)) if distance_m is not None else None,
            })

        if released:
            db.session.commit()
            invalidate_post_discovery_caches()

        summary = summarize_pending_safety_posts_for_user(user)
        return {
            'released_count': len(released),
            'released_posts': released,
            **summary,
        }

    def annotate_user_post_visibility_state(posts):
        now = datetime.now()
        for post in posts:
            post.can_delete = bool(post.created_at and (now - post.created_at) <= timedelta(hours=1))
            post.is_pending = bool(getattr(post, 'publish_at', None) and getattr(post, 'publish_at') > now)
            if post.is_pending:
                post.pending_min_ready_at = safety_publish_min_ready_at(post)
                post.pending_fallback_at = safety_publish_fallback_at(post)
            else:
                post.pending_min_ready_at = None
                post.pending_fallback_at = None

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

    FEED_CITY_BOUNDS = {
        'monterrey': (25.60, 25.75, -100.42, -100.25),
        'san-pedro': (25.62, 25.70, -100.45, -100.35),
        'guadalupe': (25.65, 25.72, -100.28, -100.18),
        'apodaca': (25.73, 25.82, -100.25, -100.12),
        'escobedo': (25.75, 25.85, -100.38, -100.28),
        'santa-catarina': (25.62, 25.72, -100.52, -100.42),
    }
    _feed_sidebar_cache: dict[tuple, dict[str, object]] = {}
    _runtime_response_cache: dict[tuple, dict[str, object]] = {}
    _runtime_cache_client = None
    _runtime_cache_client_failed = False

    def extract_report_categories(cats_raw):
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
            name = str(c).strip()
            if not name:
                continue
            key = name.casefold()
            if key in ('terrenos baldios', 'terrenos baldíos', 'baldios', 'baldío', 'baldio', 'baldíos', 'punto ciego'):
                name = 'Terrenos baldíos'
            elif key in ('poca iluminacion', 'poca iluminación'):
                name = 'Poca iluminación'
            elif key in ('banquetas en mal estado',):
                name = 'Banquetas en mal estado'
            elif key in ('zona insegura', 'zonas inseguras'):
                name = 'Zona insegura'
            normalized.add(name)
        return normalized

    def apply_feed_city_filter(query, selected_city: str):
        if not selected_city or selected_city == 'all':
            return query
        bounds = FEED_CITY_BOUNDS.get(selected_city)
        if bounds:
            lat_min, lat_max, lng_min, lng_max = bounds
            return query.filter(
                Post.latitude.isnot(None),
                Post.longitude.isnot(None),
                Post.latitude.between(lat_min, lat_max),
                Post.longitude.between(lng_min, lng_max),
            )
        return query.filter(Post.city.ilike(f"%{selected_city}%"))

    def build_feed_posts_query(selected_city: str, viewer=None, *, eager: bool = False):
        base_query = Post.query
        if eager:
            base_query = base_query.options(
                selectinload(Post.author),
                selectinload(Post.meta),
            )
        query = public_posts_query(base_query).order_by(Post.created_at.desc())
        blocked_ids = blocked_user_ids_for(viewer) if viewer and getattr(viewer, 'is_authenticated', False) else set()
        if blocked_ids:
            query = query.filter(~Post.user_id.in_(blocked_ids))
        query = apply_feed_city_filter(query, selected_city)
        return query, blocked_ids

    def compute_feed_sidebar_counts(query):
        report_counts = []
        report_counts_today = []
        try:
            cat_counts = Counter()
            rows = query.with_entities(Post.categories).all()
            for (cats_raw,) in rows:
                for name in extract_report_categories(cats_raw):
                    cat_counts[name] += 1

            report_counts = [{'category': k, 'count': v} for k, v in cat_counts.items() if v > 0]
            report_counts.sort(key=lambda x: (-x['count'], x['category'].casefold()))

            from zoneinfo import ZoneInfo

            tz_name = app.config.get('APP_TIMEZONE') or 'America/Monterrey'
            try:
                app_tz = ZoneInfo(tz_name)
            except Exception:
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
                for name in extract_report_categories(cats_raw):
                    cat_counts_today[name] += 1

            report_counts_today = [{'category': k, 'count': v} for k, v in cat_counts_today.items() if v > 0]
            report_counts_today.sort(key=lambda x: (-x['count'], x['category'].casefold()))
        except Exception:
            report_counts = []
            report_counts_today = []
        return report_counts, report_counts_today

    def get_feed_sidebar_counts(selected_city: str, viewer=None):
        viewer_id = getattr(viewer, 'id', None) if viewer and getattr(viewer, 'is_authenticated', False) else None
        blocked_ids = blocked_user_ids_for(viewer) if viewer and getattr(viewer, 'is_authenticated', False) else set()
        cache_key = ('feed_sidebar', viewer_id, selected_city, tuple(sorted(blocked_ids)))
        cached_payload = get_runtime_cached_payload(cache_key, 20)
        if cached_payload is not None:
            return cached_payload.get('report_counts') or [], cached_payload.get('report_counts_today') or []

        query, _ = build_feed_posts_query(selected_city, viewer, eager=False)
        report_counts, report_counts_today = compute_feed_sidebar_counts(query)
        payload = {
            'report_counts': report_counts,
            'report_counts_today': report_counts_today,
        }
        set_runtime_cached_payload(cache_key, payload, ttl_seconds=20, max_entries=64)
        _feed_sidebar_cache[(viewer_id, selected_city, tuple(sorted(blocked_ids)))] = {
            'ts': time.time(),
            **payload,
        }
        return report_counts, report_counts_today

    def get_runtime_cache_client():
        nonlocal _runtime_cache_client, _runtime_cache_client_failed
        if _runtime_cache_client_failed:
            return None
        if _runtime_cache_client is not None:
            return _runtime_cache_client
        if redis is None:
            _runtime_cache_client_failed = True
            return None
        redis_url = (app.config.get('REDIS_URL') or '').strip()
        if not redis_url:
            _runtime_cache_client_failed = True
            return None
        try:
            client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
                retry_on_timeout=False,
            )
            client.ping()
            _runtime_cache_client = client
            return _runtime_cache_client
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
            _runtime_cache_client_failed = True
            return None

    def runtime_cache_key_string(cache_key: tuple) -> str:
        prefix = str(cache_key[0]) if cache_key else 'cache'
        raw = json.dumps(cache_key, ensure_ascii=False, default=str, separators=(',', ':'))
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        namespace = (app.config.get('CACHE_NAMESPACE') or 'violeta').strip() or 'violeta'
        return f'{namespace}:cache:{prefix}:{digest}'

    def get_runtime_cached_payload(cache_key: tuple, ttl_seconds: float):
        now_ts = time.time()
        cached = _runtime_response_cache.get(cache_key)
        if cached:
            if (now_ts - float(cached.get('ts') or 0)) < float(ttl_seconds):
                return cached.get('payload')
            _runtime_response_cache.pop(cache_key, None)

        redis_client = get_runtime_cache_client()
        if redis_client is not None:
            try:
                raw = redis_client.get(runtime_cache_key_string(cache_key))
                if raw:
                    cached = json.loads(raw)
                    if (now_ts - float(cached.get('ts') or 0)) < float(ttl_seconds):
                        _runtime_response_cache[cache_key] = cached
                        return cached.get('payload')
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        return None

    def set_runtime_cached_payload(cache_key: tuple, payload, *, ttl_seconds: float = 15, max_entries: int = 128):
        wrapped = {
            'ts': time.time(),
            'payload': payload,
        }
        _runtime_response_cache[cache_key] = wrapped
        redis_client = get_runtime_cache_client()
        if redis_client is not None:
            try:
                redis_client.set(
                    runtime_cache_key_string(cache_key),
                    json.dumps(wrapped, ensure_ascii=False, separators=(',', ':')),
                    ex=max(int(ttl_seconds * 4), 30),
                )
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        if len(_runtime_response_cache) > max_entries:
            oldest_key = min(_runtime_response_cache, key=lambda key: float(_runtime_response_cache[key].get('ts') or 0))
            _runtime_response_cache.pop(oldest_key, None)
        return payload

    def get_cached_html_page(cache_key: tuple, ttl_seconds: float):
        now_ts = time.time()
        cached = _runtime_response_cache.get(cache_key)
        if not cached:
            return None
        if (now_ts - float(cached.get('ts') or 0)) >= float(ttl_seconds):
            _runtime_response_cache.pop(cache_key, None)
            return None
        cached_html = cached.get('payload')
        if not cached_html:
            return None
        response = make_response(cached_html)
        response.mimetype = 'text/html'
        return response

    def set_cached_html_page(cache_key: tuple, html: str, *, ttl_seconds: float = 15, max_entries: int = 128):
        _runtime_response_cache[cache_key] = {
            'ts': time.time(),
            'payload': html,
        }
        if len(_runtime_response_cache) > max_entries:
            oldest_key = min(_runtime_response_cache, key=lambda key: float(_runtime_response_cache[key].get('ts') or 0))
            _runtime_response_cache.pop(oldest_key, None)
        response = make_response(html)
        response.mimetype = 'text/html'
        return response

    def maybe_process_overdue_checkins(user_id: int | None = None, *, ttl_seconds: float = 30):
        cache_scope = user_id if user_id is not None else 'all'
        cache_key = ('checkins_overdue_refresh', cache_scope)
        if get_runtime_cached_payload(cache_key, ttl_seconds) is not None:
            return 0
        refreshed = process_overdue_checkins(user_id)
        set_runtime_cached_payload(cache_key, True, ttl_seconds=ttl_seconds, max_entries=64)
        return refreshed

    def invalidate_runtime_response_cache(prefix: str | None = None):
        if prefix is None:
            _runtime_response_cache.clear()
            redis_client = get_runtime_cache_client()
            if redis_client is not None:
                try:
                    namespace = (app.config.get('CACHE_NAMESPACE') or 'violeta').strip() or 'violeta'
                    keys = list(redis_client.scan_iter(match=f'{namespace}:cache:*'))
                    if keys:
                        redis_client.delete(*keys)
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
            return
        keys_to_drop = [key for key in _runtime_response_cache.keys() if key and key[0] == prefix]
        for key in keys_to_drop:
            _runtime_response_cache.pop(key, None)
        redis_client = get_runtime_cache_client()
        if redis_client is not None:
            try:
                namespace = (app.config.get('CACHE_NAMESPACE') or 'violeta').strip() or 'violeta'
                keys = list(redis_client.scan_iter(match=f'{namespace}:cache:{prefix}:*'))
                if keys:
                    redis_client.delete(*keys)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)

    def invalidate_admin_panel_page_cache() -> None:
        invalidate_runtime_response_cache('page_admin_shell')
        invalidate_runtime_response_cache('page_admin_content')
        invalidate_runtime_response_cache('page_admin_overview')

    ADMIN_PANEL_CACHE_VERSION = '20260409-admin-mobile-v2'

    def enrich_posts_for_cards(posts, viewer=None):
        if not posts:
            return posts

        post_ids = [getattr(post, 'id', None) for post in posts]
        post_ids = [pid for pid in post_ids if pid is not None]
        if not post_ids:
            return posts

        like_counts = dict(
            db.session.query(Like.post_id, func.count(Like.id))
            .filter(Like.post_id.in_(post_ids))
            .group_by(Like.post_id)
            .all()
        )
        comment_counts = dict(
            db.session.query(Comment.post_id, func.count(Comment.id))
            .filter(Comment.post_id.in_(post_ids))
            .group_by(Comment.post_id)
            .all()
        )

        liked_post_ids = set()
        if viewer and getattr(viewer, 'is_authenticated', False):
            liked_post_ids = {
                row[0]
                for row in db.session.query(Like.post_id)
                .filter(Like.post_id.in_(post_ids), Like.user_id == viewer.id)
                .all()
            }

        for post in posts:
            pid = getattr(post, 'id', None)
            setattr(post, 'likes_count', int(like_counts.get(pid, 0)))
            setattr(post, 'comments_count', int(comment_counts.get(pid, 0)))
            setattr(post, 'liked_by_me', pid in liked_post_ids)
        return posts

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
        path = request.path or ''
        method = (request.method or 'GET').upper()

        if path == '/service-worker.js':
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['Service-Worker-Allowed'] = '/'
        elif path.startswith('/static/'):
            response.headers['Cache-Control'] = 'public, max-age=86400, immutable'
            response.headers.pop('Pragma', None)
            response.headers.pop('Expires', None)
        elif method == 'GET' and path.startswith('/uploads/') and not path.startswith('/uploads/verify/'):
            response.headers['Cache-Control'] = 'public, max-age=300'
            response.headers.pop('Pragma', None)
            response.headers.pop('Expires', None)
        elif method == 'GET' and path == '/api/chat/rooms':
            response.headers['Cache-Control'] = 'private, max-age=3, stale-while-revalidate=10'
            response.headers.pop('Pragma', None)
            response.headers.pop('Expires', None)
        elif method == 'GET' and (
            path == '/api/feed/sidebar-summary'
            or path == '/api/hotspots'
            or path == '/api/posts-by-city'
            or path == '/api/posts-in-radius'
        ):
            response.headers['Cache-Control'] = 'private, max-age=15, stale-while-revalidate=30'
            response.headers.pop('Pragma', None)
            response.headers.pop('Expires', None)
        elif method == 'GET' and (
            path == '/admin'
            or path == '/admin/content'
            or path == '/admin/overview'
            or path == '/admin/tab-content'
            or path == '/safety'
            or path == '/safety/content'
            or (path.startswith('/user/') and path.count('/') in (2, 3))
        ):
            response.headers['Cache-Control'] = 'private, max-age=20, stale-while-revalidate=60'
            response.headers.pop('Pragma', None)
            response.headers.pop('Expires', None)
        else:
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


    @app.route('/service-worker.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'service-worker.js', mimetype='application/javascript')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Service-Worker-Allowed'] = '/'
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
            moderation_badge_level=moderation_badge_level,
            media_url=media_url,
            avatar_url_for_user=avatar_url_for_user,
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
        per_page = app.config.get('FEED_PAGE_SIZE', 3)
        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        page_cache_key = ('page_home', current_user.id, selected_city, page, per_page, tuple(sorted(blocked_ids)))
        cached_response = get_cached_html_page(page_cache_key, 20)
        if cached_response is not None:
            return cached_response

        query, _ = build_feed_posts_query(selected_city, current_user, eager=True)
        report_counts = []
        report_counts_today = []

        posts = query.paginate(page=page, per_page=per_page, error_out=False)
        enrich_posts_for_cards(posts.items, current_user)

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

        html = render_template(
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
        return set_cached_html_page(page_cache_key, html, ttl_seconds=20, max_entries=96)

    @app.route('/api/feed/sidebar-summary')
    @login_required
    def api_feed_sidebar_summary():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        selected_city = (request.args.get('city') or 'all').strip().lower()
        report_counts, report_counts_today = get_feed_sidebar_counts(selected_city, current_user)
        return jsonify({
            'report_counts': report_counts,
            'report_counts_today': report_counts_today,
        })

    @app.route('/feed')
    def feed():
        selected_city = (request.args.get('city') or 'all').strip().lower()
        page = request.args.get('page', 1, type=int)
        per_page = app.config.get('FEED_PAGE_SIZE', 3)
        viewer_id = getattr(current_user, 'id', None) if current_user.is_authenticated else None
        query, blocked_ids = build_feed_posts_query(selected_city, current_user, eager=True)
        cache_key = ('feed_page', viewer_id, selected_city, page, per_page, tuple(sorted(blocked_ids)))
        cached_payload = get_runtime_cached_payload(cache_key, 20)
        if cached_payload is not None:
            return jsonify(cached_payload)

        posts = query.paginate(page=page, per_page=per_page, error_out=False)
        enrich_posts_for_cards(posts.items, current_user)
        html = render_template('_post_cards.html', posts=posts.items)
        data = []
        for p in posts.items:
            try:
                image_url = media_url(getattr(p, 'image_filename', None))
                liked_by_me = bool(getattr(p, 'liked_by_me', False))
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
                    'likes_count': int(getattr(p, 'likes_count', 0)),
                    'comments_count': int(getattr(p, 'comments_count', 0)),
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
        payload = {
            'posts': data,
            'html': html,
            'has_next': posts.has_next,
            'page': page,
            'next_page': page + 1 if posts.has_next else None,
        }
        set_runtime_cached_payload(cache_key, payload, ttl_seconds=20, max_entries=96)
        return jsonify(payload)

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


    @app.route('/account-restricted')
    @login_required
    def account_restricted():
        state = user_restriction_state(current_user, auto_clear=True)
        if not state:
            return redirect(url_for('index'))
        return render_template('account_restricted.html', restriction=state)

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
                restriction = user_restriction_state(user, auto_clear=True)
                if restriction:
                    flash(restriction.get('message') or 'Tu cuenta tiene una restricción activa.', 'warning')
                    return redirect(url_for('account_restricted'))
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

        capture_source = (request.form.get('capture_source') or '').strip().lower()
        capture_lat = parse_float((request.form.get('capture_latitude') or '').strip())
        capture_lng = parse_float((request.form.get('capture_longitude') or '').strip())
        capture_accuracy = parse_float((request.form.get('capture_accuracy') or '').strip())
        capture_speed_mps = parse_float((request.form.get('capture_speed_mps') or '').strip())
        capture_taken_at = (request.form.get('capture_taken_at') or '').strip()[:64]
        capture_motion_state = normalize_capture_motion_state(request.form.get('capture_motion_state'))
        capture_location_name = (request.form.get('capture_location_name') or '').strip()
        capture_city = (request.form.get('capture_city') or '').strip()
        capture_country = (request.form.get('capture_country') or '').strip()
        if not user_can_override_content_controls(current_user) and capture_source != 'camera':
            flash('Por seguridad, la publicación debe capturarse en el momento con la cámara.', 'danger')
            return redirect(url_for('index'))
        if not user_can_override_content_controls(current_user) and capture_motion_state not in {'stationary', 'walking'}:
            flash('Por seguridad, solo puedes reportar si estás detenida o caminando al tomar la foto.', 'danger')
            return redirect(url_for('index'))
        if not user_can_override_content_controls(current_user) and not valid_coords(capture_lat, capture_lng):
            flash('Necesitamos la ubicación exacta del lugar donde tomaste la foto para publicar.', 'danger')
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

        if ext in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}:
            strip_image_metadata_in_place(save_path)

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

        if not sync_public_upload_to_storage(unique_name, local_path=save_path):
            try:
                os.remove(save_path)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            flash('No se pudo publicar la imagen en el almacenamiento externo.', 'danger')
            return redirect(url_for('index'))

        # Campos del formulario (con fallback a request.form)
        caption = safe_field(form, 'caption') or ''
        lat = parse_float(safe_field(form, 'latitude'))
        lng = parse_float(safe_field(form, 'longitude'))
        loc_source = (safe_field(form, 'loc_source') or '').lower()
        if not user_can_override_content_controls(current_user):
            lat = capture_lat
            lng = capture_lng
            loc_source = 'capture'

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
                print('DEBUG: Capture motion -> state:', capture_motion_state, 'speed:', capture_speed_mps, 'accuracy:', capture_accuracy, 'taken_at:', capture_taken_at)
                print('DEBUG: Categories:', categories)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        # Admin puede continuar sin ubicación válida; publicaciones normales usan la
        # ubicación exacta congelada al momento de la captura.
        if not valid_coords(lat, lng):
            lat = None
            lng = None

        location_name = safe_field(form, 'location_name')
        city = safe_field(form, 'city')
        country = safe_field(form, 'country')
        if not user_can_override_content_controls(current_user):
            location_name = capture_location_name or location_name
            city = capture_city or city
            country = capture_country or country

        # Programación de publicación
        now = datetime.now()
        publish_at = now
        if not user_can_override_content_controls(current_user):
            publish_at = now + timedelta(minutes=safety_publish_fallback_minutes())
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
                from urllib.parse import urlencode, quote
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
                    user_can_override_content_controls(current_user)
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
        invalidate_post_discovery_caches()
        # Mensajes según programación
        if not user_can_override_content_controls(current_user):
            policy = safety_publish_policy_payload()
            flash(
                f"Tu publicación se hará pública cuando pasen {policy['min_delay_minutes']} min y estés al menos a "
                f"{policy['distance_meters']} m del punto del reporte, o en máximo {policy['fallback_minutes']} min.",
                'info'
            )
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

    @app.route('/api/posts/pending-safety/status')
    @login_required
    def api_pending_safety_status():
        summary = summarize_pending_safety_posts_for_user(current_user)
        return jsonify({'ok': True, **summary})

    @app.route('/api/posts/pending-safety/release', methods=['POST'])
    @login_required
    def api_pending_safety_release():
        payload = request.get_json(silent=True) or request.form or {}
        lat = parse_float(payload.get('lat'))
        lng = parse_float(payload.get('lng'))
        result = try_release_pending_safety_posts_for_user(current_user, lat, lng)
        return jsonify({'ok': True, **result})

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return send_from_directory(os.path.join(os.path.dirname(__file__), 'static', 'images'), 'default_avatar.jpg')

        normalized = (filename or '').replace('\\', '/').lstrip('/')
        # Protect sensitive verification artifacts.
        if normalized.startswith('verify/'):
            if not current_user.is_authenticated:
                abort(403)
            if not user_can_override_content_controls(current_user):
                own_req = VerificationRequest.query.filter_by(user_id=current_user.id).first()
                if not own_req or (own_req.video_filename or '').strip() != normalized:
                    abort(403)

        external_url = public_upload_storage_url(normalized)
        if external_url:
            return redirect(external_url, code=302)

        folder = ensure_upload_folder()
        return send_from_directory(folder, normalized)

    @app.route('/post/<int:post_id>')
    def post_detail(post_id):
        post = Post.query.options(
            selectinload(Post.author),
            selectinload(Post.meta),
        ).get_or_404(post_id)
        if current_user.is_authenticated and is_user_blocked_between(current_user.id, post.user_id):
            abort(404)
        if not is_public_post(post) and (not current_user.is_authenticated or not user_can_review_private_content(current_user)):
            abort(404)
        enrich_posts_for_cards([post], current_user)
        comment_form = CommentForm()
        share_form = ShareForm()
        return render_template('post_detail.html', post=post, comment_form=comment_form, share_form=share_form)

    def media_url(filename: str | None, fallback_static: str | None = None) -> str:
        normalized = (filename or '').strip()
        if normalized:
            external = public_upload_storage_url(normalized)
            if external:
                return external
            local_public = local_public_upload_url(normalized)
            if local_public:
                return local_public
            return url_for('uploaded_file', filename=normalized)
        if fallback_static:
            return url_for('static', filename=fallback_static)
        return ''

    def avatar_url_for_user(user) -> str:
        try:
            pic = (getattr(user, 'profile_pic', None) or '').strip()
            if pic and pic != 'default.jpg':
                return media_url(pic)
        except Exception as exc:
            _debug_log_suppressed('suppressed exception', exc)
        return url_for('static', filename='images/default_avatar.jpg')

    def _avatar_url(user):
        return avatar_url_for_user(user)

    @app.route('/comments/<int:post_id>')
    def comments(post_id):
        post_row = (
            db.session.query(
                Post.id,
                Post.user_id,
                Post.publish_at,
                PostMeta.show_public,
            )
            .outerjoin(PostMeta, PostMeta.post_id == Post.id)
            .filter(Post.id == post_id)
            .first()
        )
        if not post_row:
            abort(404)

        if current_user.is_authenticated and is_user_blocked_between(current_user.id, post_row.user_id):
            return jsonify({'comments': [], 'hidden_comments': []})

        is_public = (
            (getattr(post_row, 'publish_at', None) is None or post_row.publish_at <= datetime.now())
            and (getattr(post_row, 'show_public', None) is None or bool(post_row.show_public))
        )
        if not is_public and (not current_user.is_authenticated or not user_can_review_private_content(current_user)):
            return jsonify({'comments': [], 'hidden_comments': []})

        visible_comments = []
        hidden_comments = []
        rows = (
            db.session.query(
                Comment.id,
                Comment.user_id,
                Comment.content,
                Comment.created_at,
                Comment.is_hidden,
                User.username,
                User.profile_pic,
                User.abuse_strikes,
                User.roles,
            )
            .join(User, User.id == Comment.user_id)
            .filter(Comment.post_id == post_id)
            .order_by(Comment.created_at.asc(), Comment.id.asc())
            .all()
        )
        for row in rows:
            try:
                username = getattr(row, 'username', 'unknown')
                strikes = int(getattr(row, 'abuse_strikes', 0) or 0)
                is_staff_badged = ROLE_SUPER_ADMIN in {
                    chunk.strip().lower()
                    for chunk in str(getattr(row, 'roles', '') or '').split(',')
                    if chunk.strip()
                }
                moderation_level = 0 if is_staff_badged else (2 if strikes >= 2 else 1 if strikes >= 1 else 0)
                payload = {
                    'id': row.id,
                    'user_id': row.user_id,
                    'username': username,
                    'profile_pic': media_url(getattr(row, 'profile_pic', None), 'images/default_avatar.jpg'),
                    'content': row.content,
                    'created_at': row.created_at.isoformat() if getattr(row, 'created_at', None) else None,
                    'moderation_level': moderation_level,
                    'is_super_admin': is_staff_badged,
                    'is_hidden': bool(getattr(row, 'is_hidden', False)),
                }
                if payload['is_hidden']:
                    hidden_comments.append({
                        **payload,
                        'content': 'Este comentario ha sido reportado',
                    })
                else:
                    visible_comments.append(payload)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        return jsonify({'comments': visible_comments, 'hidden_comments': hidden_comments})


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
        previous_video = (req.video_filename or '').strip()
        try:
            file.save(save_path)
        except Exception:
            return jsonify({'error': 'No se pudo guardar el video.'}), 500
        req.video_filename = f"verify/{unique_name}"
        db.session.add(req)
        db.session.commit()
        if previous_video and previous_video != req.video_filename:
            safe_remove_upload(previous_video)
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

            posts = posts[:50]
            enrich_posts_for_cards(posts, current_user)

            for p in posts:
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
                    'image_url': media_url(p.image_filename),
                    'created_at': p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
                    'likes_count': int(getattr(p, 'likes_count', 0)),
                    'comments_count': int(getattr(p, 'comments_count', 0)),
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
        limit = request.args.get('limit', type=int)
        viewer_id = getattr(current_user, 'id', None) if current_user.is_authenticated else None
        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        cache_key = (
            'hotspots',
            viewer_id,
            tuple(sorted(blocked_ids)),
            round(c_lat, 4) if c_lat is not None else None,
            round(c_lng, 4) if c_lng is not None else None,
            round(float(radius or 0), 3),
            int(precision or 3),
            (category or '').strip().casefold(),
            int(limit) if limit else None,
        )
        cached_payload = get_runtime_cached_payload(cache_key, 15)
        if cached_payload is not None:
            return jsonify(cached_payload)

        q = public_posts_query(
            Post.query.options(selectinload(Post.tags))
        ).filter(
            Post.latitude.isnot(None),
            Post.longitude.isnot(None),
        )
        if blocked_ids:
            q = q.filter(~Post.user_id.in_(blocked_ids))
        if c_lat is not None and c_lng is not None:
            lat_margin = max(radius / 110.57, 0.01)
            cos_lat = max(abs(cos(radians(c_lat))), 0.2)
            lng_margin = max(radius / (111.32 * cos_lat), 0.01)
            q = q.filter(
                Post.latitude.between(c_lat - lat_margin, c_lat + lat_margin),
                Post.longitude.between(c_lng - lng_margin, c_lng + lng_margin),
            )

        posts = q.all()
        post_ids = [p.id for p in posts]
        like_counts = {}
        if post_ids:
            like_counts = dict(
                db.session.query(Like.post_id, func.count(Like.id))
                .filter(Like.post_id.in_(post_ids))
                .group_by(Like.post_id)
                .all()
            )
        buckets = {}

        for p in posts:
            if not match_category(p, category):
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
                info['likes'] += int(like_counts.get(p.id, 0))
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
        if limit and limit > 0:
            payload = payload[:limit]
        payload_wrapper = {'hotspots': payload}
        set_runtime_cached_payload(cache_key, payload_wrapper, ttl_seconds=15, max_entries=160)
        return jsonify(payload_wrapper)

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
        viewer_id = getattr(current_user, 'id', None) if current_user.is_authenticated else None
        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        cache_key = (
            'posts_in_radius',
            viewer_id,
            tuple(sorted(blocked_ids)),
            round(c_lat, 4),
            round(c_lng, 4),
            round(float(radius or 0), 3),
            (category or '').strip().casefold(),
        )
        cached_payload = get_runtime_cached_payload(cache_key, 8)
        if cached_payload is not None:
            return jsonify(cached_payload)

        def within_radius(p_lat, p_lng, c_lat, c_lng, radius_km=1.0):
            try:
                from math import cos, radians, sqrt
                dx = (p_lng - c_lng) * cos(radians((p_lat + c_lat) / 2)) * 111.32
                dy = (p_lat - c_lat) * 110.57
                dist = sqrt(dx*dx + dy*dy)
                return dist <= radius_km
            except Exception:
                return False

        lat_margin = max(radius / 110.57, 0.01)
        cos_lat = max(abs(cos(radians(c_lat))), 0.2)
        lng_margin = max(radius / (111.32 * cos_lat), 0.01)
        posts_query = public_posts_query(
            Post.query.options(
                selectinload(Post.author),
                selectinload(Post.meta),
                selectinload(Post.tags),
            )
        ).filter(
            Post.latitude.isnot(None),
            Post.longitude.isnot(None),
            Post.latitude.between(c_lat - lat_margin, c_lat + lat_margin),
            Post.longitude.between(c_lng - lng_margin, c_lng + lng_margin),
        )
        if blocked_ids:
            posts_query = posts_query.filter(~Post.user_id.in_(blocked_ids))
        posts = posts_query.order_by(Post.created_at.desc()).limit(100).all()
        visible_posts = []
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
                visible_posts.append(p)
        enrich_posts_for_cards(visible_posts, current_user)
        for p in visible_posts:
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
                    'image_url': media_url(p.image_filename),
                    'created_at': p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
                    'likes_count': int(getattr(p, 'likes_count', 0)),
                    'comments_count': int(getattr(p, 'comments_count', 0)),
                    'latitude': loc.get('lat'),
                    'longitude': loc.get('lng'),
                    'location_name': loc.get('name'),
                    'location_visibility': loc.get('visibility'),
                    'categories': categories,
                })
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        payload = {'posts': data}
        set_runtime_cached_payload(cache_key, payload, ttl_seconds=8, max_entries=160)
        return jsonify(payload)

    @app.route('/api/posts-by-city')
    def api_posts_by_city():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        """Filtra posts por ciudad usando coordenadas."""
        city = (request.args.get('city') or '').strip().lower()
        viewer_id = getattr(current_user, 'id', None) if current_user.is_authenticated else None
        blocked_ids = blocked_user_ids_for(current_user) if current_user.is_authenticated else set()
        cache_key = (
            'posts_by_city',
            viewer_id,
            tuple(sorted(blocked_ids)),
            city or 'all',
        )
        cached_payload = get_runtime_cached_payload(cache_key, 8)
        if cached_payload is not None:
            return jsonify(cached_payload)

        filtered_query, _ = build_feed_posts_query(city or 'all', current_user, eager=True)
        filtered = filtered_query.limit(50).all()
        enrich_posts_for_cards(filtered, current_user)

        data = []
        for p in filtered:
            try:
                author = p.author
                pic = avatar_url_for_user(author)
                loc = public_location_for_post(p, current_user)
                data.append({
                    'id': p.id,
                    'username': author.username if author else 'unknown',
                    'profile_pic': pic,
                    'caption': p.caption,
                    'image_url': media_url(p.image_filename),
                    'likes_count': int(getattr(p, 'likes_count', 0)),
                    'comments_count': int(getattr(p, 'comments_count', 0)),
                    'location_name': loc.get('name'),
                    'latitude': loc.get('lat'),
                    'longitude': loc.get('lng'),
                    'location_visibility': loc.get('visibility'),
                    'liked_by_me': bool(getattr(p, 'liked_by_me', False)),
                })
            except Exception as exc:
                _debug_log_suppressed('suppressed bare exception', exc)
        payload = {'posts': data}
        set_runtime_cached_payload(cache_key, payload, ttl_seconds=8, max_entries=160)
        return jsonify(payload)

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

            blocked_ids = blocked_user_ids_for(current_user)
            cache_key = (
                'chat_rooms',
                current_user.id,
                tuple(sorted(blocked_ids)),
            )
            cached_payload = get_runtime_cached_payload(cache_key, 3)
            if cached_payload is not None:
                return jsonify(cached_payload)
            rooms_query = ChatRoom.query.filter(ChatRoom.is_approved.is_(True))
            if blocked_ids:
                rooms_query = rooms_query.filter(or_(ChatRoom.created_by.is_(None), ~ChatRoom.created_by.in_(blocked_ids)))
            all_rooms = rooms_query.order_by(ChatRoom.created_at.desc()).all()
            room_ids = [room.id for room in all_rooms]
            if not room_ids:
                payload = {'rooms': []}
                set_runtime_cached_payload(cache_key, payload, ttl_seconds=3, max_entries=96)
                return jsonify(payload)

            participants = {
                p.room_id: p
                for p in ChatParticipant.query.filter(
                    ChatParticipant.user_id == current_user.id,
                    ChatParticipant.room_id.in_(room_ids),
                ).all()
            }
            last_message_ids = dict(
                db.session.query(ChatMessage.room_id, func.max(ChatMessage.id))
                .filter(ChatMessage.room_id.in_(room_ids))
                .group_by(ChatMessage.room_id)
                .all()
            )
            last_messages_by_room = {}
            if last_message_ids:
                last_messages = ChatMessage.query.options(selectinload(ChatMessage.user)).filter(
                    ChatMessage.id.in_(list(last_message_ids.values()))
                ).all()
                last_messages_by_room = {message.room_id: message for message in last_messages}

            unread_counts = {}
            last_unread_message_ids = {}
            participant_room_ids = list(participants.keys())
            if participant_room_ids:
                unread_rows_query = (
                    db.session.query(
                        ChatMessage.room_id,
                        func.count(ChatMessage.id),
                        func.max(ChatMessage.id),
                    )
                    .join(
                        ChatParticipant,
                        and_(
                            ChatParticipant.room_id == ChatMessage.room_id,
                            ChatParticipant.user_id == current_user.id,
                        ),
                    )
                    .filter(
                        ChatMessage.room_id.in_(participant_room_ids),
                        ChatMessage.user_id != current_user.id,
                        ChatMessage.is_deleted.is_(False),
                        or_(
                            ChatParticipant.last_read_at.is_(None),
                            ChatMessage.created_at > ChatParticipant.last_read_at,
                        ),
                    )
                )
                if blocked_ids:
                    unread_rows_query = unread_rows_query.filter(~ChatMessage.user_id.in_(blocked_ids))
                unread_rows = unread_rows_query.group_by(ChatMessage.room_id).all()
                unread_counts = {
                    int(room_id): int(count or 0)
                    for room_id, count, _ in unread_rows
                }
                last_unread_message_ids = {
                    int(room_id): int(last_id)
                    for room_id, _, last_id in unread_rows
                    if last_id is not None
                }

            last_unread_messages_by_room = {}
            if last_unread_message_ids:
                unread_messages = ChatMessage.query.options(selectinload(ChatMessage.user)).filter(
                    ChatMessage.id.in_(list(last_unread_message_ids.values()))
                ).all()
                last_unread_messages_by_room = {message.room_id: message for message in unread_messages}

            rooms = []
            for room in all_rooms:
                participant = participants.get(room.id)
                last_message = last_messages_by_room.get(room.id)
                unread_count = int(unread_counts.get(room.id, 0))
                last_unread_message_data = None
                if unread_count > 0:
                    last_unread = last_unread_messages_by_room.get(room.id)
                    if last_unread:
                        last_unread_attachment_url = None
                        if last_unread.attachment_filename:
                            last_unread_attachment_url = media_url(last_unread.attachment_filename)
                        last_unread_message_data = {
                            'id': last_unread.id,
                            'content': last_unread.content,
                            'username': last_unread.user.username if getattr(last_unread, 'user', None) else None,
                            'is_super_admin': user_has_staff_badge(last_unread.user) if getattr(last_unread, 'user', None) else False,
                            'created_at': last_unread.created_at.isoformat() if last_unread.created_at else None,
                            'message_type': last_unread.message_type,
                            'attachment_name': last_unread.attachment_name,
                            'attachment_url': last_unread_attachment_url,
                            'attachment_mime': last_unread.attachment_mime,
                            'is_deleted': False,
                        }

                image_url = media_url(getattr(room, 'image_filename', None), 'images/favicon.png')
                is_owner = room.created_by == current_user.id
                can_post = True
                if getattr(room, 'messages_open', True) is False:
                    can_post = user_has_permission(current_user, PERM_CHAT_ROOMS_OVERRIDE) or is_owner
                last_is_deleted = bool(getattr(last_message, 'is_deleted', False)) if last_message else False
                last_deleted_reason = chat_message_deleted_reason(last_message) if last_is_deleted else None
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
                        'id': last_message.id if last_message else None,
                        'content': '' if last_is_deleted else (last_message.content if last_message else None),
                        'username': last_message.user.username if last_message and getattr(last_message, 'user', None) else None,
                        'is_super_admin': user_has_staff_badge(last_message.user) if last_message and getattr(last_message, 'user', None) else False,
                        'created_at': last_message.created_at.isoformat() if last_message else None,
                        'message_type': last_message.message_type if last_message else None,
                        'attachment_name': None if last_is_deleted else (last_message.attachment_name if last_message else None),
                        'attachment_url': media_url(last_message.attachment_filename) if last_message and last_message.attachment_filename and not last_is_deleted else None,
                        'is_deleted': last_is_deleted,
                        'deleted_reason': last_deleted_reason,
                    } if last_message else None,
                    'last_unread_message': last_unread_message_data,
                    'unread_count': unread_count,
                    'participants_count': 0,
                })

            payload = {'rooms': rooms}
            set_runtime_cached_payload(cache_key, payload, ttl_seconds=3, max_entries=96)
            return jsonify(payload)
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
            invalidate_runtime_response_cache('chat_rooms')
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

            # Update last read time
            participant.last_read_at = utc_now_naive()
            db.session.commit()

            # Get messages with pagination
            page = request.args.get('page', 1, type=int)
            per_page = 50
            blocked_ids = blocked_user_ids_for(current_user)
            messages_query = ChatMessage.query.options(selectinload(ChatMessage.user)).filter_by(room_id=room_id)
            if blocked_ids:
                messages_query = messages_query.filter(~ChatMessage.user_id.in_(blocked_ids))
            messages_query = messages_query.order_by(ChatMessage.created_at.desc())
            messages_paginated = messages_query.paginate(page=page, per_page=per_page, error_out=False)
            page_messages = list(messages_paginated.items)
            message_ids = [msg.id for msg in page_messages]
            reported_ids = set()
            if message_ids:
                reported_ids = {
                    row[0]
                    for row in db.session.query(ChatMessageReport.message_id)
                    .filter(ChatMessageReport.message_id.in_(message_ids))
                    .filter(ChatMessageReport.status.in_(('reviewing', 'struck')))
                    .all()
                }

            messages = []
            for msg in page_messages:
                is_deleted = bool(getattr(msg, 'is_deleted', False))
                deleted_reason = chat_message_deleted_reason(msg, reported_ids) if is_deleted else None
                attachment_url = None
                attachment_name = None
                attachment_mime = None
                if not is_deleted and msg.attachment_filename:
                    attachment_url = media_url(msg.attachment_filename)
                    attachment_name = msg.attachment_name
                    attachment_mime = msg.attachment_mime
                messages.append({
                    'id': msg.id,
                    'content': '' if is_deleted else msg.content,
                    'username': msg.user.username if getattr(msg, 'user', None) else 'unknown',
                    'is_super_admin': user_has_staff_badge(msg.user) if getattr(msg, 'user', None) else False,
                    'user_id': msg.user.id if getattr(msg, 'user', None) else None,
                    'user_avatar': avatar_url_for_user(msg.user) if getattr(msg, 'user', None) else url_for('static', filename='images/default_avatar.jpg'),
                    'created_at': msg.created_at.isoformat(),
                    'message_type': msg.message_type,
                    'attachment_name': attachment_name,
                    'attachment_url': attachment_url,
                    'attachment_mime': attachment_mime,
                    'is_deleted': is_deleted,
                    'deleted_reason': deleted_reason,
                    'moderation_level': moderation_badge_level(msg.user),
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
                if not user_has_permission(current_user, PERM_CHAT_ROOMS_OVERRIDE) and room.created_by != current_user.id:
                    return jsonify({'error': 'Solo personal autorizado y la creadora pueden enviar mensajes en esta sala.'}), 403

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
                if ext in {'png', 'jpg', 'jpeg', 'webp', 'bmp'}:
                    strip_image_metadata_in_place(file_path)
                if not sync_public_upload_to_storage(unique_filename, local_path=file_path, mime_type=attachment_file.mimetype):
                    try:
                        os.remove(file_path)
                    except Exception as exc:
                        _debug_log_suppressed('suppressed exception', exc)
                    return jsonify({'error': 'No se pudo guardar el archivo en el almacenamiento externo'}), 500
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
            invalidate_runtime_response_cache('chat_rooms')

            message_data = {
                'id': message.id,
                'content': message.content,
                'username': current_user.username,
                'user_id': current_user.id,
                'user_avatar': avatar_url_for_user(current_user),
                'created_at': message.created_at.isoformat(),
                'message_type': message.message_type,
                'room_id': room_id,
                'attachment_name': message.attachment_name,
                'attachment_url': media_url(message.attachment_filename) if message.attachment_filename else None,
                'attachment_mime': message.attachment_mime,
                'is_deleted': False,
                'deleted_reason': None,
                'moderation_level': moderation_badge_level(current_user),
                'is_super_admin': user_has_staff_badge(current_user),
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
        if not user_has_permission(current_user, PERM_CHAT_ROOMS_MANAGE) and room.created_by != current_user.id:
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
            old_image = (room.image_filename or '').strip()
            unique_name = f"{uuid4().hex}.{filename.rsplit('.', 1)[1].lower()}"
            upload_folder = ensure_upload_folder()
            save_path = os.path.join(upload_folder, unique_name)
            file.save(save_path)
            strip_image_metadata_in_place(save_path)
            if not sync_public_upload_to_storage(unique_name, local_path=save_path, mime_type=file.mimetype):
                try:
                    os.remove(save_path)
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
                return jsonify({'error': 'No se pudo guardar la imagen en el almacenamiento externo'}), 500
            room.image_filename = unique_name
            if old_image and old_image != unique_name:
                safe_remove_upload(old_image)

        db.session.commit()
        invalidate_runtime_response_cache('chat_rooms')

        image_url = media_url(getattr(room, 'image_filename', None), 'images/favicon.png')

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
            is_approved = True if user_has_permission(current_user, PERM_CHAT_ROOMS_MANAGE) else False
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
            invalidate_runtime_response_cache('chat_rooms')

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
            invalidate_runtime_response_cache('chat_rooms')

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
        from urllib.parse import urlencode, quote
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
        from urllib.parse import urlencode, quote
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
        from urllib.parse import urlencode, quote
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
            invalidate_runtime_response_cache('hotspots')
            invalidate_runtime_response_cache('posts_in_radius')
            invalidate_runtime_response_cache('posts_by_city')
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
            result = apply_abuse_strike(
                current_user,
                reason='Lenguaje no permitido en comentario',
                source_type='comment',
                source_label='Comentario automático',
                content_excerpt=content,
            )
            db.session.commit()
            if result.get('applied') and result.get('strike'):
                try:
                    send_moderation_notice_email(current_user, result['strike'])
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
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
            invalidate_runtime_response_cache('posts_in_radius')
            invalidate_runtime_response_cache('posts_by_city')
            return jsonify({
                'ok': True,
                'comment': {
                    'id': c.id,
                    'user_id': current_user.id,
                    'username': current_user.username,
                    'profile_pic': _avatar_url(current_user),
                    'content': c.content,
                    'created_at': c.created_at.isoformat(),
                    'moderation_level': moderation_badge_level(current_user),
                    'is_hidden': False,
                },
                'comments_count': Comment.query.filter_by(post_id=post.id, is_hidden=False).count(),
                'hidden_comments_count': Comment.query.filter_by(post_id=post.id, is_hidden=True).count(),
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
        'Doxxing o datos personales',
        'Ubicación exacta, rastreo o rutina',
        'Amenaza o violencia',
        'Contenido íntimo o sexual sin consentimiento',
        'Suplantación de identidad',
        'Fraude o phishing',
        'Información falso',
        'La imagen no corresponde al evento',
        'La imagen fue hecha con IA',
        'Descripción con lenguaje verbal insultante',
        'La ubicación no corresponde al lugar donde se tomó la foto',
    ]
    CHAT_MESSAGE_REPORT_REASONS = [
        'Doxxing o datos personales',
        'Ubicación exacta, rastreo o rutina',
        'Amenaza o violencia',
        'Contenido íntimo o sexual sin consentimiento',
        'Contenido sexual no solicitado',
        'Archivo o enlace sospechoso',
        'Acoso o insultos',
        'Spam o fraude',
    ]

    COMMENT_REPORT_REASONS = CHAT_MESSAGE_REPORT_REASONS[:]

    POST_HIGH_RISK_REPORT_REASONS = {
        'Doxxing o datos personales',
        'Ubicación exacta, rastreo o rutina',
        'Amenaza o violencia',
        'Contenido íntimo o sexual sin consentimiento',
        'Suplantación de identidad',
        'Fraude o phishing',
    }
    CHAT_MESSAGE_HIGH_RISK_REPORT_REASONS = {
        'Doxxing o datos personales',
        'Ubicación exacta, rastreo o rutina',
        'Amenaza o violencia',
        'Contenido íntimo o sexual sin consentimiento',
        'Contenido sexual no solicitado',
        'Archivo o enlace sospechoso',
    }
    COMMENT_HIGH_RISK_REPORT_REASONS = CHAT_MESSAGE_HIGH_RISK_REPORT_REASONS.copy()
    HIGH_RISK_REPORT_PATTERNS = (
        re.compile(r'(?:google\.com/maps|maps\.app\.goo\.gl|goo\.gl/maps|maps\.apple\.com|waze\.com/ul)', re.IGNORECASE),
        re.compile(r'(?<!\d)-?\d{1,2}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}(?!\d)'),
        re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.IGNORECASE),
        re.compile(r'(?:tel[eé]fono|celular|whatsapp|contacto)[^\n]{0,24}(?:\+?\d[\d\s().-]{7,}\d)', re.IGNORECASE),
    )

    def _report_requires_immediate_hide(source_type: str, reason: str, details: str | None = None, content_excerpt: str | None = None) -> bool:
        if source_type == 'post':
            high_risk_reasons = POST_HIGH_RISK_REPORT_REASONS
        elif source_type == 'comment':
            high_risk_reasons = COMMENT_HIGH_RISK_REPORT_REASONS
        else:
            high_risk_reasons = CHAT_MESSAGE_HIGH_RISK_REPORT_REASONS

        if reason in high_risk_reasons:
            return True

        combined_text = '\n'.join(
            part.strip()
            for part in (details or '', content_excerpt or '')
            if part and part.strip()
        )
        if not combined_text:
            return False
        return any(pattern.search(combined_text) for pattern in HIGH_RISK_REPORT_PATTERNS)

    def _mark_report_resolution(report, status: str, admin_note: str | None = None):
        report.status = status
        report.admin_note = (admin_note or '').strip() or None
        report.resolved_at = utc_now_naive()
        report.resolved_by = current_user.id
        db.session.add(report)

    def _mark_related_reports(reports, status: str, admin_note: str | None = None):
        for item in reports:
            _mark_report_resolution(item, status, admin_note)

    ACTIVE_REVIEW_REPORT_STATUSES = ('pending', 'reviewing')

    def _is_active_review_report(report) -> bool:
        return (getattr(report, 'status', None) or 'pending') in ACTIVE_REVIEW_REPORT_STATUSES

    def _attach_active_post_reports(posts) -> None:
        for post in posts or []:
            active_reports = [
                report for report in (getattr(post, 'reports', None) or [])
                if _is_active_review_report(report)
            ]
            active_reports.sort(
                key=lambda report: (
                    getattr(report, 'created_at', None) or datetime.min,
                    getattr(report, 'id', 0) or 0,
                ),
                reverse=True,
            )
            post.active_reports_admin = active_reports

    def _build_checkin_user_groups(checkins) -> list[dict]:
        groups: list[dict] = []
        by_key: dict[object, dict] = {}
        for checkin in checkins or []:
            user = getattr(checkin, 'user', None)
            if user is not None:
                key: object = ('user', user.id)
                username = user.username
            else:
                key = ('deleted', getattr(checkin, 'user_id', None) or getattr(checkin, 'id', None))
                username = 'Usuaria eliminada'

            group = by_key.get(key)
            if group is None:
                group = {
                    'key': f'{key[0]}-{key[1]}',
                    'user': user,
                    'username': username,
                    'checkins': [],
                    'total': 0,
                    'active_count': 0,
                    'latest_started_at': getattr(checkin, 'started_at', None),
                }
                by_key[key] = group
                groups.append(group)

            group['checkins'].append(checkin)
            group['total'] += 1
            if getattr(checkin, 'status', None) == 'active':
                group['active_count'] += 1
            started_at = getattr(checkin, 'started_at', None)
            latest_started_at = group.get('latest_started_at')
            if started_at and (latest_started_at is None or started_at > latest_started_at):
                group['latest_started_at'] = started_at
        return groups

    def _serialize_chat_message_payload(message: ChatMessage):
        is_deleted = bool(getattr(message, 'is_deleted', False))
        attachment_url = None
        attachment_name = None
        attachment_mime = None
        if not is_deleted and message.attachment_filename:
            attachment_url = url_for('uploaded_file', filename=message.attachment_filename)
            attachment_name = message.attachment_name
            attachment_mime = message.attachment_mime
        return {
            'id': message.id,
            'content': '' if is_deleted else (message.content or ''),
            'username': message.user.username if message.user else 'usuaria',
            'user_id': message.user_id,
            'user_avatar': _avatar_url(message.user),
            'created_at': message.created_at.isoformat() if message.created_at else None,
            'message_type': message.message_type,
            'room_id': message.room_id,
            'attachment_name': attachment_name,
            'attachment_url': attachment_url,
            'attachment_mime': attachment_mime,
            'is_deleted': is_deleted,
            'deleted_reason': chat_message_deleted_reason(message),
            'moderation_level': moderation_badge_level(message.user),
            'is_super_admin': user_has_staff_badge(message.user),
        }

    def _emit_message_restored(message: ChatMessage):
        try:
            socketio.emit('message_restored', {
                'room_id': message.room_id,
                'message': _serialize_chat_message_payload(message),
            }, room=f'room_{message.room_id}')
        except Exception as e:
            if app.debug:
                print('DEBUG message_restored emit error:', e)

    def _restore_reported_message(message: ChatMessage, admin_note: str | None = None):
        message.is_deleted = False
        message.deleted_at = None
        message.deleted_by = None
        db.session.add(message)
        _mark_related_reports(message.reports, 'restored', admin_note)

    def _restore_reported_post(post: Post, admin_note: str | None = None):
        meta = PostMeta.query.filter_by(post_id=post.id).first()
        if not meta:
            meta = PostMeta(post_id=post.id)
        meta.show_public = True
        db.session.add(meta)
        _mark_related_reports(post.reports, 'restored', admin_note)

    def _restore_reported_comment(comment: Comment, admin_note: str | None = None):
        comment.is_hidden = False
        comment.hidden_at = None
        comment.hidden_by = None
        comment.hidden_reason = None
        db.session.add(comment)
        _mark_related_reports(comment.reports, 'restored', admin_note)

    def _issue_report_strike(target_user: User, *, report_reason: str, source_type: str, source_id: int | None = None, source_label: str | None = None, details: str | None = None, content_excerpt: str | None = None):
        result = apply_abuse_strike(
            target_user,
            reason=report_reason or 'Incumplimiento de reglas',
            issued_by=current_user,
            source_type=source_type,
            source_id=source_id,
            source_label=source_label,
            details=details,
            content_excerpt=content_excerpt,
        )
        return result

    @app.route('/report_post/<int:post_id>', methods=['POST'])
    @csrf.exempt
    @login_required
    def report_post(post_id):
        if not is_same_origin_request():
            return jsonify({'error': 'Origen inválido'}), 403
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
        if post.user_id == current_user.id and not user_is_protected_staff(current_user):
            return jsonify({'ok': False, 'error': 'No puedes reportar tu propia publicación.'}), 400
        if is_user_blocked_between(current_user.id, post.user_id):
            return jsonify({'ok': False, 'error': 'No puedes reportar contenido de esta cuenta.'}), 403
        existing = Report.query.filter_by(post_id=post.id, reporter_id=current_user.id).first()
        high_risk = _report_requires_immediate_hide(
            'post',
            reason,
            details=details,
            content_excerpt='\n'.join(part for part in (post.caption or '', post.location_name or '') if part),
        )

        try:
            if existing:
                existing.reason = reason
                existing.details = details or None
                existing.status = 'reviewing' if high_risk else 'pending'
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
                report.status = 'reviewing' if high_risk else 'pending'
                db.session.add(report)

            content_hidden = False
            meta = PostMeta.query.filter_by(post_id=post.id).first()
            if high_risk:
                if not meta:
                    meta = PostMeta()  # type: ignore
                    meta.post_id = post.id
                meta.show_public = False
                db.session.add(meta)
                content_hidden = True
            elif meta and meta.show_public is False:
                content_hidden = True

            db.session.commit()
            if high_risk:
                invalidate_runtime_response_cache('hotspots')
                invalidate_runtime_response_cache('posts_in_radius')
                invalidate_runtime_response_cache('posts_by_city')
                invalidate_runtime_response_cache('feed_sidebar')
                _feed_sidebar_cache.clear()

            if high_risk:
                message = 'Reporte de alto riesgo enviado. La publicación se ocultó preventivamente mientras la revisamos.'
            elif content_hidden:
                message = 'Reporte enviado. La publicación ya está oculta mientras el equipo la revisa.'
            else:
                message = 'Reporte enviado a revisión. La publicación seguirá visible hasta que el equipo la revise.'

            return jsonify({
                'ok': True,
                'message': message,
                'report_id': report.id,
                'status': report.status,
                'high_risk': high_risk,
                'hidden_immediately': content_hidden,
            })
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
        user_posts = (
            Post.query.options(
                selectinload(Post.author),
                selectinload(Post.meta),
            )
            .filter_by(user_id=user.id)
            .order_by(Post.created_at.desc())
            .all()
        )
        annotate_user_post_visibility_state(user_posts)
        enrich_posts_for_cards(user_posts, current_user)
        report_count = len(user_posts)
        total_likes = sum((getattr(p, 'likes_count', 0) for p in user_posts), 0)
        total_comments = sum((getattr(p, 'comments_count', 0) for p in user_posts), 0)
        return render_template(
            'profile.html',
            user=user,
            posts=user_posts,
            report_count=report_count,
            total_likes=total_likes,
            total_comments=total_comments,
        )

    def _base_ops_panel_context() -> dict:
        return {
            'users': [],
            'posts': [],
            'total_likes': 0,
            'total_comments': 0,
            'chat_rooms': [],
            'pending_rooms': [],
            'chat_message_reports': [],
            'comment_reports': [],
            'verifications': [],
            'pending_verifications': [],
            'panic_events': [],
            'checkins': [],
            'audit_logs': [],
            'audit_filters': {},
            'audit_filter_options': {'workspaces': [], 'event_types': [], 'days': list(AUDIT_DAYS_FILTER_OPTIONS)},
            'audit_export_url': '',
            'audit_retention_days': audit_log_retention_days(),
            'available_admin_tabs': [],
            'active_admin_tab': 'users',
            'initial_admin_tab': 'users',
            'ops_panel_title': 'Panel de Operaciones',
            'ops_panel_subtitle': 'Resumen de actividad en tiempo real.',
            'show_admin_overview': False,
            'staff_role_options': staff_role_payloads(),
            'active_reports_subtab': 'reportados',
            'reported_posts_count': 0,
            'chat_message_reports_count': 0,
            'comment_reports_count': 0,
            'pending_chat_rooms_count': 0,
            'pending_verifications_count': 0,
            'has_reported_posts': False,
            'has_chat_message_reports': False,
            'has_comment_reports': False,
            'has_pending_chat_rooms': False,
            'has_pending_verifications': False,
            'has_admin_reports_attention': False,
            'has_admin_chats_attention': False,
            'has_admin_verifications_attention': False,
        }

    def _build_admin_attention_state() -> dict:
        reported_posts_count = int(
            db.session.query(func.count(func.distinct(Report.post_id)))
            .filter(
                Report.post_id.isnot(None),
                Report.status.in_(ACTIVE_REVIEW_REPORT_STATUSES),
            )
            .scalar()
            or 0
        )
        chat_message_reports_count = int(
            db.session.query(func.count(ChatMessageReport.id))
            .filter(ChatMessageReport.status.in_(ACTIVE_REVIEW_REPORT_STATUSES))
            .scalar()
            or 0
        )
        comment_reports_count = int(
            db.session.query(func.count(CommentReport.id))
            .filter(CommentReport.status.in_(ACTIVE_REVIEW_REPORT_STATUSES))
            .scalar()
            or 0
        )
        pending_chat_rooms_count = int(
            db.session.query(func.count(ChatRoom.id))
            .filter(ChatRoom.is_approved.is_(False))
            .scalar()
            or 0
        )
        pending_verifications_count = int(
            db.session.query(func.count(VerificationRequest.id))
            .filter(VerificationRequest.status == 'pending')
            .scalar()
            or 0
        )
        has_reported_posts = reported_posts_count > 0
        has_chat_message_reports = chat_message_reports_count > 0
        has_comment_reports = comment_reports_count > 0
        has_pending_chat_rooms = pending_chat_rooms_count > 0
        has_pending_verifications = pending_verifications_count > 0
        return {
            'reported_posts_count': reported_posts_count,
            'chat_message_reports_count': chat_message_reports_count,
            'comment_reports_count': comment_reports_count,
            'pending_chat_rooms_count': pending_chat_rooms_count,
            'pending_verifications_count': pending_verifications_count,
            'has_reported_posts': has_reported_posts,
            'has_chat_message_reports': has_chat_message_reports,
            'has_comment_reports': has_comment_reports,
            'has_pending_chat_rooms': has_pending_chat_rooms,
            'has_pending_verifications': has_pending_verifications,
            'has_admin_reports_attention': has_reported_posts or has_chat_message_reports or has_comment_reports,
            'has_admin_chats_attention': has_pending_chat_rooms,
            'has_admin_verifications_attention': has_pending_verifications,
        }

    def _build_super_admin_overview_context() -> dict:
        return {
            'total_users_count': db.session.query(func.count(User.id)).scalar() or 0,
            'total_posts_count': db.session.query(func.count(Post.id)).scalar() or 0,
            'total_likes': db.session.query(func.count(Like.id)).scalar() or 0,
            'total_comments': db.session.query(func.count(Comment.id)).scalar() or 0,
        }

    def _build_super_admin_ops_context(active_tab: str = 'users', reports_subtab: str = 'reportados', *, include_overview: bool = True, page_number: int = 1) -> dict:
        context = _base_ops_panel_context()
        available_tabs = ['users', 'posts', 'reportes', 'chats', 'verificaciones', 'rutas']
        if active_tab not in available_tabs:
            active_tab = 'users'
        report_subtabs = {'reportados', 'reportes-chat', 'reportes-comentarios'}
        if reports_subtab not in report_subtabs:
            reports_subtab = 'reportados'
        page_number = max(1, int(page_number or 1))

        users_limit = app.config.get('ADMIN_USERS_LIMIT', 12)
        posts_limit = app.config.get('ADMIN_POSTS_LIMIT', 9)
        reported_posts_limit = app.config.get('ADMIN_REPORTED_POSTS_LIMIT', 8)
        chat_rooms_limit = app.config.get('ADMIN_CHAT_ROOMS_LIMIT', 8)
        reports_limit = app.config.get('ADMIN_REPORTS_LIMIT', 8)
        verifications_limit = app.config.get('ADMIN_VERIFICATIONS_LIMIT', 8)
        checkins_limit = app.config.get('ADMIN_CHECKINS_LIMIT', 10)
        panic_events_limit = app.config.get('ADMIN_PANIC_EVENTS_LIMIT', 8)

        context.update({
            'available_admin_tabs': available_tabs,
            'active_admin_tab': active_tab,
            'initial_admin_tab': active_tab,
            'ops_panel_title': 'Panel de Operaciones',
            'ops_panel_subtitle': 'Resumen de actividad en tiempo real.',
            'show_admin_overview': include_overview,
            'active_reports_subtab': reports_subtab,
            'admin_page_number': page_number,
        })
        context.update(_build_admin_attention_state())

        if include_overview:
            context.update(_build_super_admin_overview_context())

        if active_tab == 'users':
            total_users_count = db.session.query(func.count(User.id)).scalar() or 0
            total_pages = max(1, (total_users_count + users_limit - 1) // users_limit) if total_users_count else 1
            page_number = min(page_number, total_pages)
            users = (
                User.query
                .order_by(User.created_at.desc())
                .offset((page_number - 1) * users_limit)
                .limit(users_limit)
                .all()
            )
            user_ids = [user.id for user in users]
            user_post_counts = {}
            user_like_counts = {}
            if user_ids:
                user_post_counts = dict(
                    db.session.query(Post.user_id, func.count(Post.id))
                    .filter(Post.user_id.in_(user_ids))
                    .group_by(Post.user_id)
                    .all()
                )
                user_like_counts = dict(
                    db.session.query(Post.user_id, func.count(Like.id))
                    .join(Like, Like.post_id == Post.id)
                    .filter(Post.user_id.in_(user_ids))
                    .group_by(Post.user_id)
                    .all()
                )
            for user in users:
                user.post_count = int(user_post_counts.get(user.id, 0))
                user.like_count = int(user_like_counts.get(user.id, 0))
            context.update({
                'users': users,
                'total_users_count': total_users_count,
                'tab_total_count': total_users_count,
                'tab_page': page_number,
                'tab_total_pages': total_pages,
                'tab_has_prev': page_number > 1,
                'tab_has_next': page_number < total_pages,
                'tab_page_size': users_limit,
            })
            return context

        if active_tab == 'posts':
            posts_query = public_posts_query(
                Post.query.options(
                    selectinload(Post.author),
                    selectinload(Post.meta),
                )
            ).order_by(Post.created_at.desc())
            total_posts_count = posts_query.order_by(None).count() or 0
            total_pages = max(1, (total_posts_count + posts_limit - 1) // posts_limit) if total_posts_count else 1
            page_number = min(page_number, total_pages)
            posts = posts_query.offset((page_number - 1) * posts_limit).limit(posts_limit).all()
            enrich_posts_for_cards(posts, current_user)
            post_ids = [post.id for post in posts]
            reported_post_ids = set()
            if post_ids:
                reported_post_ids = {
                    int(post_id)
                    for post_id, in db.session.query(Report.post_id)
                    .filter(
                        Report.post_id.in_(post_ids),
                        Report.status.in_(ACTIVE_REVIEW_REPORT_STATUSES),
                    )
                    .distinct()
                    .all()
                }
            for post in posts:
                is_hidden = bool(post.meta and post.meta.show_public is not None and not post.meta.show_public)
                post.is_reported_admin = is_hidden or post.id in reported_post_ids
            context.update({
                'posts': posts,
                'total_posts_count': total_posts_count,
                'tab_total_count': total_posts_count,
                'tab_page': page_number,
                'tab_total_pages': total_pages,
                'tab_has_prev': page_number > 1,
                'tab_has_next': page_number < total_pages,
                'tab_page_size': posts_limit,
            })
            return context

        if active_tab == 'reportes':
            reported_posts = []
            chat_message_reports = []
            comment_reports = []

            if reports_subtab == 'reportados':
                reported_posts = (
                    Post.query.options(
                        selectinload(Post.author),
                        selectinload(Post.meta),
                        selectinload(Post.reports).selectinload(Report.reporter),
                        selectinload(Post.reports).selectinload(Report.resolver),
                    )
                    .filter(
                        Post.reports.any(Report.status.in_(ACTIVE_REVIEW_REPORT_STATUSES))
                    )
                    .order_by(Post.created_at.desc())
                    .limit(reported_posts_limit)
                    .all()
                )
                enrich_posts_for_cards(reported_posts, current_user)
                _attach_active_post_reports(reported_posts)
            elif reports_subtab == 'reportes-chat':
                chat_message_reports = (
                    ChatMessageReport.query.options(
                        selectinload(ChatMessageReport.message).selectinload(ChatMessage.user),
                        selectinload(ChatMessageReport.message).selectinload(ChatMessage.room),
                        selectinload(ChatMessageReport.reporter),
                        selectinload(ChatMessageReport.resolver),
                    )
                    .filter(ChatMessageReport.status.in_(ACTIVE_REVIEW_REPORT_STATUSES))
                    .order_by(ChatMessageReport.created_at.desc())
                    .limit(reports_limit)
                    .all()
                )
            else:
                comment_reports = (
                    CommentReport.query.options(
                        selectinload(CommentReport.comment).selectinload(Comment.author),
                        selectinload(CommentReport.comment).selectinload(Comment.post),
                        selectinload(CommentReport.reporter),
                        selectinload(CommentReport.resolver),
                    )
                    .filter(CommentReport.status.in_(ACTIVE_REVIEW_REPORT_STATUSES))
                    .order_by(CommentReport.created_at.desc())
                    .limit(reports_limit)
                    .all()
                )
            context.update({
                'reported_posts': reported_posts,
                'chat_message_reports': chat_message_reports,
                'comment_reports': comment_reports,
            })
            return context

        if active_tab == 'chats':
            pending_rooms = (
                ChatRoom.query.filter_by(is_approved=False)
                .order_by(ChatRoom.created_at.desc())
                .limit(chat_rooms_limit)
                .all()
            )
            chat_rooms = (
                ChatRoom.query.order_by(ChatRoom.created_at.desc())
                .limit(chat_rooms_limit)
                .all()
            )
            room_ids = [room.id for room in chat_rooms]
            room_participant_counts = {}
            room_message_counts = {}
            if room_ids:
                room_participant_counts = {
                    int(room_id): int(count or 0)
                    for room_id, count in db.session.query(ChatParticipant.room_id, func.count(ChatParticipant.id))
                    .filter(ChatParticipant.room_id.in_(room_ids))
                    .group_by(ChatParticipant.room_id)
                    .all()
                }
                room_message_counts = {
                    int(room_id): int(count or 0)
                    for room_id, count in db.session.query(ChatMessage.room_id, func.count(ChatMessage.id))
                    .filter(ChatMessage.room_id.in_(room_ids))
                    .group_by(ChatMessage.room_id)
                    .all()
                }
            for room in chat_rooms:
                room.participant_count = room_participant_counts.get(room.id, 0)
                room.message_count = room_message_counts.get(room.id, 0)
            context.update({
                'pending_rooms': pending_rooms,
                'chat_rooms': chat_rooms,
            })
            return context

        if active_tab == 'verificaciones':
            verifications = (
                VerificationRequest.query.options(
                    selectinload(VerificationRequest.user),
                    selectinload(VerificationRequest.reviewer),
                )
                .order_by(VerificationRequest.created_at.desc())
                .limit(verifications_limit)
                .all()
            )
            pending_verifications = [v for v in verifications if getattr(v, 'status', '') == 'pending']
            pending_verifications_count = (
                db.session.query(func.count(VerificationRequest.id))
                .filter(VerificationRequest.status == 'pending')
                .scalar()
                or 0
            )
            context.update({
                'verifications': verifications,
                'pending_verifications': pending_verifications,
                'pending_verifications_count': pending_verifications_count,
            })
            return context

        if active_tab == 'rutas':
            maybe_process_overdue_checkins(ttl_seconds=30)
            route_checkins_limit = max(int(checkins_limit or 0), 200)
            checkins = (
                SafetyCheckin.query.options(selectinload(SafetyCheckin.user))
                .order_by(SafetyCheckin.started_at.desc())
                .limit(route_checkins_limit)
                .all()
            )
            checkins_total_count = db.session.query(func.count(SafetyCheckin.id)).scalar() or 0
            panic_events = (
                PanicEvent.query.options(selectinload(PanicEvent.user), selectinload(PanicEvent.resolver))
                .filter_by(status='open')
                .order_by(PanicEvent.created_at.desc())
                .limit(panic_events_limit)
                .all()
            )
            context.update({
                'checkins': checkins,
                'checkin_user_groups': _build_checkin_user_groups(checkins),
                'checkins_total_count': checkins_total_count,
                'panic_events': panic_events,
            })
            return context

        return context

    def _build_verification_ops_context() -> dict:
        context = _base_ops_panel_context()
        verifications = (
            VerificationRequest.query.options(
                selectinload(VerificationRequest.user),
                selectinload(VerificationRequest.reviewer),
            )
            .order_by(VerificationRequest.created_at.desc())
            .all()
        )
        context.update({
            'verifications': verifications,
            'pending_verifications': [v for v in verifications if getattr(v, 'status', '') == 'pending'],
            'available_admin_tabs': ['verificaciones'],
            'initial_admin_tab': 'verificaciones',
            'ops_panel_title': 'Centro de Verificación',
            'ops_panel_subtitle': 'Revisión de identidad y elegibilidad.',
        })
        return context

    def _build_moderation_ops_context() -> dict:
        context = _base_ops_panel_context()
        reported_posts = (
            Post.query.options(
                selectinload(Post.author),
                selectinload(Post.meta),
                selectinload(Post.reports).selectinload(Report.reporter),
                selectinload(Post.reports).selectinload(Report.resolver),
            )
            .filter(Post.reports.any(Report.status.in_(ACTIVE_REVIEW_REPORT_STATUSES)))
            .order_by(Post.created_at.desc())
            .all()
        )
        enrich_posts_for_cards(reported_posts, current_user)
        _attach_active_post_reports(reported_posts)
        chat_message_reports = (
            ChatMessageReport.query.options(
                selectinload(ChatMessageReport.message).selectinload(ChatMessage.user),
                selectinload(ChatMessageReport.message).selectinload(ChatMessage.room),
                selectinload(ChatMessageReport.reporter),
                selectinload(ChatMessageReport.resolver),
            )
            .filter(ChatMessageReport.status.in_(ACTIVE_REVIEW_REPORT_STATUSES))
            .order_by(ChatMessageReport.created_at.desc())
            .all()
        )
        comment_reports = (
            CommentReport.query.options(
                selectinload(CommentReport.comment).selectinload(Comment.author),
                selectinload(CommentReport.comment).selectinload(Comment.post),
                selectinload(CommentReport.reporter),
                selectinload(CommentReport.resolver),
            )
            .filter(CommentReport.status.in_(ACTIVE_REVIEW_REPORT_STATUSES))
            .order_by(CommentReport.created_at.desc())
            .all()
        )
        context.update({
            'reported_posts': reported_posts,
            'chat_message_reports': chat_message_reports,
            'comment_reports': comment_reports,
            'available_admin_tabs': ['reportes'],
            'initial_admin_tab': 'reportes',
            'ops_panel_title': 'Centro de Moderación',
            'ops_panel_subtitle': 'Revisión de reportes, restauraciones y strikes.',
        })
        return context

    def _build_safety_ops_context() -> dict:
        maybe_process_overdue_checkins(ttl_seconds=30)
        context = _base_ops_panel_context()
        checkins = (
            SafetyCheckin.query.options(selectinload(SafetyCheckin.user))
            .order_by(SafetyCheckin.started_at.desc())
            .limit(200)
            .all()
        )
        panic_events = (
            PanicEvent.query.options(selectinload(PanicEvent.user), selectinload(PanicEvent.resolver))
            .filter_by(status='open')
            .order_by(PanicEvent.created_at.desc())
            .all()
        )
        context.update({
            'checkins': checkins,
            'checkin_user_groups': _build_checkin_user_groups(checkins),
            'panic_events': panic_events,
            'available_admin_tabs': ['rutas'],
            'initial_admin_tab': 'rutas',
            'ops_panel_title': 'Centro de Safety',
            'ops_panel_subtitle': 'Monitoreo de check-ins, trayectos y eventos de pánico.',
        })
        return context

    @app.route('/admin')
    @login_required
    @permission_required(PERM_ADMIN_PANEL_VIEW, flash_message='Acceso denegado. Solo para personal autorizado.')
    def admin_panel():
        active_tab = (request.args.get('tab') or 'users').strip().lower()
        reports_subtab = (request.args.get('reports_subtab') or 'reportados').strip().lower()
        page_number = max(1, request.args.get('page', default=1, type=int) or 1)
        page_cache_key = ('page_admin_shell', ADMIN_PANEL_CACHE_VERSION, current_user.id, active_tab, reports_subtab, page_number)
        cached_response = get_cached_html_page(page_cache_key, 90)
        if cached_response is not None:
            return cached_response
        html = render_template(
            'admin_shell.html',
            active_admin_tab=active_tab,
            active_reports_subtab=reports_subtab,
            active_page_number=page_number,
            **_build_admin_attention_state(),
        )
        return set_cached_html_page(page_cache_key, html, ttl_seconds=90, max_entries=96)

    @app.route('/admin/content')
    @login_required
    @permission_required(PERM_ADMIN_PANEL_VIEW, flash_message='Acceso denegado. Solo para personal autorizado.')
    def admin_panel_content():
        active_tab = (request.args.get('tab') or 'users').strip().lower()
        reports_subtab = (request.args.get('reports_subtab') or 'reportados').strip().lower()
        page_number = max(1, request.args.get('page', default=1, type=int) or 1)
        if active_tab == 'chats':
            try:
                _ensure_default_chat_room()
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
        page_cache_key = ('page_admin_content', ADMIN_PANEL_CACHE_VERSION, current_user.id, active_tab, reports_subtab, page_number)
        cached_response = get_cached_html_page(page_cache_key, 45)
        if cached_response is not None:
            return cached_response
        context = _build_super_admin_ops_context(active_tab, reports_subtab, include_overview=False, page_number=page_number)
        record_audit_event(
            'workspace.view',
            workspace='admin',
            resource_type='workspace',
            summary='Abrió el panel completo de operaciones.',
            details={
                'available_tabs': context.get('available_admin_tabs') or [],
                'active_tab': context.get('active_admin_tab') or 'users',
                'active_reports_subtab': context.get('active_reports_subtab') or 'reportados',
                'page_number': context.get('admin_page_number') or 1,
                'mode': 'content',
            },
        )
        html = render_template('admin.html', admin_partial=True, **context)
        return set_cached_html_page(page_cache_key, html, ttl_seconds=45, max_entries=96)

    @app.route('/admin/overview')
    @login_required
    @permission_required(PERM_ADMIN_PANEL_VIEW, flash_message='Acceso denegado. Solo para personal autorizado.')
    def admin_panel_overview():
        page_cache_key = ('page_admin_overview', ADMIN_PANEL_CACHE_VERSION, current_user.id)
        cached_response = get_cached_html_page(page_cache_key, 45)
        if cached_response is not None:
            return cached_response
        html = render_template('admin_overview.html', **_build_super_admin_overview_context())
        return set_cached_html_page(page_cache_key, html, ttl_seconds=45, max_entries=96)

    @app.route('/admin/tab-content')
    @login_required
    @permission_required(PERM_ADMIN_PANEL_VIEW, flash_message='Acceso denegado. Solo para personal autorizado.')
    def admin_panel_tab_content():
        return admin_panel_content()

    @app.route('/admin/audit_logs/export')
    @login_required
    @permission_required(PERM_ADMIN_PANEL_VIEW, flash_message='Acceso denegado. Solo para personal autorizado.')
    def admin_export_audit_logs():
        filters = build_audit_filters_from_request()
        rows = build_audit_log_query(
            filters,
            include_related=True,
            limit=audit_log_export_limit(),
        ).all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            'created_at',
            'workspace',
            'event_type',
            'summary',
            'actor_username',
            'target_username',
            'resource_type',
            'resource_id',
            'route',
            'method',
            'ip_address',
            'user_agent',
            'details',
        ])
        for entry in rows:
            writer.writerow([
                entry.created_at.isoformat() if entry.created_at else '',
                entry.workspace or '',
                entry.event_type or '',
                entry.summary or '',
                entry.actor.username if entry.actor else '',
                entry.target_user.username if entry.target_user else '',
                entry.resource_type or '',
                entry.resource_id or '',
                entry.route or '',
                entry.method or '',
                entry.ip_address or '',
                entry.user_agent or '',
                entry.details or '',
            ])

        record_audit_event(
            'audit.export',
            workspace='admin',
            resource_type='audit_log',
            summary='Exportó auditoría en CSV.',
            details={
                'rows_exported': len(rows),
                'filters': audit_filters_to_query_params(filters),
            },
        )

        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=audit-logs-{utc_now_naive().strftime("%Y%m%d-%H%M%S")}.csv'
        return response

    @app.route('/admin/audit_logs/purge', methods=['POST'])
    @login_required
    @permission_required(PERM_ADMIN_PANEL_VIEW, json_only=True, flash_message='Acceso denegado. Solo para personal autorizado.')
    def admin_purge_audit_logs():
        try:
            deleted_count = purge_expired_audit_logs()
            retention_days = audit_log_retention_days()
            record_audit_event(
                'audit.purge',
                workspace='admin',
                resource_type='audit_log',
                summary='Ejecutó la purga de auditoría.',
                details={
                    'deleted_count': deleted_count,
                    'retention_days': retention_days,
                },
            )
            return jsonify({
                'success': True,
                'deleted_count': deleted_count,
                'retention_days': retention_days,
            })
        except Exception as exc:
            db.session.rollback()
            _debug_log_suppressed('suppressed audit purge route exception', exc)
            return jsonify({'success': False, 'error': 'No se pudo completar la purga de auditoría.'}), 500

    @app.route('/staff/verificaciones')
    @login_required
    @permission_required(PERM_VERIFICATION_REVIEW, flash_message='Acceso denegado. Solo para personal de verificación.')
    def verification_workspace():
        context = _build_verification_ops_context()
        record_audit_event(
            'workspace.view',
            workspace='verification',
            resource_type='workspace',
            summary='Abrió el centro de verificación.',
            details={'available_tabs': context.get('available_admin_tabs') or []},
        )
        return render_template('admin.html', **context)

    @app.route('/staff/moderacion')
    @login_required
    @permission_required(PERM_REPORTS_REVIEW, flash_message='Acceso denegado. Solo para personal de moderación.')
    def moderation_workspace():
        context = _build_moderation_ops_context()
        record_audit_event(
            'workspace.view',
            workspace='moderation',
            resource_type='workspace',
            summary='Abrió el centro de moderación.',
            details={'available_tabs': context.get('available_admin_tabs') or []},
        )
        return render_template('admin.html', **context)

    @app.route('/staff/safety')
    @login_required
    @permission_required(PERM_SAFETY_VIEW_ANY, flash_message='Acceso denegado. Solo para personal de safety.')
    def safety_workspace():
        context = _build_safety_ops_context()
        record_audit_event(
            'workspace.view',
            workspace='safety',
            resource_type='workspace',
            summary='Abrió el centro de safety.',
            details={'available_tabs': context.get('available_admin_tabs') or []},
        )
        return render_template('admin.html', **context)

    @app.route('/admin/reports_timeseries')
    @login_required
    @permission_required(PERM_ADMIN_PANEL_VIEW, json_only=True)
    def admin_reports_timeseries():
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
                if key in ('terrenos baldios', 'terrenos baldíos', 'baldios', 'baldío', 'baldio', 'baldíos', 'punto ciego'):
                    normalized.add('Terrenos baldíos')
                elif key in ('poca iluminacion', 'poca iluminación'):
                    normalized.add('Poca iluminación')
                elif key in ('banquetas en mal estado',):
                    normalized.add('Banquetas en mal estado')
                elif key in ('zona insegura', 'zonas inseguras'):
                    normalized.add('Zona insegura')
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
    @permission_required(PERM_VERIFICATION_REVIEW, json_only=True)
    def admin_approve_verification(req_id):
        req = VerificationRequest.query.get_or_404(req_id)
        video_to_delete = (req.video_filename or '').strip()
        previous_status = (req.status or '').strip() or 'pending'
        req.status = 'approved'
        req.reviewed_at = datetime.now()
        req.reviewed_by = current_user.id
        req.video_filename = None
        user = User.query.get(req.user_id)
        if user:
            user.is_verified = True
        db.session.add(req)
        db.session.commit()
        if video_to_delete:
            safe_remove_upload(video_to_delete)
        record_audit_event(
            'verification.approve',
            workspace='verification',
            target_user=user,
            resource_type='verification_request',
            resource_id=req.id,
            summary='Aprobó una verificación.',
            details={
                'previous_status': previous_status,
                'new_status': req.status,
                'user_id': req.user_id,
            },
        )
        return jsonify({'success': True})

    @app.route('/admin/verify/<int:req_id>/reject', methods=['POST'])
    @login_required
    @permission_required(PERM_VERIFICATION_REVIEW, json_only=True)
    def admin_reject_verification(req_id):
        req = VerificationRequest.query.get_or_404(req_id)
        video_to_delete = (req.video_filename or '').strip()
        previous_status = (req.status or '').strip() or 'pending'
        req.status = 'rejected'
        req.reviewed_at = datetime.now()
        req.reviewed_by = current_user.id
        req.video_filename = None
        user = User.query.get(req.user_id)
        if user:
            user.is_verified = False
        db.session.add(req)
        db.session.commit()
        if video_to_delete:
            safe_remove_upload(video_to_delete)
        record_audit_event(
            'verification.reject',
            workspace='verification',
            target_user=user,
            resource_type='verification_request',
            resource_id=req.id,
            summary='Rechazó una verificación.',
            details={
                'previous_status': previous_status,
                'new_status': req.status,
                'user_id': req.user_id,
            },
        )
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
        delete_public_upload_from_storage(name)

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
        Report.query.filter_by(resolved_by=target_user.id).update({'resolved_by': None}, synchronize_session=False)
        ChatMessageReport.query.filter_by(reporter_id=target_user.id).delete(synchronize_session=False)
        ChatMessageReport.query.filter_by(resolved_by=target_user.id).update({'resolved_by': None}, synchronize_session=False)
        CommentReport.query.filter_by(reporter_id=target_user.id).delete(synchronize_session=False)
        CommentReport.query.filter_by(resolved_by=target_user.id).update({'resolved_by': None}, synchronize_session=False)
        Comment.query.filter_by(hidden_by=target_user.id).update({'hidden_by': None}, synchronize_session=False)
        ModerationStrike.query.filter_by(user_id=target_user.id).delete(synchronize_session=False)
        ModerationStrike.query.filter_by(issued_by=target_user.id).update({'issued_by': None}, synchronize_session=False)
        AuditLog.query.filter_by(actor_id=target_user.id).update({'actor_id': None}, synchronize_session=False)
        AuditLog.query.filter_by(target_user_id=target_user.id).update({'target_user_id': None}, synchronize_session=False)
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
    @permission_required(PERM_USERS_MANAGE, json_only=True)
    def admin_delete_user(user_id):
        user = User.query.get_or_404(user_id)
        if user_is_protected_staff(user):
            return jsonify({'error': 'No puedes eliminar una cuenta protegida'}), 400

        try:
            delete_user_and_related(user)
            db.session.commit()
            invalidate_admin_panel_page_cache()
            return jsonify({'success': True, 'message': f'Usuaria {user.username} eliminada'})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_delete_user error:', e)
            return jsonify({'error': 'No se pudo eliminar la usuaria'}), 500

    @app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
    @login_required
    @permission_required(PERM_POSTS_MANAGE, json_only=True)
    def admin_delete_post(post_id):
        post = Post.query.get_or_404(post_id)
        db.session.delete(post)
        db.session.commit()
        invalidate_admin_panel_page_cache()
        return jsonify({'success': True, 'message': 'Publicación eliminada'})

    @app.route('/admin/restore_post/<int:post_id>', methods=['POST'])
    @login_required
    @permission_required(PERM_POSTS_MANAGE, json_only=True)
    def admin_restore_post(post_id):
        meta = PostMeta.query.filter_by(post_id=post_id).first()
        if not meta:
            return jsonify({'error': 'No hay reporte para restaurar'}), 404

        meta.show_public = True
        db.session.add(meta)
        db.session.commit()
        invalidate_admin_panel_page_cache()
        invalidate_runtime_response_cache('hotspots')
        invalidate_runtime_response_cache('posts_in_radius')
        invalidate_runtime_response_cache('posts_by_city')
        invalidate_runtime_response_cache('feed_sidebar')
        _feed_sidebar_cache.clear()
        return jsonify({'success': True, 'message': 'Publicación restaurada'})

    @app.route('/admin/update_post_location/<int:post_id>', methods=['POST'])
    @login_required
    @permission_required(PERM_POSTS_MANAGE, json_only=True)
    def admin_update_post_location(post_id):
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
        invalidate_runtime_response_cache('hotspots')
        invalidate_runtime_response_cache('posts_in_radius')
        invalidate_runtime_response_cache('posts_by_city')
        invalidate_runtime_response_cache('feed_sidebar')

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
    @permission_required(PERM_USERS_MANAGE, json_only=True)
    def admin_change_username(user_id):
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
        invalidate_admin_panel_page_cache()
        return jsonify({'success': True, 'message': f'Nombre de usuaria cambiado a {new_username}'})

    @app.route('/admin/change_user_photo/<int:user_id>', methods=['POST'])
    @login_required
    @permission_required(PERM_USERS_MANAGE, json_only=True)
    def admin_change_user_photo(user_id):
        user = User.query.get_or_404(user_id)

        bio = (request.form.get('bio') or '').strip()
        file = request.files.get('photo')

        if not file or file.filename == '':
            if bio == '':
                return jsonify({'error': 'No se seleccionó archivo'}), 400
            user.bio = bio
            db.session.commit()
            invalidate_admin_panel_page_cache()
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
            strip_image_metadata_in_place(file_path)
            if not sync_public_upload_to_storage(unique_filename, local_path=file_path, mime_type=file.mimetype):
                try:
                    os.remove(file_path)
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
                return jsonify({'error': 'No se pudo guardar la foto en el almacenamiento externo'}), 500

            user.profile_pic = unique_filename
            if bio != '':
                user.bio = bio
            db.session.commit()
            invalidate_admin_panel_page_cache()
            return jsonify({'success': True, 'message': 'Foto de perfil actualizada', 'photo_url': url_for('uploaded_file', filename=unique_filename)})
        else:
            return jsonify({'error': 'Tipo de archivo no permitido'}), 400

    @app.route('/admin/user/<int:user_id>/roles', methods=['POST'])
    @login_required
    @permission_required(PERM_USERS_MANAGE, json_only=True)
    def admin_update_user_roles(user_id):
        user = User.query.get_or_404(user_id)
        payload = request.get_json(silent=True) or request.form or {}
        raw_roles = payload.get('roles') if isinstance(payload, dict) else None

        if raw_roles is None and hasattr(request.form, 'getlist'):
            raw_roles = request.form.getlist('roles')

        if isinstance(raw_roles, str):
            raw_roles = [chunk.strip() for chunk in raw_roles.split(',') if chunk.strip()]
        elif not isinstance(raw_roles, (list, tuple, set)):
            raw_roles = []

        allowed_roles = {item['key'] for item in STAFF_ROLE_OPTIONS}
        next_roles = sorted({
            str(role).strip().lower()
            for role in raw_roles
            if str(role).strip().lower() in allowed_roles
        })
        current_roles = user_role_names(user)

        if ROLE_SUPER_ADMIN in current_roles and ROLE_SUPER_ADMIN not in next_roles:
            if count_super_admin_users() <= 1:
                return jsonify({'success': False, 'error': 'Debe existir al menos una cuenta con rol de súper admin.'}), 400

        user.set_roles(next_roles)
        db.session.add(user)
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _debug_log_suppressed('suppressed exception', exc)
            return jsonify({'success': False, 'error': 'No se pudieron guardar los roles.'}), 500
        invalidate_admin_panel_page_cache()

        next_roles_saved = sorted(user_role_names(user))
        record_audit_event(
            'user_roles.update',
            workspace='admin',
            target_user=user,
            resource_type='user',
            resource_id=user.id,
            summary='Actualizó los roles de una cuenta del staff.',
            details={
                'previous_roles': sorted(current_roles),
                'new_roles': next_roles_saved,
            },
        )

        return jsonify({
            'success': True,
            'user_id': user.id,
            'roles': next_roles_saved,
        })

    @app.route('/admin/approve_chat_room/<int:room_id>', methods=['POST'])
    @login_required
    @permission_required(PERM_CHAT_ROOMS_MANAGE, json_only=True)
    def admin_approve_chat_room(room_id):
        room = ChatRoom.query.get_or_404(room_id)
        room.is_approved = True
        db.session.commit()
        invalidate_runtime_response_cache('chat_rooms')
        return jsonify({'success': True})

    @app.route('/admin/delete_chat_room/<int:room_id>', methods=['POST'])
    @login_required
    @permission_required(PERM_CHAT_ROOMS_MANAGE, json_only=True)
    def admin_delete_chat_room(room_id):
        room = ChatRoom.query.get_or_404(room_id)
        db.session.delete(room)
        db.session.commit()
        invalidate_runtime_response_cache('chat_rooms')
        return jsonify({'success': True})

    @app.route('/admin/clear_chat_room/<int:room_id>', methods=['POST'])
    @login_required
    @permission_required(PERM_CHAT_ROOMS_MANAGE, json_only=True)
    def admin_clear_chat_room(room_id):
        room = ChatRoom.query.get_or_404(room_id)

        try:
            messages = ChatMessage.query.filter_by(room_id=room_id).all()
            for msg in messages:
                filename = getattr(msg, 'attachment_filename', None)
                if filename:
                    safe_remove_upload(filename)
                db.session.delete(msg)
            db.session.commit()
            invalidate_runtime_response_cache('chat_rooms')

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

    @app.route('/api/chat/message/<int:message_id>/report', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_chat_report_message(message_id):
        if not is_same_origin_request():
            return jsonify({'error': 'Origen inválido'}), 403
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        if is_user_temp_muted(current_user):
            return jsonify(temp_mute_error_payload('Tienes una restricción temporal de interacción.')), 403

        data = request.get_json(silent=True) or request.form or {}
        reason = (data.get('reason') or '').strip()
        details = (data.get('details') or '').strip()

        if reason not in CHAT_MESSAGE_REPORT_REASONS:
            return jsonify({'error': 'Categoría inválida'}), 400

        try:
            message = ChatMessage.query.get_or_404(message_id)
            room = ChatRoom.query.get_or_404(message.room_id)
            high_risk = _report_requires_immediate_hide(
                'chat_message',
                reason,
                details=details,
                content_excerpt=message.content or message.attachment_name or '',
            )

            if not room.is_approved:
                return jsonify({'error': 'Sala pendiente de aprobación'}), 403
            if room.created_by and is_user_blocked_between(current_user.id, room.created_by):
                return jsonify({'error': 'No tienes acceso a esta sala.'}), 403
            if is_user_blocked_between(current_user.id, message.user_id):
                return jsonify({'error': 'No puedes reportar contenido de esta cuenta.'}), 403
            if message.user_id == current_user.id:
                return jsonify({'error': 'No puedes reportar tu propio mensaje.'}), 400

            existing = ChatMessageReport.query.filter_by(message_id=message.id, reporter_id=current_user.id).first()
            if getattr(message, 'is_deleted', False) and not existing:
                return jsonify({'error': 'Este mensaje ya no está disponible.'}), 400

            if existing:
                existing.reason = reason
                existing.details = details or None
                existing.status = 'reviewing' if high_risk else 'pending'
                existing.admin_note = None
                existing.resolved_at = None
                existing.resolved_by = None
                report = existing
            else:
                report = ChatMessageReport(
                    message_id=message.id,
                    reporter_id=current_user.id,
                    reason=reason,
                    details=details or None,
                    status='reviewing' if high_risk else 'pending',
                )
                db.session.add(report)

            if high_risk and not getattr(message, 'is_deleted', False):
                message.is_deleted = True
                message.deleted_at = utc_now_naive()
                message.deleted_by = current_user.id
                db.session.add(message)

            db.session.commit()

            content_hidden = bool(getattr(message, 'is_deleted', False))
            if content_hidden:
                try:
                    socketio.emit('message_deleted', {
                        'room_id': room.id,
                        'message_id': message.id,
                        'deleted_reason': 'reported',
                        'created_at': message.created_at.isoformat() if message.created_at else None,
                        'username': message.user.username if message.user else None,
                        'message_type': message.message_type,
                    }, room=f'room_{room.id}')
                except Exception as e:
                    if app.debug:
                        print('DEBUG message_reported emit error:', e)

            if high_risk:
                message_text = 'Reporte de alto riesgo enviado. El mensaje se ocultó preventivamente mientras lo revisamos.'
            elif content_hidden:
                message_text = 'Reporte enviado. El mensaje ya está oculto mientras el equipo lo revisa.'
            else:
                message_text = 'Reporte enviado a revisión. El mensaje seguirá visible hasta que el equipo lo revise.'

            return jsonify({
                'success': True,
                'message': message_text,
                'report_id': report.id,
                'room_id': room.id,
                'message_id': message.id,
                'status': report.status,
                'high_risk': high_risk,
                'hidden_immediately': content_hidden,
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_chat_report_message error:', e)
            return jsonify({'error': 'No se pudo enviar el reporte'}), 400

    @app.route('/api/comment/<int:comment_id>/report', methods=['POST'])
    @csrf.exempt
    @login_required
    def api_comment_report(comment_id):
        if not is_same_origin_request():
            return jsonify({'error': 'Origen inválido'}), 403
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        if is_user_temp_muted(current_user):
            return jsonify(temp_mute_error_payload('Tienes una restricción temporal de interacción.')), 403

        data = request.get_json(silent=True) or request.form or {}
        reason = (data.get('reason') or '').strip()
        details = (data.get('details') or '').strip()
        if reason not in COMMENT_REPORT_REASONS:
            return jsonify({'error': 'Categoría inválida'}), 400

        try:
            comment = Comment.query.get_or_404(comment_id)
            post = Post.query.get_or_404(comment.post_id)
            high_risk = _report_requires_immediate_hide(
                'comment',
                reason,
                details=details,
                content_excerpt=comment.content or '',
            )
            if comment.user_id == current_user.id and not user_is_protected_staff(current_user):
                return jsonify({'error': 'No puedes reportar tu propio comentario.'}), 400
            if is_user_blocked_between(current_user.id, comment.user_id):
                return jsonify({'error': 'No puedes reportar contenido de esta cuenta.'}), 403
            if not is_public_post(post) and not user_can_review_private_content(current_user):
                return jsonify({'error': 'Publicación no disponible.'}), 404

            existing = CommentReport.query.filter_by(comment_id=comment.id, reporter_id=current_user.id).first()
            if existing:
                existing.reason = reason
                existing.details = details or None
                existing.status = 'reviewing' if high_risk else 'pending'
                existing.admin_note = None
                existing.resolved_at = None
                existing.resolved_by = None
                report = existing
            else:
                report = CommentReport(
                    comment_id=comment.id,
                    reporter_id=current_user.id,
                    reason=reason,
                    details=details or None,
                    status='reviewing' if high_risk else 'pending',
                )
                db.session.add(report)

            if high_risk:
                comment.is_hidden = True
                comment.hidden_at = utc_now_naive()
                comment.hidden_by = current_user.id
                comment.hidden_reason = 'reported'
                db.session.add(comment)
            db.session.commit()
            content_hidden = bool(getattr(comment, 'is_hidden', False))
            if high_risk:
                message_text = 'Reporte de alto riesgo enviado. El comentario se ocultó preventivamente mientras lo revisamos.'
            elif content_hidden:
                message_text = 'Reporte enviado. El comentario ya está oculto mientras el equipo lo revisa.'
            else:
                message_text = 'Reporte enviado a revisión. El comentario seguirá visible hasta que el equipo lo revise.'
            return jsonify({
                'success': True,
                'message': message_text,
                'report_id': report.id,
                'comment_id': comment.id,
                'post_id': post.id,
                'status': report.status,
                'high_risk': high_risk,
                'hidden_immediately': content_hidden,
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_comment_report error:', e)
            return jsonify({'error': 'No se pudo enviar el reporte'}), 400

    @app.route('/api/chat/message/<int:message_id>/delete', methods=['POST'])
    @login_required
    def api_chat_delete_message(message_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403
        try:
            message = ChatMessage.query.get_or_404(message_id)
            room = ChatRoom.query.get_or_404(message.room_id)

            is_admin = user_has_permission(current_user, PERM_CHAT_MESSAGES_MODERATE)
            is_owner = room.created_by == current_user.id
            is_sender = message.user_id == current_user.id

            if user_is_protected_staff(message.user) and not is_admin:
                return jsonify({'error': 'No tienes permiso para eliminar mensajes de una cuenta protegida'}), 403

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

            if message.attachment_filename:
                safe_remove_upload(message.attachment_filename)
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
                    'message_id': message.id,
                    'deleted_reason': 'deleted',
                    'created_at': message.created_at.isoformat() if message.created_at else None,
                    'username': message.user.username if message.user else None,
                    'message_type': message.message_type,
                }, room=f'room_{room.id}')
            except Exception as e:
                if app.debug:
                    print('DEBUG message_deleted emit error:', e)

            return jsonify({'success': True, 'deleted_reason': 'deleted'})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG api_chat_delete_message error:', e)
            return jsonify({'error': 'No se pudo eliminar el mensaje'}), 500

    @app.route('/admin/bulk_delete_users', methods=['POST'])
    @login_required
    @permission_required(PERM_USERS_MANAGE, json_only=True)
    def admin_bulk_delete_users():
        data = request.get_json() or {}
        ids = data.get('ids') or []
        deleted = 0
        try:
            for uid in ids:
                user = User.query.get(uid)
                if not user or user_is_protected_staff(user):
                    continue
                delete_user_and_related(user)
                deleted += 1
            db.session.commit()
            invalidate_admin_panel_page_cache()
            return jsonify({'success': True, 'deleted': deleted})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_bulk_delete_users error:', e)
            return jsonify({'error': 'No se pudieron eliminar usuarias'}), 500

    @app.route('/admin/bulk_delete_posts', methods=['POST'])
    @login_required
    @permission_required(PERM_POSTS_MANAGE, json_only=True)
    def admin_bulk_delete_posts():
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
        invalidate_admin_panel_page_cache()
        return jsonify({'success': True, 'deleted': deleted})

    @app.route('/admin/bulk_restore_posts', methods=['POST'])
    @login_required
    @permission_required(PERM_POSTS_MANAGE, json_only=True)
    def admin_bulk_restore_posts():
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
        invalidate_admin_panel_page_cache()
        return jsonify({'success': True, 'restored': restored})

    @app.route('/admin/bulk_delete_chat_rooms', methods=['POST'])
    @login_required
    @permission_required(PERM_CHAT_ROOMS_MANAGE, json_only=True)
    def admin_bulk_delete_chat_rooms():
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
    @permission_required(PERM_REPORTS_REVIEW, json_only=True)
    def admin_report_details(post_id):
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
                'is_super_admin': user_has_staff_badge(c.author) if getattr(c, 'author', None) else False,
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
                'reporter_is_super_admin': user_has_staff_badge(r.reporter) if getattr(r, 'reporter', None) else False,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'status': r.status or 'pending',
                'admin_note': r.admin_note or '',
                'resolved_at': r.resolved_at.isoformat() if r.resolved_at else None,
                'resolved_by': r.resolver.username if getattr(r, 'resolver', None) else None,
            })

        record_audit_event(
            'report_details.view',
            workspace='moderation',
            target_user=author,
            resource_type='post',
            resource_id=post.id,
            summary='Abrió el detalle sensible de una publicación reportada.',
            details={
                'reports_count': len(reports),
                'comments_count': comments_count,
                'likes_count': likes_count,
            },
        )

        return jsonify({
            'post': {
                'id': post.id,
                'image_url': image_url,
                'caption': post.caption or '',
                'created_at': post.created_at.isoformat() if post.created_at else None,
                'author': {
                    'username': author.username if author else 'unknown',
                    'profile_pic': author_pic,
                    'is_super_admin': user_has_staff_badge(author) if author else False,
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

    @app.route('/admin/report/<int:report_id>/restore', methods=['POST'])
    @login_required
    @permission_required(PERM_REPORTS_REVIEW, json_only=True)
    def admin_restore_post_report(report_id):
        report = Report.query.get_or_404(report_id)
        post = report.post
        if not post:
            return jsonify({'error': 'La publicación ya no existe'}), 404
        admin_note = (request.get_json(silent=True) or request.form or {}).get('admin_note') if (request.get_json(silent=True) or request.form or {}) else ''
        try:
            _restore_reported_post(post, admin_note)
            db.session.commit()
            invalidate_admin_panel_page_cache()
            invalidate_runtime_response_cache('hotspots')
            invalidate_runtime_response_cache('posts_in_radius')
            invalidate_runtime_response_cache('posts_by_city')
            invalidate_runtime_response_cache('feed_sidebar')
            _feed_sidebar_cache.clear()
            return jsonify({'success': True, 'status': 'restored'})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_restore_post_report error:', e)
            return jsonify({'error': 'No se pudo restaurar la publicación'}), 500

    @app.route('/admin/report/<int:report_id>/strike', methods=['POST'])
    @login_required
    @permission_required(PERM_REPORTS_REVIEW, json_only=True)
    def admin_strike_post_report(report_id):
        report = Report.query.get_or_404(report_id)
        post = report.post
        if not post or not post.author:
            return jsonify({'error': 'La publicación ya no existe'}), 404
        if user_is_protected_staff(post.author):
            return jsonify({'error': 'No puedes sancionar publicaciones de una cuenta protegida.'}), 400
        payload = request.get_json(silent=True) or request.form or {}
        admin_note = (payload.get('admin_note') or '').strip()
        strike_result = None
        try:
            meta = PostMeta.query.filter_by(post_id=post.id).first()
            if not meta:
                meta = PostMeta(post_id=post.id)
            meta.show_public = False
            db.session.add(meta)
            created_label = post.created_at.strftime('%d/%m/%Y %H:%M') if post.created_at else 'sin fecha'
            location_label = post.location_name or post.city or post.country or 'sin ubicación'
            strike_result = _issue_report_strike(
                post.author,
                report_reason=report.reason,
                source_type='post',
                source_id=post.id,
                source_label=f'Publicación en {location_label}',
                details=f'Publicación enviada el {created_label}. Ubicación: {location_label}. Motivo: {report.reason}. Nota admin: {admin_note or "Sin nota."}',
                content_excerpt=post.caption or post.image_filename or 'Imagen adjunta',
            )
            if strike_result.get('applied'):
                note = admin_note or 'Strike aplicado por publicación reportada.'
            else:
                note = admin_note or 'El contenido se mantuvo oculto, pero no se generó un nuevo strike por límite diario.'
            _mark_related_reports(post.reports, 'struck', note)
            db.session.commit()
            if strike_result.get('applied') and strike_result.get('strike'):
                try:
                    send_moderation_notice_email(post.author, strike_result['strike'])
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
            invalidate_admin_panel_page_cache()
            invalidate_runtime_response_cache('hotspots')
            invalidate_runtime_response_cache('posts_in_radius')
            invalidate_runtime_response_cache('posts_by_city')
            invalidate_runtime_response_cache('feed_sidebar')
            _feed_sidebar_cache.clear()
            return jsonify({
                'success': True,
                'status': 'struck',
                'strike_applied': bool(strike_result.get('applied')),
                'consequence': strike_result.get('consequence'),
                'message': 'Se aplicó la sanción.' if strike_result.get('applied') else 'El contenido quedó oculto, pero la usuaria ya tenía un strike hoy.'
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_strike_post_report error:', e)
            return jsonify({'error': 'No se pudo aplicar la sanción'}), 500

    @app.route('/admin/chat_report/<int:report_id>/restore', methods=['POST'])
    @login_required
    @permission_required(PERM_REPORTS_REVIEW, json_only=True)
    def admin_restore_chat_report(report_id):
        report = ChatMessageReport.query.get_or_404(report_id)
        message = report.message
        if not message:
            return jsonify({'error': 'El mensaje ya no existe'}), 404
        payload = request.get_json(silent=True) or request.form or {}
        admin_note = (payload.get('admin_note') or '').strip()
        try:
            _restore_reported_message(message, admin_note)
            db.session.commit()
            invalidate_admin_panel_page_cache()
            _emit_message_restored(message)
            return jsonify({'success': True, 'status': 'restored'})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_restore_chat_report error:', e)
            return jsonify({'error': 'No se pudo restaurar el mensaje'}), 500

    @app.route('/admin/chat_report/<int:report_id>/strike', methods=['POST'])
    @login_required
    @permission_required(PERM_REPORTS_REVIEW, json_only=True)
    def admin_strike_chat_report(report_id):
        report = ChatMessageReport.query.get_or_404(report_id)
        message = report.message
        if not message or not message.user:
            return jsonify({'error': 'El mensaje ya no existe'}), 404
        if user_is_protected_staff(message.user):
            return jsonify({'error': 'No puedes sancionar mensajes de una cuenta protegida.'}), 400
        payload = request.get_json(silent=True) or request.form or {}
        admin_note = (payload.get('admin_note') or '').strip()
        strike_result = None
        try:
            message.is_deleted = True
            if not message.deleted_at:
                message.deleted_at = utc_now_naive()
            if not message.deleted_by:
                message.deleted_by = current_user.id
            db.session.add(message)
            room = message.room
            room_label = room.name if room else 'grupo eliminado'
            created_label = message.created_at.strftime('%d/%m/%Y %H:%M') if message.created_at else 'sin fecha'
            strike_result = _issue_report_strike(
                message.user,
                report_reason=report.reason,
                source_type='chat_message',
                source_id=message.id,
                source_label=f'Mensaje en {room_label}',
                details=f'Grupo: {room_label}. Fecha: {created_label}. Motivo: {report.reason}. Nota admin: {admin_note or "Sin nota."}',
                content_excerpt=message.content or message.attachment_name or 'Archivo adjunto',
            )
            if strike_result.get('applied'):
                note = admin_note or 'Strike aplicado por mensaje reportado.'
            else:
                note = admin_note or 'El mensaje siguió oculto, pero no se generó un nuevo strike por límite diario.'
            _mark_related_reports(message.reports, 'struck', note)
            db.session.commit()
            if strike_result.get('applied') and strike_result.get('strike'):
                try:
                    send_moderation_notice_email(message.user, strike_result['strike'])
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
            invalidate_admin_panel_page_cache()
            return jsonify({
                'success': True,
                'status': 'struck',
                'strike_applied': bool(strike_result.get('applied')),
                'consequence': strike_result.get('consequence'),
                'message': 'Se aplicó la sanción.' if strike_result.get('applied') else 'El mensaje quedó oculto, pero la usuaria ya tenía un strike hoy.'
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_strike_chat_report error:', e)
            return jsonify({'error': 'No se pudo aplicar la sanción'}), 500

    @app.route('/admin/comment_report/<int:report_id>/restore', methods=['POST'])
    @login_required
    @permission_required(PERM_REPORTS_REVIEW, json_only=True)
    def admin_restore_comment_report(report_id):
        report = CommentReport.query.get_or_404(report_id)
        comment = report.comment
        if not comment:
            return jsonify({'error': 'El comentario ya no existe'}), 404
        payload = request.get_json(silent=True) or request.form or {}
        admin_note = (payload.get('admin_note') or '').strip()
        try:
            _restore_reported_comment(comment, admin_note)
            db.session.commit()
            invalidate_admin_panel_page_cache()
            return jsonify({'success': True, 'status': 'restored'})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_restore_comment_report error:', e)
            return jsonify({'error': 'No se pudo restaurar el comentario'}), 500

    @app.route('/admin/comment_report/<int:report_id>/strike', methods=['POST'])
    @login_required
    @permission_required(PERM_REPORTS_REVIEW, json_only=True)
    def admin_strike_comment_report(report_id):
        report = CommentReport.query.get_or_404(report_id)
        comment = report.comment
        if not comment or not comment.author:
            return jsonify({'error': 'El comentario ya no existe'}), 404
        if user_is_protected_staff(comment.author):
            return jsonify({'error': 'No puedes sancionar comentarios de una cuenta protegida.'}), 400
        payload = request.get_json(silent=True) or request.form or {}
        admin_note = (payload.get('admin_note') or '').strip()
        strike_result = None
        try:
            comment.is_hidden = True
            comment.hidden_at = comment.hidden_at or utc_now_naive()
            comment.hidden_by = comment.hidden_by or current_user.id
            comment.hidden_reason = 'reported'
            db.session.add(comment)
            post = comment.post
            post_label = f'publicación #{post.id}' if post else 'publicación eliminada'
            created_label = comment.created_at.strftime('%d/%m/%Y %H:%M') if comment.created_at else 'sin fecha'
            strike_result = _issue_report_strike(
                comment.author,
                report_reason=report.reason,
                source_type='comment',
                source_id=comment.id,
                source_label=f'Comentario en {post_label}',
                details=f'Post: {post_label}. Fecha: {created_label}. Motivo: {report.reason}. Nota admin: {admin_note or "Sin nota."}',
                content_excerpt=comment.content,
            )
            if strike_result.get('applied'):
                note = admin_note or 'Strike aplicado por comentario reportado.'
            else:
                note = admin_note or 'El comentario siguió oculto, pero no se generó un nuevo strike por límite diario.'
            _mark_related_reports(comment.reports, 'struck', note)
            db.session.commit()
            if strike_result.get('applied') and strike_result.get('strike'):
                try:
                    send_moderation_notice_email(comment.author, strike_result['strike'])
                except Exception as exc:
                    _debug_log_suppressed('suppressed exception', exc)
            invalidate_admin_panel_page_cache()
            return jsonify({
                'success': True,
                'status': 'struck',
                'strike_applied': bool(strike_result.get('applied')),
                'consequence': strike_result.get('consequence'),
                'message': 'Se aplicó la sanción.' if strike_result.get('applied') else 'El comentario quedó oculto, pero la usuaria ya tenía un strike hoy.'
            })
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG admin_strike_comment_report error:', e)
            return jsonify({'error': 'No se pudo aplicar la sanción'}), 500


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
                        strip_image_metadata_in_place(save_path)
                        if not sync_public_upload_to_storage(unique_name, local_path=save_path, mime_type=file.mimetype):
                            try:
                                os.remove(save_path)
                            except Exception as exc:
                                _debug_log_suppressed('suppressed exception', exc)
                            error = 'No se pudo guardar la foto en el almacenamiento externo.'
                        else:
                            user.profile_pic = unique_name
                        # Intentar eliminar la foto anterior si no es la por defecto
                        try:
                            if old_pic and old_pic.lower() != 'default.jpg':
                                safe_remove_upload(old_pic)
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
                    strip_image_metadata_in_place(save_path)
                    if not sync_public_upload_to_storage(unique_name, local_path=save_path, mime_type=mime):
                        try:
                            os.remove(save_path)
                        except Exception as exc:
                            _debug_log_suppressed('suppressed exception', exc)
                        error = 'No se pudo guardar la foto en el almacenamiento externo.'
                    old_pic = (user.profile_pic or '').strip()
                    if not error:
                        user.profile_pic = unique_name
                    try:
                        if old_pic and old_pic.lower() != 'default.jpg':
                            safe_remove_upload(old_pic)
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
                file_path = os.path.join(upload_folder, new_name)
                file.save(file_path)
                strip_image_metadata_in_place(file_path)
                if not sync_public_upload_to_storage(new_name, local_path=file_path, mime_type=file.mimetype):
                    try:
                        os.remove(file_path)
                    except Exception as exc:
                        _debug_log_suppressed('suppressed exception', exc)
                    return jsonify({'ok': False, 'error': 'No se pudo guardar la imagen en el almacenamiento externo.'}), 500
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
                file_path = os.path.join(upload_folder, new_name)
                with open(file_path, 'wb') as f:
                    f.write(raw)
                strip_image_metadata_in_place(file_path)
                if not sync_public_upload_to_storage(new_name, local_path=file_path, mime_type=mime):
                    try:
                        os.remove(file_path)
                    except Exception as exc:
                        _debug_log_suppressed('suppressed exception', exc)
                    return jsonify({'ok': False, 'error': 'No se pudo guardar la imagen en el almacenamiento externo.'}), 500
            else:
                return jsonify({'ok': False, 'error': 'Imagen inválida'}), 400

            # Borrar anterior si aplica
            old = (user.profile_pic or '').strip()
            user.profile_pic = new_name
            db.session.add(user)
            db.session.commit()

            try:
                if old and old.lower() != 'default.jpg':
                    safe_remove_upload(old)
            except Exception as exc:
                _debug_log_suppressed('suppressed exception', exc)
            url = url_for('uploaded_file', filename=new_name)
            return jsonify({'ok': True, 'url': url})
        except Exception as e:
            db.session.rollback()
            if app.debug:
                print('DEBUG avatar api error:', e)
            return jsonify({'ok': False, 'error': 'No se pudo actualizar el avatar.'}), 500

    def _build_user_profile_view_context(user, *, is_self: bool, page: int, per_page: int, viewer_can_review_private: bool):
        user_posts_query = (
            Post.query.options(
                selectinload(Post.author),
                selectinload(Post.meta),
            )
            .filter_by(user_id=user.id)
            .order_by(Post.created_at.desc())
        )
        if not viewer_can_review_private:
            user_posts_query = public_posts_query(user_posts_query)

        posts_pagination = user_posts_query.paginate(page=page, per_page=per_page, error_out=False)
        user_posts = posts_pagination.items
        annotate_user_post_visibility_state(user_posts)
        enrich_posts_for_cards(user_posts, current_user)
        report_count = posts_pagination.total

        stats_cache_key = ('profile_stats', user.id, viewer_can_review_private)
        cached_stats = get_runtime_cached_payload(stats_cache_key, 30) or {}
        total_likes = cached_stats.get('total_likes')
        total_comments = cached_stats.get('total_comments')
        if total_likes is None or total_comments is None:
            visible_posts_subquery = user_posts_query.order_by(None).with_entities(Post.id).subquery()
            total_likes = (
                db.session.query(func.count(Like.id))
                .join(visible_posts_subquery, Like.post_id == visible_posts_subquery.c.id)
                .scalar()
                or 0
            )
            total_comments = (
                db.session.query(func.count(Comment.id))
                .join(visible_posts_subquery, Comment.post_id == visible_posts_subquery.c.id)
                .scalar()
                or 0
            )
            set_runtime_cached_payload(
                stats_cache_key,
                {'total_likes': int(total_likes), 'total_comments': int(total_comments)},
                ttl_seconds=30,
                max_entries=128,
            )
        html = render_template(
            'user_profile.html',
            user=user,
            posts=user_posts,
            pagination=posts_pagination,
            report_count=report_count,
            total_likes=int(total_likes or 0),
            total_comments=int(total_comments or 0),
            is_self=is_self
        )
        return html

    def _build_safety_center_view_context():
        maybe_process_overdue_checkins(current_user.id, ttl_seconds=30)
        blocked_rows = (
            UserBlock.query.options(selectinload(UserBlock.blocked))
            .filter_by(blocker_id=current_user.id)
            .order_by(UserBlock.created_at.desc())
            .all()
        )
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

        contacts = (
            SafetyContact.query
            .filter_by(user_id=current_user.id)
            .order_by(SafetyContact.is_primary.desc(), SafetyContact.created_at.desc())
            .all()
        )
        active_checkin = (
            SafetyCheckin.query
            .filter_by(user_id=current_user.id, status='active')
            .order_by(SafetyCheckin.started_at.desc())
            .first()
        )

        avatar_tones = ['violet', 'rose', 'amber', 'emerald']
        contacts_payload = []
        for index, contact in enumerate(contacts):
            contacts_payload.append({
                'id': contact.id,
                'name': contact.name,
                'phone': contact.phone,
                'relationship': contact.relationship or '',
                'is_primary': bool(contact.is_primary),
                'avatar_tone': avatar_tones[index % len(avatar_tones)],
            })

        weekday_names = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']

        def format_trip_when(dt_obj):
            if not dt_obj:
                return 'Sin fecha'
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            if dt_obj.date() == today:
                day_label = 'Hoy'
            elif dt_obj.date() == yesterday:
                day_label = 'Ayer'
            else:
                day_label = weekday_names[dt_obj.weekday()]
            time_label = dt_obj.strftime('%I:%M %p').lstrip('0')
            return f'{day_label} · {time_label}'

        def format_duration_label(start_dt, end_dt):
            if not start_dt or not end_dt:
                return 'Sin registro'
            total_seconds = max(60, int((end_dt - start_dt).total_seconds()))
            hours, remainder = divmod(total_seconds, 3600)
            minutes = max(1, remainder // 60)
            if hours:
                if minutes:
                    return f'{hours} h {minutes} min'
                return f'{hours} h'
            return f'{minutes} min'

        history_limit = max(3, int(app.config.get('SAFETY_HISTORY_LIMIT', 6) or 6))
        history_rows = (
            SafetyCheckin.query
            .filter(
                SafetyCheckin.user_id == current_user.id,
                SafetyCheckin.status.in_(['arrived', 'cancelled', 'expired']),
            )
            .order_by(
                SafetyCheckin.arrived_at.desc(),
                SafetyCheckin.cancelled_at.desc(),
                SafetyCheckin.expires_at.desc(),
                SafetyCheckin.started_at.desc(),
                SafetyCheckin.id.desc(),
            )
            .limit(history_limit)
            .all()
        )

        total_finished = (
            SafetyCheckin.query
            .filter(
                SafetyCheckin.user_id == current_user.id,
                SafetyCheckin.status.in_(['arrived', 'cancelled', 'expired']),
            )
            .count()
        )

        route_styles = ['office', 'metro', 'uni']
        status_labels = {
            'arrived': ('Finalizada', 'success'),
            'cancelled': ('Cancelada', 'danger'),
            'expired': ('Expirada', 'danger'),
        }
        trip_items = []
        for index, checkin in enumerate(history_rows):
            number = max(1, total_finished - index)
            default_title = f'Trayecto {number}'
            raw_title = (getattr(checkin, 'title', None) or '').strip()
            destination = (checkin.destination or '').strip()
            display_title = raw_title or destination or default_title
            when_dt = checkin.arrived_at or checkin.cancelled_at or checkin.expires_at or checkin.started_at
            finished_dt = checkin.arrived_at or checkin.cancelled_at or checkin.expires_at or checkin.started_at
            status_label, status_variant = status_labels.get(checkin.status or 'arrived', ('Finalizada', 'success'))
            trip_items.append({
                'id': checkin.id,
                'title': raw_title,
                'default_title': default_title,
                'display_title': display_title,
                'destination': destination,
                'when_label': format_trip_when(when_dt),
                'route_style': route_styles[index % len(route_styles)],
                'badge_label': 'Con destino' if destination else 'Sin destino claro',
                'badge_variant': 'live' if destination else 'danger',
                'duration_label': format_duration_label(checkin.started_at, finished_dt),
                'contacts_label': '1 contacto' if (checkin.contact_name or checkin.contact_phone) else 'Sin contacto',
                'status_label': status_label,
                'status_variant': status_variant,
            })

        active_checkin_payload = None
        if active_checkin:
            active_checkin_payload = {
                'id': active_checkin.id,
                'destination': (active_checkin.destination or '').strip(),
                'display_destination': (active_checkin.destination or '').strip() or 'Destino en progreso',
                'started_at_iso': active_checkin.started_at.isoformat() if active_checkin.started_at else None,
                'expires_at_iso': active_checkin.expires_at.isoformat() if active_checkin.expires_at else None,
                'eta_minutes': int(active_checkin.eta_minutes or 30),
                'contact_name': (active_checkin.contact_name or '').strip(),
                'contact_phone': (active_checkin.contact_phone or '').strip(),
                'latitude': float(active_checkin.latitude) if active_checkin.latitude is not None else None,
                'longitude': float(active_checkin.longitude) if active_checkin.longitude is not None else None,
            }

        return render_template(
            'safety.html',
            blocked_users=blocked_users,
            contacts=contacts,
            contacts_payload=contacts_payload,
            active_checkin=active_checkin,
            active_checkin_payload=active_checkin_payload,
            trip_items=trip_items,
            initial_state='active' if active_checkin else 'idle',
        )

    @app.route('/user/<username>')
    def user_profile(username):
        user = User.query.filter_by(username=username).first_or_404()
        if current_user.is_authenticated and current_user.id != user.id and is_user_blocked_between(current_user.id, user.id):
            abort(404)
        is_self = (current_user.is_authenticated and current_user.id == user.id)
        page = request.args.get('page', 1, type=int)
        viewer_id = current_user.id if current_user.is_authenticated else 0
        page_cache_key = ('page_profile_shell', viewer_id, user.id, page)
        cached_response = get_cached_html_page(page_cache_key, 90)
        if cached_response is not None:
            return cached_response
        html = render_template(
            'user_profile_shell.html',
            user=user,
            is_self=is_self,
            page=page,
        )
        return set_cached_html_page(page_cache_key, html, ttl_seconds=90, max_entries=128)

    @app.route('/user/<username>/content')
    def user_profile_content(username):
        user = User.query.filter_by(username=username).first_or_404()
        if current_user.is_authenticated and current_user.id != user.id and is_user_blocked_between(current_user.id, user.id):
            abort(404)
        is_self = (current_user.is_authenticated and current_user.id == user.id)
        page = request.args.get('page', 1, type=int)
        per_page = app.config.get('PROFILE_POSTS_PAGE_SIZE', 12)
        viewer_can_review_private = bool(is_self or (current_user.is_authenticated and user_can_review_private_content(current_user)))
        viewer_id = current_user.id if current_user.is_authenticated else 0
        page_cache_key = ('page_profile_content', viewer_id, user.id, page, per_page, viewer_can_review_private)
        cached_response = get_cached_html_page(page_cache_key, 45)
        if cached_response is not None:
            return cached_response
        html = _build_user_profile_view_context(
            user,
            is_self=is_self,
            page=page,
            per_page=per_page,
            viewer_can_review_private=viewer_can_review_private,
        )
        return set_cached_html_page(page_cache_key, html, ttl_seconds=45, max_entries=128)

    @app.route('/api/user/block/<int:target_user_id>', methods=['POST'])
    @login_required
    def api_block_user(target_user_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'error': VERIFY_REQUIRED_MSG}), 403

        target = User.query.get_or_404(target_user_id)
        if target.id == current_user.id:
            return jsonify({'error': 'No puedes bloquearte a ti misma.'}), 400
        if user_is_protected_staff(target):
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
        if user_is_protected_staff(target):
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
        page_cache_key = ('page_safety_shell', current_user.id)
        cached_response = get_cached_html_page(page_cache_key, 90)
        if cached_response is not None:
            return cached_response
        html = render_template('safety_shell.html')
        return set_cached_html_page(page_cache_key, html, ttl_seconds=90, max_entries=96)

    @app.route('/safety/content')
    @login_required
    def safety_center_content():
        if current_user.is_authenticated and not is_user_verified(current_user):
            flash(VERIFY_REQUIRED_MSG, 'info')
            return redirect(url_for('verify_identity'))
        page_cache_key = ('page_safety_content', current_user.id)
        cached_response = get_cached_html_page(page_cache_key, 45)
        if cached_response is not None:
            return cached_response
        html = _build_safety_center_view_context()
        return set_cached_html_page(page_cache_key, html, ttl_seconds=45, max_entries=96)

    @app.route('/safety/checkin/<int:checkin_id>/summary')
    @login_required
    def checkin_summary(checkin_id: int):
        """Compatibilidad: antes mostraba el resumen de ruta; ahora redirige a Safety."""
        if current_user.is_authenticated and not is_user_verified(current_user):
            flash(VERIFY_REQUIRED_MSG, 'info')
            return redirect(url_for('verify_identity'))
        checkin = SafetyCheckin.query.get_or_404(checkin_id)
        if not user_has_permission(current_user, PERM_SAFETY_VIEW_ANY) and checkin.user_id != current_user.id:
            abort(403)
        if user_has_permission(current_user, PERM_SAFETY_VIEW_ANY) and checkin.user_id != current_user.id:
            return redirect(url_for('safety_workspace'))
        return redirect(url_for('safety_center'))

    @app.route('/emergency')
    def emergency_call():
        contacts_count = 0
        if current_user.is_authenticated:
            contacts_count = SafetyContact.query.filter_by(user_id=current_user.id).count()
        return render_template(
            'emergency.html',
            emergency_number=get_emergency_number(),
            contacts_count=contacts_count,
        )

    @app.route('/api/safety/emergency/trigger', methods=['POST'])
    def api_emergency_trigger():
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403

        payload = request.get_json(silent=True) or request.form or {}
        lat = parse_float(payload.get('lat'))
        lng = parse_float(payload.get('lng'))
        emergency_number = get_emergency_number()

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
        whatsapp_sent_count = 0
        sms_sent_count = 0
        for contact in contacts:
            delivered = False
            if send_whatsapp_via_twilio(contact.phone, sms_body):
                delivered = True
                whatsapp_sent_count += 1
            elif send_sms_via_twilio(contact.phone, sms_body):
                delivered = True
                sms_sent_count += 1
            if delivered:
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
            'contacts_notified_whatsapp': whatsapp_sent_count,
            'contacts_notified_sms': sms_sent_count,
            'maps_url': maps_url,
            'sms_auto_enabled': sms_sent_count > 0,
            'whatsapp_auto_enabled': whatsapp_sent_count > 0,
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
        invalidate_runtime_response_cache('page_safety_content')
        return jsonify({'ok': True, 'contact_id': contact.id})

    @app.route('/api/safety/contact/<int:contact_id>/update', methods=['POST'])
    @login_required
    def api_update_safety_contact(contact_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403

        contact = SafetyContact.query.get_or_404(contact_id)
        if contact.user_id != current_user.id:
            return jsonify({'ok': False, 'error': 'Acceso denegado'}), 403

        payload = request.get_json(silent=True) or request.form or {}
        name = (payload.get('name') or '').strip()
        relationship = (payload.get('relationship') or '').strip()
        phone = normalize_phone_simple(payload.get('phone'))

        if len(name) < 2:
            return jsonify({'ok': False, 'error': 'Nombre invalido'}), 400
        if not phone:
            return jsonify({'ok': False, 'error': 'Telefono invalido. Usa un numero real.'}), 400

        duplicate = (
            SafetyContact.query
            .filter(
                SafetyContact.user_id == current_user.id,
                SafetyContact.phone == phone,
                SafetyContact.id != contact.id,
            )
            .first()
        )
        if duplicate:
            return jsonify({'ok': False, 'error': 'Ese telefono ya existe'}), 400

        contact.name = name
        contact.phone = phone
        contact.relationship = relationship or None
        db.session.add(contact)
        db.session.commit()
        invalidate_runtime_response_cache('page_safety_content')
        return jsonify({'ok': True})

    @app.route('/api/safety/contact/<int:contact_id>/delete', methods=['POST'])
    @login_required
    def api_delete_safety_contact(contact_id):
        if current_user.is_authenticated and not is_user_verified(current_user):
            return jsonify({'ok': False, 'error': VERIFY_REQUIRED_MSG}), 403
        contact = SafetyContact.query.get_or_404(contact_id)
        if contact.user_id != current_user.id and not user_has_permission(current_user, PERM_SAFETY_VIEW_ANY):
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

        invalidate_runtime_response_cache('page_safety_content')
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
        invalidate_runtime_response_cache('page_safety_content')
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
        invalidate_runtime_response_cache('page_safety_content')

        return jsonify({
            'ok': True,
            'checkin_id': checkin.id,
            'destination': (checkin.destination or '').strip(),
            'expires_at': checkin.expires_at.isoformat() if checkin.expires_at else None,
            'started_at': checkin.started_at.isoformat() if checkin.started_at else None,
            'eta_minutes': int(checkin.eta_minutes or eta_minutes),
            'latitude': float(checkin.latitude) if checkin.latitude is not None else None,
            'longitude': float(checkin.longitude) if checkin.longitude is not None else None,
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
        invalidate_runtime_response_cache('page_safety_content')
        return jsonify({
            'ok': True,
            'checkin_id': checkin.id,
            'redirect_url': url_for('safety_center'),
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
        invalidate_runtime_response_cache('page_safety_content')
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
        if not user_has_permission(current_user, PERM_SAFETY_VIEW_ANY) and checkin.user_id != current_user.id:
            return jsonify({'ok': False, 'error': 'Acceso denegado.'}), 403
        if checkin.status != 'arrived':
            return jsonify({'ok': False, 'error': 'Solo puedes renombrar trayectos finalizados.'}), 400

        checkin.title = title or None
        db.session.add(checkin)
        db.session.commit()
        invalidate_runtime_response_cache('page_safety_content')
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
        if not user_has_permission(current_user, PERM_SAFETY_VIEW_ANY) and checkin.user_id != current_user.id:
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
        if not user_has_permission(current_user, PERM_SAFETY_VIEW_ANY) and checkin.user_id != current_user.id:
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

        if user_has_permission(current_user, PERM_SAFETY_VIEW_ANY) and checkin.user_id != current_user.id:
            record_audit_event(
                'safety.route_points.view',
                workspace='safety',
                target_user=checkin.user,
                resource_type='safety_checkin',
                resource_id=checkin.id,
                summary='Consultó la ruta detallada de un check-in.',
                details={
                    'points_count': len(points),
                    'checkin_status': checkin.status,
                },
            )

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
    @permission_required(PERM_SAFETY_RESOLVE_PANIC, json_only=True)
    def admin_resolve_panic(panic_id):
        event = PanicEvent.query.get_or_404(panic_id)
        event.status = 'resolved'
        event.resolved_at = datetime.now()
        event.resolved_by = current_user.id
        db.session.add(event)
        db.session.commit()
        record_audit_event(
            'panic.resolve',
            workspace='safety',
            target_user=event.user,
            resource_type='panic_event',
            resource_id=event.id,
            summary='Marcó como resuelto un evento de pánico.',
            details={
                'status': event.status,
                'contact_name': event.contact_name or '',
            },
        )
        return jsonify({'ok': True})

    # CLI helper para inicializar DB
    @app.cli.command('init-db')
    def init_db():
        ensure_startup_schema()
        print('Base de datos inicializada')

    @app.cli.command('purge-audit-logs')
    def purge_audit_logs_cli():
        deleted = purge_expired_audit_logs()
        print(f'Audit logs purgados: {deleted} (retención {audit_log_retention_days()} días)')

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
        from urllib.parse import urlencode, quote
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
        if app.config.get('RUN_STARTUP_SCHEMA_SYNC'):
            try:
                ensure_startup_schema()
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
        if app.config.get('RUN_STARTUP_SCHEMA_SYNC'):
            ensure_startup_schema()
    # Ejecutar con SocketIO (si no hay eventlet/gevent, usa Werkzeug). 
    # allow_unsafe_werkzeug=True evita el warning en modo desarrollo
    socketio.run(
        app,
        host=os.environ.get('HOST', '127.0.0.1'),
        port=port,
        debug=app.config.get('DEBUG', False),
        allow_unsafe_werkzeug=bool(app.config.get('DEBUG', False)),
    )
