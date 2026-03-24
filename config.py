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
        return f"sqlite:///{os.path.join(instance_dir, 'instagram_clone.db')}"

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

    # Zona horaria "de negocio" para cálculos de "hoy" (p. ej. reportes del día).
    # Se usa para convertir límites locales -> UTC naive (created_at se guarda en UTC naive).
    APP_TIMEZONE = os.environ.get('APP_TIMEZONE') or 'America/Monterrey'

    # Usar ruta absoluta al archivo de BD dentro de instance/
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(SQLALCHEMY_DATABASE_URI)

    # Configuración de archivos
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # 32MB máximo
    # Extensiones permitidas (añadimos formatos comunes de móviles)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}

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

    # Configuración de correo (para OTP)
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or ''
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or ''
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME

    @staticmethod
    def init_app(app):
        pass
