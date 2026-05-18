#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def normalize_database_url(raw: str) -> str:
    url = (raw or '').strip()
    if not url:
        raise ValueError('DATABASE_URL no está definido.')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return url


def redact_url(raw: str) -> str:
    if '@' not in raw or '://' not in raw:
        return raw
    scheme, rest = raw.split('://', 1)
    if '@' not in rest:
        return raw
    creds, host = rest.rsplit('@', 1)
    user = creds.split(':', 1)[0] if creds else ''
    if user:
        return f'{scheme}://{user}:***@{host}'
    return f'{scheme}://***@{host}'


def main() -> int:
    url = normalize_database_url(os.environ.get('DATABASE_URL', ''))
    engine = create_engine(url, pool_pre_ping=True)

    with engine.connect() as conn:
        db_name = conn.execute(text('SELECT current_database()')).scalar()
        user_name = conn.execute(text('SELECT current_user')).scalar()
        version = conn.execute(text('SHOW server_version')).scalar()
        ssl = conn.execute(
            text(
                """
                SELECT ssl
                FROM pg_stat_ssl
                WHERE pid = pg_backend_pid()
                """
            )
        ).scalar()

    print('Conexion OK')
    print(f'URL: {redact_url(url)}')
    print(f'Base: {db_name}')
    print(f'Usuaria: {user_name}')
    print(f'Version: {version}')
    print(f'SSL: {"on" if ssl else "off"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
