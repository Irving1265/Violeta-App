# Preparacion De Staging Y Produccion

Esta guia define el orden recomendado para dejar Violeta lista en un entorno real con HTTPS, base administrada, storage persistente, Redis y correo.

## Objetivo

Evitar estos fallos antes de exponer la app a usuarias:

- perdida de imagenes por disco efimero,
- sesiones inseguras en HTTPS,
- emails de recuperacion sin entregar,
- cache o background jobs inconsistentes entre instancias,
- deploys que pasan localmente pero fallan en telefono o admin.

## Entornos

Usa dos entornos separados:

- `staging`: copia segura para probar deploys y migraciones.
- `production`: entorno usado por usuarias reales.

Variables base:

```bash
APP_ENV=staging
APP_TIMEZONE=America/Monterrey
PREFERRED_URL_SCHEME=https
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
```

En produccion cambia:

```bash
APP_ENV=production
```

## Render Con Servicio Y Base Ya Creados

Si ya tienes un Web Service y una base PostgreSQL en Render, no necesitas agregar `render.yaml` para este paso. Configuralo desde el panel de Render con estos valores:

```text
Build Command: pip install -r requirements.txt
Start Command: python app.py
Health Check Path: /healthz
```

Variables clave en Render:

```bash
APP_ENV=production
HOST=0.0.0.0
PREFERRED_URL_SCHEME=https
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
DATABASE_URL=<internal-database-url-de-render>
DATABASE_REQUIRE_SSL=true
DATABASE_SSLMODE=require
RUN_STARTUP_SCHEMA_SYNC=true
UPLOAD_BACKEND=supabase
BACKGROUND_JOBS_ENABLED=true
BACKGROUND_JOBS_INLINE=false
ASYNC_IMAGE_PROCESSING=true
ASYNC_UPLOAD_OPTIMIZATION=true
ASYNC_REVERSE_GEOCODING=true
ASYNC_EMAIL_DELIVERY=true
```

Notas especificas para Render:

- Render define `PORT` automaticamente; no lo fijes manualmente salvo que tengas una razon concreta.
- Usa `HOST=0.0.0.0`; si el proceso escucha solo en `127.0.0.1`, Render no puede exponer la app correctamente.
- Usa la URL interna de PostgreSQL si el Web Service y la base estan en Render; evita la URL externa cuando no sea necesaria.
- No uses `UPLOAD_BACKEND=local` en produccion a menos que hayas contratado y montado un disco persistente para uploads. Para esta app es mas seguro usar Supabase Storage.
- No cambies el comando a `gunicorn app:app` sin configurar WebSockets; este repo usa Flask-SocketIO y actualmente esta preparado para arrancar con `python app.py`.
- Redis puede ser Render Key Value, Upstash u otro proveedor. Si no tienes Redis, la app puede correr, pero la cache no sera compartida entre instancias.

Para cerrar especificamente los warnings `local_uploads` y `mail_not_configured`, sigue
`docs/render-env-setup.md` y valida antes de desplegar:

```bash
python scripts/production_env_audit.py --env-file .env.production
flask --app app:app preflight-check --strict
```

## Variables Minimas Requeridas

### Seguridad

```bash
SECRET_KEY=<valor-largo-generado>
APP_ENV=production
PREFERRED_URL_SCHEME=https
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
```

Genera `SECRET_KEY` con:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

No reutilices `SECRET_KEY` de desarrollo en staging o produccion.

### Base De Datos

```bash
DATABASE_URL=postgresql+psycopg://usuario:password@host:5432/violeta
DATABASE_REQUIRE_SSL=true
DATABASE_SSLMODE=require
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_RECYCLE=1800
RUN_STARTUP_SCHEMA_SYNC=true
```

Recomendacion:

- staging y produccion deben usar bases distintas;
- antes de migrar datos reales, genera backup;
- no uses SQLite en produccion.

### Storage Persistente

Para desarrollo:

```bash
UPLOAD_BACKEND=local
```

Para staging/produccion:

```bash
UPLOAD_BACKEND=supabase
SUPABASE_URL=https://TU_PROYECTO.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_STORAGE_BUCKET=uploads
```

Checklist de Supabase Storage:

- bucket `uploads` creado;
- bucket publico si las imagenes deben verse sin URLs firmadas;
- policy de lectura publica configurada;
- service role solo en backend, nunca en frontend;
- prueba una imagen de post, avatar y adjunto de chat.

Si ya tienes uploads locales y vas a migrarlos:

```bash
python scripts/sync_public_uploads_to_supabase_storage.py
```

Ejecuta el script solo despues de configurar `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` y `SUPABASE_STORAGE_BUCKET`.

### Redis

Redis es recomendado para cache compartido cuando hay mas de un proceso o instancia.

```bash
REDIS_URL=rediss://default:password@host:6379/0
CACHE_NAMESPACE=violeta-production
```

Usa namespaces distintos:

```bash
CACHE_NAMESPACE=violeta-staging
CACHE_NAMESPACE=violeta-production
```

Si tu proveedor no exige TLS, puede usar `redis://`, pero `rediss://` es preferible en produccion.

### Background Jobs

```bash
BACKGROUND_JOBS_ENABLED=true
BACKGROUND_JOBS_INLINE=false
BACKGROUND_JOB_WORKERS=2
BACKGROUND_JOB_MAX_RETRIES=2
BACKGROUND_JOB_RETRY_DELAY_SECONDS=0.5
BACKGROUND_JOB_EVENT_RETENTION_DAYS=30
ASYNC_IMAGE_PROCESSING=true
ASYNC_UPLOAD_OPTIMIZATION=true
ASYNC_REVERSE_GEOCODING=true
ASYNC_EMAIL_DELIVERY=true
```

Motivo:

- imagenes, geocoding y emails no deben bloquear requests;
- los errores quedan visibles en `/admin/background-jobs`;
- los reintentos manuales se hacen desde admin.

### Correo

Opcion recomendada en plataformas que bloquean SMTP: Resend.

```bash
MAIL_DELIVERY_METHOD=resend
RESEND_API_KEY=<api-key>
RESEND_FROM=Violeta <no-reply@tu-dominio.com>
RESEND_REPLY_TO=soporte@tu-dominio.com
```

Opcion SMTP:

```bash
MAIL_DELIVERY_METHOD=smtp
MAIL_SERVER=smtp.tu-proveedor.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=<usuario>
MAIL_PASSWORD=<password-o-app-password>
MAIL_DEFAULT_SENDER=no-reply@tu-dominio.com
```

Prueba minimo:

- recuperacion de contraseña;
- email de soporte/admin si aplica;
- revisar background jobs de email.

### Cache HTTP

```bash
STATIC_ASSET_CACHE_SECONDS=604800
PUBLIC_UPLOAD_CACHE_SECONDS=604800
OPTIMIZED_UPLOAD_CACHE_SECONDS=31536000
```

Mantiene assets rapidos sin bloquear cambios de HTML.

## Validacion Local Antes De Deploy

```bash
./.venv/bin/python scripts/ci_checks.py
```

Si tocaste UI, admin, feed, chat, perfil o safety:

```bash
RUN_UI_SMOKE=1 ./.venv/bin/python scripts/ci_checks.py
```

## Validacion En Staging

Con variables de staging activas:

```bash
flask --app app:app preflight-check --strict
curl -fsS https://TU_STAGING/healthz
```

Luego prueba visualmente en telefono y web:

- `/`
- `/admin`
- `/admin/background-jobs`
- `/user/TU_USUARIO`
- `/chat`
- `/safety`

## Promocion A Produccion

1. Confirma CI verde en GitHub.
2. Confirma staging con `preflight-check --strict`.
3. Confirma `/healthz` en staging.
4. Genera backup de base de produccion.
5. Aplica variables de produccion.
6. Despliega.
7. Ejecuta `/healthz`.
8. Revisa `/admin/background-jobs`.
9. Prueba telefono y web.

## Criterio De No-Go

No despliegues si:

- `preflight-check --strict` tiene errores;
- `/healthz` responde degradado;
- `UPLOAD_BACKEND=local` en produccion;
- falta `SECRET_KEY`;
- se usa SQLite en produccion;
- cookies seguras estan apagadas en HTTPS;
- admin movil tiene overflow horizontal;
- emails criticos no se entregan.
