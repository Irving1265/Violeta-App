# PostgreSQL administrado

Este proyecto ya puede leer `DATABASE_URL` para usar PostgreSQL en lugar de SQLite.

## 1. Instala dependencias

```bash
cd "/Users/irv.cantu/Desktop/Versiones/Todo bien/Violeta-App"
./.venv/bin/pip install -r requirements.txt
```

## 2. Configura variables

En tu `.env` o en la terminal:

```bash
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
export DATABASE_URL="postgresql+psycopg://usuario:password@host:5432/violeta"
export DATABASE_REQUIRE_SSL=true
export DATABASE_SSLMODE=require
```

Notas:
- Si tu proveedor te entrega `postgres://...`, la app lo normaliza automáticamente.
- Si tu proveedor ya incluye `sslmode=...` en la URL, la app no lo duplica.

## 3. Migra datos desde SQLite

El script copia todas las tablas conocidas desde `instance/Violeta-App.db` hacia la base PostgreSQL vacía.

```bash
cd "/Users/irv.cantu/Desktop/Versiones/Todo bien/Violeta-App"
export DATABASE_URL="postgresql+psycopg://usuario:password@host:5432/violeta"
./.venv/bin/python scripts/migrate_sqlite_to_postgres.py
```

Si tu SQLite origen está en otra ruta:

```bash
./.venv/bin/python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-url "sqlite:////ruta/completa/a/otra.db"
```

## 4. Arranca la app usando PostgreSQL

```bash
cd "/Users/irv.cantu/Desktop/Versiones/Todo bien/Violeta-App"
export DATABASE_URL="postgresql+psycopg://usuario:password@host:5432/violeta"
./.venv/bin/python app.py
```

## 5. Qué cambió en la app

- `config.py` ahora:
  - usa `DATABASE_URL` como fuente principal,
  - normaliza `postgres://` a `postgresql://`,
  - agrega `sslmode=require` por defecto en PostgreSQL,
  - habilita `pool_pre_ping`,
  - habilita `pool_size`, `max_overflow` y `pool_recycle`.

- La app sigue soportando SQLite en local si `DATABASE_URL` no está definido.

## 6. Recomendación operativa

Antes de apuntar producción a PostgreSQL:

1. prueba migración en una base nueva,
2. valida login, chat, reportes y seguridad,
3. respalda tu SQLite original,
4. cambia `DATABASE_URL` sólo cuando verifiques que todo respondió bien.
