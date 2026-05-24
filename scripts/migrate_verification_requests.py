#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Añadir el directorio raíz al path para poder importar módulos si fuera necesario
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Cargar el archivo .env
dotenv_path = PROJECT_ROOT / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path)

def normalize_database_url(raw: str) -> str:
    url = (raw or '').strip()
    if not url:
        # Fallback a SQLite si no está especificado DATABASE_URL
        instance_dir = PROJECT_ROOT / 'instance'
        return f"sqlite:///{instance_dir / 'Violeta-App.db'}"
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
    raw_url = os.environ.get('DATABASE_URL', '')
    url = normalize_database_url(raw_url)
    
    print(f"Base de datos objetivo: {redact_url(url)}")
    engine = create_engine(url, pool_pre_ping=True)
    dialect = engine.dialect.name
    print(f"Dialecto detectado: {dialect}")

    columns_to_add = {
        'evidence_file_path': 'VARCHAR(255)',
        'evidence_type': 'VARCHAR(20)',
        'mime_type': 'VARCHAR(100)',
        'file_size': 'INTEGER',
        'note': 'TEXT',
        'consent_accepted': 'BOOLEAN NOT NULL DEFAULT FALSE' if dialect == 'postgresql' else 'BOOLEAN NOT NULL DEFAULT 0',
        'consent_accepted_at': 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME',
        'decision_reason': 'TEXT',
        'evidence_expires_at': 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME',
        'evidence_deleted_at': 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME',
    }

    try:
        with engine.begin() as conn:
            # Obtener columnas existentes en base al dialecto
            if dialect == 'postgresql':
                res = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='verification_request'"
                ))
                existing_cols = {row[0].lower() for row in res}
            elif dialect == 'sqlite':
                res = conn.execute(text("PRAGMA table_info(verification_request)"))
                existing_cols = {row[1].lower() for row in res}
            else:
                print(f"Error: Dialecto '{dialect}' no soportado directamente.")
                return 1

            if not existing_cols:
                print("Error: La tabla 'verification_request' no existe en la base de datos.")
                print("Por favor, asegúrate de que la base de datos inicial ya esté creada.")
                return 1

            print(f"Columnas existentes en 'verification_request': {sorted(list(existing_cols))}")

            # Aplicar ALTER TABLE solo para las columnas faltantes (idempotente)
            added_count = 0
            for col_name, col_type in columns_to_add.items():
                col_name_lower = col_name.lower()
                if col_name_lower not in existing_cols:
                    print(f"Añadiendo columna faltante: '{col_name}' ({col_type})...")
                    conn.execute(text(f"ALTER TABLE verification_request ADD COLUMN {col_name} {col_type}"))
                    added_count += 1
                else:
                    print(f"La columna '{col_name}' ya existe. Omitiendo.")

            if added_count > 0:
                print(f"Migración completada con éxito. Se agregaron {added_count} columnas.")
            else:
                print("No se requirieron cambios. La estructura ya está actualizada.")
                
            return 0

    except Exception as e:
        print(f"Error crítico durante la migración: {e}", file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
