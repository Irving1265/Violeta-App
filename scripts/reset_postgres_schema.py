#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / '.env')


def normalize_database_url(raw: str) -> str:
    url = (raw or '').strip()
    if not url:
        raise ValueError('DATABASE_URL no está definido.')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return url


def main() -> int:
    url = normalize_database_url(os.environ.get('DATABASE_URL', ''))
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))
        conn.execute(text('GRANT ALL ON SCHEMA public TO postgres'))
        conn.execute(text('GRANT ALL ON SCHEMA public TO public'))
    print('Schema public reiniciado.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
