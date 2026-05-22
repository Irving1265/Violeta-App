#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


SECRET_NAMES = {
    'SECRET_KEY',
    'DATABASE_URL',
    'SUPABASE_SERVICE_ROLE_KEY',
    'MAIL_PASSWORD',
    'RESEND_API_KEY',
    'REDIS_URL',
}

PLACEHOLDER_PATTERN = re.compile(
    r'(tu_|your_|placeholder|pon_aqui|cambia|xxx|tu-dominio|example\.com)',
    re.I,
)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f'No existe el archivo: {path}')

    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def env_value(name: str, file_values: dict[str, str]) -> str:
    if name in file_values:
        return file_values[name].strip()
    return (os.environ.get(name) or '').strip()


def redact(name: str, value: str) -> str:
    if not value:
        return ''
    if name in SECRET_NAMES:
        if len(value) <= 8:
            return '***'
        return f'{value[:4]}...{value[-4:]}'
    return value


def issue(level: str, code: str, message: str) -> dict[str, str]:
    return {'level': level, 'code': code, 'message': message}


def is_truthy(value: str) -> bool:
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def looks_placeholder(value: str) -> bool:
    return bool(value and PLACEHOLDER_PATTERN.search(value))


def audit(file_values: dict[str, str]) -> dict[str, object]:
    issues: list[dict[str, str]] = []

    app_env = env_value('APP_ENV', file_values).lower()
    if app_env not in {'production', 'staging'}:
        issues.append(issue(
            'warning',
            'app_env_not_production_like',
            'Usa APP_ENV=production o APP_ENV=staging para validar Render.',
        ))

    secret_key = env_value('SECRET_KEY', file_values)
    if not secret_key or re.search(r'pon_aqui|cambia|secret|password', secret_key, re.I):
        issues.append(issue('error', 'missing_secret_key', 'Define SECRET_KEY real, larga y persistente.'))

    database_url = env_value('DATABASE_URL', file_values)
    if not database_url:
        issues.append(issue('error', 'missing_database_url', 'DATABASE_URL debe apuntar a PostgreSQL administrado.'))
    elif not database_url.startswith(('postgresql://', 'postgresql+psycopg://', 'postgres://')):
        issues.append(issue('error', 'database_not_postgres', 'En Render usa PostgreSQL, no SQLite/local.'))

    if env_value('PREFERRED_URL_SCHEME', file_values).lower() != 'https':
        issues.append(issue('warning', 'preferred_scheme_not_https', 'Configura PREFERRED_URL_SCHEME=https.'))

    if not is_truthy(env_value('SESSION_COOKIE_SECURE', file_values)):
        issues.append(issue('warning', 'session_cookie_not_secure', 'Configura SESSION_COOKIE_SECURE=true en HTTPS.'))

    if not is_truthy(env_value('REMEMBER_COOKIE_SECURE', file_values)):
        issues.append(issue('warning', 'remember_cookie_not_secure', 'Configura REMEMBER_COOKIE_SECURE=true en HTTPS.'))

    upload_backend = env_value('UPLOAD_BACKEND', file_values).lower() or 'local'
    if upload_backend != 'supabase':
        issues.append(issue(
            'error',
            'local_uploads',
            'Configura UPLOAD_BACKEND=supabase para evitar perder imágenes en disco efímero.',
        ))
    else:
        for name in ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_STORAGE_BUCKET'):
            value = env_value(name, file_values)
            if not value:
                issues.append(issue('error', f'missing_{name.lower()}', f'Falta {name}.'))
            elif looks_placeholder(value):
                issues.append(issue('error', f'placeholder_{name.lower()}', f'{name} parece ser un placeholder, usa el valor real.'))
        if env_value('SUPABASE_URL', file_values) and not env_value('SUPABASE_URL', file_values).startswith('https://'):
            issues.append(issue('error', 'supabase_url_not_https', 'SUPABASE_URL debe usar https://.'))

    mail_method = env_value('MAIL_DELIVERY_METHOD', file_values).lower()
    if mail_method == 'resend':
        for name in ('RESEND_API_KEY', 'RESEND_FROM'):
            value = env_value(name, file_values)
            if not value:
                issues.append(issue('error', f'missing_{name.lower()}', f'Falta {name}.'))
            elif looks_placeholder(value):
                issues.append(issue('error', f'placeholder_{name.lower()}', f'{name} parece ser un placeholder, usa el valor real.'))
    elif mail_method == 'smtp':
        if not env_value('MAIL_SERVER', file_values):
            issues.append(issue('error', 'missing_mail_server', 'Falta MAIL_SERVER.'))
        if not (env_value('MAIL_DEFAULT_SENDER', file_values) or env_value('MAIL_USERNAME', file_values)):
            issues.append(issue('error', 'missing_mail_sender', 'Falta MAIL_DEFAULT_SENDER o MAIL_USERNAME.'))
        if not env_value('MAIL_PASSWORD', file_values):
            issues.append(issue('error', 'missing_mail_password', 'Falta MAIL_PASSWORD para SMTP.'))
    else:
        issues.append(issue(
            'error',
            'mail_not_configured',
            'Configura MAIL_DELIVERY_METHOD=resend o MAIL_DELIVERY_METHOD=smtp.',
        ))

    if not env_value('REDIS_URL', file_values):
        issues.append(issue('warning', 'redis_not_configured', 'REDIS_URL es recomendado para cache compartido y multiinstancia.'))

    snapshot_keys = [
        'APP_ENV',
        'PREFERRED_URL_SCHEME',
        'DATABASE_URL',
        'UPLOAD_BACKEND',
        'SUPABASE_URL',
        'SUPABASE_SERVICE_ROLE_KEY',
        'SUPABASE_STORAGE_BUCKET',
        'MAIL_DELIVERY_METHOD',
        'RESEND_FROM',
        'RESEND_API_KEY',
        'MAIL_SERVER',
        'MAIL_DEFAULT_SENDER',
        'MAIL_PASSWORD',
        'REDIS_URL',
        'SESSION_COOKIE_SECURE',
        'REMEMBER_COOKIE_SECURE',
    ]

    errors = [item for item in issues if item['level'] == 'error']
    warnings = [item for item in issues if item['level'] == 'warning']
    return {
        'status': 'error' if errors else ('warning' if warnings else 'ok'),
        'error_count': len(errors),
        'warning_count': len(warnings),
        'issues': issues,
        'redacted_config': {
            key: redact(key, env_value(key, file_values))
            for key in snapshot_keys
            if env_value(key, file_values)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Audita variables de producción de Violeta sin imprimir secretos.')
    parser.add_argument('--env-file', type=Path, help='Archivo .env a auditar, por ejemplo .env.production.')
    args = parser.parse_args()

    file_values: dict[str, str] = {}
    if args.env_file:
        file_values = load_env_file(args.env_file)

    payload = audit(file_values)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload['status'] == 'error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
