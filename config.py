import os
import secrets
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

basedir = os.path.dirname(os.path.abspath(__file__))
instance_dir = os.path.join(basedir, 'instance')
os.makedirs(instance_dir, exist_ok=True)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def _database_url() -> str:
    raw = (os.environ.get('DATABASE_URL') or '').strip()
    if not raw:
        return f"sqlite:///{os.path.join(instance_dir, 'Violeta-App.db')}"

    if raw.startswith('postgres://'):
        raw = 'postgresql://' + raw[len('postgres://'):]

    sslmode = (os.environ.get('DATABASE_SSLMODE') or '').strip()
    require_ssl = _env_bool('DATABASE_REQUIRE_SSL', raw.startswith('postgresql'))
    if raw.startswith('postgresql') and require_ssl:
        parts = urlsplit(raw)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.setdefault('sslmode', sslmode or 'require')
        raw = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    return raw


def _engine_options(database_uri: str) -> dict:
    options: dict[str, object] = {'pool_pre_ping': True}
    if database_uri.startswith('postgresql'):
        options.update({
            'pool_recycle': int(os.environ.get('DATABASE_POOL_RECYCLE') or 1800),
            'pool_size': int(os.environ.get('DATABASE_POOL_SIZE') or 10),
            'max_overflow': int(os.environ.get('DATABASE_MAX_OVERFLOW') or 20),
        })
    return options


class Config:
    # Never use a hardcoded fallback secret in source control.
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_urlsafe(64)
    DEBUG = _env_bool('FLASK_DEBUG', False)
    APP_ENV = (os.environ.get('APP_ENV') or ('development' if DEBUG else 'production')).strip().lower()
    PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME') or ('https' if not DEBUG else 'http')
    PUBLIC_BETA_VERSION = (os.environ.get('PUBLIC_BETA_VERSION') or 'Beta v1.1').strip()
    SUPPORT_EMAIL = (os.environ.get('SUPPORT_EMAIL') or 'violetaapp38@gmail.com').strip()

    # Zona horaria "de negocio" para cálculos de "hoy" (p. ej. reportes del día).
    # Se usa para convertir límites locales -> UTC naive (created_at se guarda en UTC naive).
    APP_TIMEZONE = os.environ.get('APP_TIMEZONE') or 'America/Monterrey'

    # Usar ruta absoluta al archivo de BD dentro de instance/
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(SQLALCHEMY_DATABASE_URI)
    RUN_STARTUP_SCHEMA_SYNC = _env_bool(
        'RUN_STARTUP_SCHEMA_SYNC',
        SQLALCHEMY_DATABASE_URI.startswith(('sqlite', 'postgresql')),
    )

    # Configuración de archivos
    UPLOAD_FOLDER = (
        os.environ.get('UPLOAD_FOLDER')
        or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    )
    MAX_CONTENT_LENGTH = 40 * 1024 * 1024  # 40MB máximo para videos de verificación
    # Extensiones permitidas (añadimos formatos comunes de móviles)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}
    UPLOAD_BACKEND = (os.environ.get('UPLOAD_BACKEND') or 'local').strip().lower()
    SUPABASE_URL = (os.environ.get('SUPABASE_URL') or '').strip().rstrip('/')
    SUPABASE_SERVICE_ROLE_KEY = (os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
    SUPABASE_STORAGE_BUCKET = (os.environ.get('SUPABASE_STORAGE_BUCKET') or 'uploads').strip()
    PUBLIC_UPLOAD_DIRECT_URLS = _env_bool('PUBLIC_UPLOAD_DIRECT_URLS', False)

    # Configuración de sesión
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = _env_bool('REMEMBER_COOKIE_SECURE', SESSION_COOKIE_SECURE)
    WTF_CSRF_TIME_LIMIT = 3600

    # None => same-origin policy by default in Flask-SocketIO.
    SOCKETIO_CORS_ALLOWED_ORIGINS = os.environ.get('SOCKETIO_CORS_ALLOWED_ORIGINS')

    # Cache compartido opcional para producción.
    REDIS_URL = (os.environ.get('REDIS_URL') or '').strip()
    CACHE_NAMESPACE = (os.environ.get('CACHE_NAMESPACE') or 'violeta').strip()

    # Paginación y límites de vistas pesadas.
    FEED_PAGE_SIZE = max(1, int(os.environ.get('FEED_PAGE_SIZE') or 3))
    SLOW_REQUEST_LOG_MS = max(1, int(os.environ.get('SLOW_REQUEST_LOG_MS') or 750))
    STATIC_ASSET_CACHE_SECONDS = max(0, int(os.environ.get('STATIC_ASSET_CACHE_SECONDS') or 604800))
    PUBLIC_UPLOAD_CACHE_SECONDS = max(0, int(os.environ.get('PUBLIC_UPLOAD_CACHE_SECONDS') or 604800))
    OPTIMIZED_UPLOAD_CACHE_SECONDS = max(0, int(os.environ.get('OPTIMIZED_UPLOAD_CACHE_SECONDS') or 31536000))
    BACKGROUND_JOBS_ENABLED = _env_bool('BACKGROUND_JOBS_ENABLED', True)
    BACKGROUND_JOBS_INLINE = _env_bool('BACKGROUND_JOBS_INLINE', False)
    BACKGROUND_JOB_WORKERS = max(1, int(os.environ.get('BACKGROUND_JOB_WORKERS') or 2))
    BACKGROUND_JOB_MAX_RETRIES = max(0, int(os.environ.get('BACKGROUND_JOB_MAX_RETRIES') or 2))
    BACKGROUND_JOB_RETRY_DELAY_SECONDS = max(0.0, float(os.environ.get('BACKGROUND_JOB_RETRY_DELAY_SECONDS') or 0.5))
    BACKGROUND_JOB_EVENT_RETENTION_DAYS = max(0, int(os.environ.get('BACKGROUND_JOB_EVENT_RETENTION_DAYS') or 30))
    ASYNC_IMAGE_PROCESSING = _env_bool('ASYNC_IMAGE_PROCESSING', True)
    ASYNC_UPLOAD_OPTIMIZATION = _env_bool('ASYNC_UPLOAD_OPTIMIZATION', True)
    ASYNC_REVERSE_GEOCODING = _env_bool('ASYNC_REVERSE_GEOCODING', True)
    ASYNC_EMAIL_DELIVERY = _env_bool('ASYNC_EMAIL_DELIVERY', True)
    PROFILE_POSTS_PAGE_SIZE = max(1, int(os.environ.get('PROFILE_POSTS_PAGE_SIZE') or 12))
    ADMIN_USERS_LIMIT = max(5, int(os.environ.get('ADMIN_USERS_LIMIT') or 8))
    ADMIN_POSTS_LIMIT = max(6, int(os.environ.get('ADMIN_POSTS_LIMIT') or 6))
    ADMIN_REPORTED_POSTS_LIMIT = max(6, int(os.environ.get('ADMIN_REPORTED_POSTS_LIMIT') or 8))
    ADMIN_CHAT_ROOMS_LIMIT = max(5, int(os.environ.get('ADMIN_CHAT_ROOMS_LIMIT') or 8))
    ADMIN_REPORTS_LIMIT = max(5, int(os.environ.get('ADMIN_REPORTS_LIMIT') or 8))
    ADMIN_VERIFICATIONS_LIMIT = max(5, int(os.environ.get('ADMIN_VERIFICATIONS_LIMIT') or 8))
    ADMIN_CHECKINS_LIMIT = max(5, int(os.environ.get('ADMIN_CHECKINS_LIMIT') or 10))
    ADMIN_PANIC_EVENTS_LIMIT = max(5, int(os.environ.get('ADMIN_PANIC_EVENTS_LIMIT') or 8))

    # Configuración de correo (para OTP y recuperación)
    MAIL_DELIVERY_METHOD = (os.environ.get('MAIL_DELIVERY_METHOD') or '').strip().lower()
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or ''
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or ''
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY') or ''
    RESEND_API_URL = os.environ.get('RESEND_API_URL') or 'https://api.resend.com/emails'
    RESEND_FROM = os.environ.get('RESEND_FROM') or MAIL_DEFAULT_SENDER
    RESEND_REPLY_TO = os.environ.get('RESEND_REPLY_TO') or ''

    @staticmethod
    def init_app(app):
        pass
