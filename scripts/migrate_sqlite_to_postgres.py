#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, select
from sqlalchemy.engine import Engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def normalize_database_url(raw: str) -> str:
    url = (raw or '').strip()
    if not url:
        raise ValueError('DATABASE_URL está vacío.')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return url


def build_default_sqlite_url() -> str:
    return f"sqlite:///{PROJECT_ROOT / 'instance' / 'Violeta-App.db'}"


def batched_rows(conn, table, batch_size: int):
    result = conn.execute(table.select())
    while True:
        rows = result.fetchmany(batch_size)
        if not rows:
            break
        yield [dict(row._mapping) for row in rows]


def ensure_empty_target(engine: Engine) -> None:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as conn:
        for table in metadata.sorted_tables:
            count = conn.execute(select(func.count()).select_from(table)).scalar()
            if count and int(count) > 0:
                raise RuntimeError(
                    f'La tabla destino "{table.name}" ya tiene datos. '
                    'Usa una base vacía o vacíala antes de migrar.'
                )


def sync_postgres_sequences(engine: Engine, metadata: MetaData) -> None:
    if engine.dialect.name != 'postgresql':
        return

    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            pk_cols = list(table.primary_key.columns)
            if len(pk_cols) != 1:
                continue
            pk_col = pk_cols[0]
            if pk_col.name != 'id':
                continue
            stmt = select(
                func.setval(
                    func.pg_get_serial_sequence(table.fullname, 'id'),
                    func.coalesce(select(func.max(pk_col)).scalar_subquery(), 1),
                    select((func.count() > 0)).select_from(table).scalar_subquery(),
                )
            )
            conn.execute(stmt)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Migra datos desde SQLite local a PostgreSQL administrado.'
    )
    parser.add_argument(
        '--sqlite-url',
        default=os.environ.get('SQLITE_SOURCE_URL') or build_default_sqlite_url(),
        help='URL SQLAlchemy de SQLite origen. Default: instance/Violeta-App.db',
    )
    parser.add_argument(
        '--postgres-url',
        default=os.environ.get('DATABASE_URL', ''),
        help='URL SQLAlchemy destino para PostgreSQL. Default: DATABASE_URL',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Cantidad de filas a insertar por lote.',
    )
    args = parser.parse_args()

    sqlite_url = args.sqlite_url.strip()
    postgres_url = normalize_database_url(args.postgres_url)

    os.environ['DATABASE_URL'] = postgres_url

    from app import app, db  # Imported after DATABASE_URL is set on purpose.

    source_engine = create_engine(sqlite_url)
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)

    with app.app_context():
        db.create_all()
        target_engine = db.engine
        target_metadata = MetaData()
        target_metadata.reflect(bind=target_engine)

        ensure_empty_target(target_engine)

        ordered_target_tables = list(target_metadata.sorted_tables)
        seen_names = {table.name for table in ordered_target_tables}
        for table in source_metadata.sorted_tables:
            if table.name not in seen_names and table.name in target_metadata.tables:
                ordered_target_tables.append(target_metadata.tables[table.name])

        with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
            for target_table in ordered_target_tables:
                source_table = source_metadata.tables.get(target_table.name)
                if source_table is None:
                    print(f'SKIP {target_table.name}: no existe en origen.')
                    continue

                inserted = 0
                for rows in batched_rows(source_conn, source_table, args.batch_size):
                    target_conn.execute(target_table.insert(), rows)
                    inserted += len(rows)

                print(f'OK {target_table.name}: {inserted} filas')

        sync_postgres_sequences(target_engine, target_metadata)

    print('Migración completada.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
