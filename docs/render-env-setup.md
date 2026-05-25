# Configuración de Render para producción

Esta guía cierra los warnings `local_uploads` y `mail_not_configured` del preflight.

## Variables mínimas

En Render entra a `Dashboard > Web Service > Environment` y configura:

```bash
APP_ENV=production
PREFERRED_URL_SCHEME=https
HOST=0.0.0.0
PUBLIC_BETA_VERSION=Beta v1.0
SUPPORT_EMAIL=violetaapp38@gmail.com
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
DATABASE_REQUIRE_SSL=true
DATABASE_SSLMODE=require
BACKGROUND_JOBS_ENABLED=true
BACKGROUND_JOBS_INLINE=false
ASYNC_IMAGE_PROCESSING=true
ASYNC_UPLOAD_OPTIMIZATION=true
ASYNC_REVERSE_GEOCODING=true
ASYNC_EMAIL_DELIVERY=true
UPLOAD_BACKEND=supabase
SUPABASE_URL=https://TU_PROYECTO.supabase.co
SUPABASE_SERVICE_ROLE_KEY=TU_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET=uploads
MAIL_DELIVERY_METHOD=resend
RESEND_API_KEY=TU_RESEND_API_KEY
RESEND_FROM=Violeta <no-reply@tu-dominio.com>
RESEND_REPLY_TO=violetaapp38@gmail.com
```

Render normalmente ya define `DATABASE_URL` si conectaste PostgreSQL al servicio. Si no aparece,
copia la URL interna o externa de la base administrada.

Genera `SECRET_KEY` una sola vez y guárdala en Render:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Supabase Storage

1. En Supabase crea o abre el proyecto de Violeta.
2. Ve a `Storage`.
3. Crea el bucket `uploads`.
4. El bucket debe ser público para que las imágenes del feed y avatares se puedan servir por URL pública.
5. Copia `Project URL` a `SUPABASE_URL`.
6. Copia `service_role key` a `SUPABASE_SERVICE_ROLE_KEY`.
7. En Render configura `UPLOAD_BACKEND=supabase`.

Si ya existen archivos locales que necesitas migrar:

```bash
set -a
source .env
set +a
python scripts/sync_public_uploads_to_supabase_storage.py
```

No subas `SUPABASE_SERVICE_ROLE_KEY` a GitHub.

## Correo

Opción recomendada en Render: Resend por HTTPS.

1. Crea API key en Resend.
2. Si tienes dominio, verifica el dominio y usa `no-reply@tu-dominio.com`.
3. Si todavía no tienes dominio verificado, usa temporalmente el remitente permitido por Resend para pruebas.
4. Configura en Render:

```bash
MAIL_DELIVERY_METHOD=resend
RESEND_API_KEY=TU_RESEND_API_KEY
RESEND_FROM=Violeta <no-reply@tu-dominio.com>
RESEND_REPLY_TO=violetaapp38@gmail.com
```

## Validación local sin imprimir secretos

Puedes auditar un archivo `.env.production` local:

```bash
python scripts/production_env_audit.py --env-file .env.production
```

O auditar variables cargadas en terminal:

```bash
set -a
source .env.production
set +a
python scripts/production_env_audit.py
```

El auditor redacta secretos y falla si detecta placeholders como `TU_PROYECTO`,
`TU_SERVICE_ROLE_KEY`, `TU_RESEND_API_KEY` o `tu-dominio.com`. Si `status` es `ok`,
la configuración básica está completa.

## Validación con Flask

Después de configurar variables reales:

```bash
flask --app app:app preflight-check --strict
```

En producción debe quedar sin errores. Warnings aceptables dependen del caso, pero no lances si hay:

- `local_uploads_in_strict_mode`
- `missing_supabase_storage`
- `mail_not_configured`
- `missing_resend_config`
- `missing_smtp_password`
- `sqlite_in_strict_mode`

## Deploy

1. Guarda variables en Render.
2. Ejecuta `Manual Deploy > Deploy latest commit`.
3. Revisa `/healthz`; en producción debe mostrar `uploads.backend=supabase` y `mail.backend=resend` o `mail.backend=smtp` con `status=ok`.
4. Revisa logs de Render al crear publicación, subir avatar y recuperar contraseña.
5. Corre el flujo real en teléfono: login, feed, crear publicación, comentar, reportar, chat y borrar cuenta.
