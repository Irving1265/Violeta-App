# Runbook Operativo

Guia practica para validar, desplegar, monitorear y recuperar Violeta sin tocar datos reales innecesariamente.

## Checklist Antes De Deploy

Ejecuta todo desde la raiz del repo:

```bash
./.venv/bin/python scripts/ci_checks.py
```

Debe pasar con:

- Bandit sin hallazgos `Low`, `Medium` ni `High`.
- Smoke tests criticos en verde.
- Preflight no estricto sin errores.

Si el cambio toca UI, responsive, admin, perfil, feed, seguridad o chat, corre tambien:

```bash
RUN_UI_SMOKE=1 ./.venv/bin/python scripts/ci_checks.py
```

Ese smoke revisa telefono y web con navegador real. Si falla por overflow horizontal, selector invisible o flujo roto, corrige antes de subir.

## Preflight De Produccion

Antes de desplegar a produccion:

```bash
flask --app app:app preflight-check --strict
```

El resultado esperado es `status: ok`. Si hay `errors`, no despliegues.

Warnings aceptables temporalmente:

- `local_uploads` solo en desarrollo local. En produccion usa storage persistente.
- `mail_not_configured` solo si todavia no se usan recuperacion de contraseña o emails reales.
- `redis_not_configured` solo si el volumen es bajo y aceptas cache/local workers limitados.

## Variables Criticas

Confirma que produccion tenga configurado:

- `SECRET_KEY` fuerte y distinto al local.
- `DATABASE_URL` apuntando a PostgreSQL administrado.
- `DATABASE_REQUIRE_SSL=true` si el proveedor lo requiere.
- `UPLOAD_BACKEND` segun storage real, no disco efimero si la plataforma lo borra.
- `REDIS_URL` si hay mas de una instancia, workers background o cache compartida.
- `SESSION_COOKIE_SECURE=true` cuando se sirve por HTTPS.
- Configuracion de correo si hay recuperacion de contraseña o mensajes transaccionales.

Nunca pegues valores reales de secretos en issues, logs, screenshots ni commits.

## Deploy

Flujo recomendado:

1. Corre `./.venv/bin/python scripts/ci_checks.py`.
2. Corre `RUN_UI_SMOKE=1 ./.venv/bin/python scripts/ci_checks.py` si cambiaste UI o rutas criticas.
3. Corre `flask --app app:app preflight-check --strict` con variables de produccion disponibles.
4. Haz commit y push.
5. Despliega en la plataforma.
6. Verifica `/healthz`.
7. Entra como admin desde telefono y web para revisar feed, panel admin y diagnostico background.

## Verificacion Despues De Deploy

Health:

```bash
curl -fsS https://TU_DOMINIO/healthz
```

Debe responder JSON con `status: ok`. Si responde `warning`, revisa `failing_checks` y el preflight.

Smoke manual minimo:

- Telefono: abrir feed, filtrar ciudad, abrir filtros avanzados, abrir una publicacion, comentar y navegar al perfil.
- Telefono: abrir panel admin si la cuenta tiene permisos y revisar que no haya overflow horizontal.
- Web: abrir feed, panel admin, reportes, diagnostico background y perfil.
- Seguridad: abrir Centro de seguridad y validar que el boton de emergencia no se active por accidente.
- Chat: abrir lista de chats y confirmar que carga sin errores visuales.

Smoke publico automatizado:

```bash
./.venv/bin/python scripts/production_smoke.py --base-url https://violeta-app.onrender.com
```

Este smoke confirma que produccion expone health, privacidad, borrado de cuenta, aviso beta, soporte y terminos.

## Lanzamiento Beta v1.0

Antes de abrir Violeta a publico:

- confirma que el banner `Beta v1.0` aparece en la app;
- confirma que `/beta`, `/support`, `/terms`, `/privacy` y `/account/delete` abren sin iniciar sesion;
- ejecuta `scripts/production_smoke.py` contra produccion;
- genera backup de PostgreSQL y confirma acceso al storage de Supabase;
- entra con una cuenta admin y una cuenta no admin desde telefono real;
- prueba registro, login, feed, mapa, camara, publicar reporte, verificacion y borrado de cuenta.

Durante las primeras 24 horas:

- revisa `/healthz` cada 2-3 horas;
- revisa logs de Render;
- revisa `/admin/background-jobs`;
- revisa reportes de alto riesgo y verificaciones pendientes;
- atiende mensajes recibidos en soporte.

## Monitoreo Diario

Revisar al inicio del dia:

- `/healthz`.
- Panel admin.
- Diagnostico background en `/admin/background-jobs`.
- Reportes pendientes y reportes de alto riesgo.
- Usuarios con strikes recientes.
- Errores del proveedor de deploy.

En diagnostico background revisa:

- Fallas en `upload_image_processing`.
- Fallas en `upload_optimized_variant_on_demand`.
- Fallas en `upload_optimized_variants`.
- Fallas en `reverse_geocode_post`.
- Cola o reintentos acumulados.

Si hay tareas recuperables, usa los botones de mantenimiento manual desde el panel antes de entrar a consola.

## Respuesta A Incidentes

### Feed No Carga

1. Verifica `/healthz`.
2. Revisa logs de la ruta `/` y `/feed`.
3. Revisa DB y Redis en health/preflight.
4. Desactiva temporalmente filtros o cache solo si los logs apuntan ahi.
5. Si afecta a usuarias, haz rollback.

### Imagenes No Aparecen

1. Revisa `UPLOAD_BACKEND` y storage.
2. Abre `/admin/background-jobs`.
3. Reintenta procesamiento de imagenes desde mantenimiento manual.
4. Revisa URLs `/uploads/optimized/...`.
5. Si solo falla WebP/thumbnail, la imagen original debe seguir funcionando como fallback.

### Geocoding No Completa

1. Revisa fallas `reverse_geocode_post`.
2. Usa mantenimiento manual para completar geocoding pendiente.
3. Confirma que el feed siga mostrando ubicacion aproximada o fallback seguro.

### Emails No Salen

1. Revisa preflight por `mail_not_configured`.
2. Verifica proveedor SMTP/Resend.
3. Revisa logs de background jobs relacionados a email.
4. No reintentes masivamente sin confirmar que el proveedor ya responde.

### Admin Lento O Roto En Telefono

1. Ejecuta `RUN_UI_SMOKE=1 ./.venv/bin/python scripts/ci_checks.py`.
2. Reproduce en viewport movil.
3. Revisa overflow horizontal, tablas sin scroll y botones fuera de pantalla.
4. Prioriza layouts de una columna, cards y acciones circulares para telefono.

## Rollback

Si el deploy rompe rutas criticas:

1. Marca el incidente y evita nuevos cambios manuales en produccion.
2. Revisa el commit anterior estable.
3. Haz rollback desde la plataforma o redeploy del commit anterior.
4. Verifica `/healthz`.
5. Revisa feed, login, admin y chat en telefono.
6. Documenta causa raiz antes de volver a desplegar.

No hagas cambios directos sobre la base real salvo que sea necesario para recuperar servicio. Si necesitas tocar datos, exporta backup primero.

## Backups Y Datos

Antes de migraciones o cambios de esquema:

- Genera backup de PostgreSQL desde el proveedor.
- Exporta una muestra de datos criticos si el proveedor lo permite.
- Corre migracion en staging o base temporal.
- Verifica login, feed, crear publicacion, comentarios, reportes y admin.

Nunca uses la base real para pruebas destructivas.

Antes de un anuncio publico:

- genera snapshot/backup desde el proveedor de PostgreSQL;
- confirma que puedes restaurar o descargar el backup;
- confirma que Supabase Storage usa bucket de produccion y no storage local;
- guarda el commit desplegado y la hora del deploy;
- evita cambios manuales en base real durante el lanzamiento salvo incidente.

## Criterio Para Cerrar Un Cambio

Un cambio puede cerrarse cuando:

- `./.venv/bin/python scripts/ci_checks.py` pasa.
- `RUN_UI_SMOKE=1 ./.venv/bin/python scripts/ci_checks.py` pasa si hubo UI/rutas criticas.
- `git diff --check` no reporta whitespace.
- La pantalla afectada fue revisada en telefono y web.
- El cambio no introduce secretos, datos reales ni logs sensibles.
