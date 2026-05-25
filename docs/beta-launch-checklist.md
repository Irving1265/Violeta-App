# Checklist De Lanzamiento Beta v1.0

Usa esta lista antes y despues de abrir Violeta al publico. La meta es lanzar con riesgos controlados, no congelar el producto.

## Estado Publico

- Nombre recomendado: `Violeta Beta v1.0`.
- Mensaje publico: Violeta esta en beta publica; la app ya puede usarse, pero seguiremos mejorando funciones, seguridad y rendimiento.
- Ruta informativa: `/beta`.
- Soporte publico: `/support`.
- Terminos de uso: `/terms`.

## Smoke De Produccion

Antes de anunciar el lanzamiento:

```bash
./.venv/bin/python scripts/production_smoke.py --base-url https://violeta-app.onrender.com
```

Debe validar:

- `/healthz` con `status: ok`;
- `/privacy`;
- `/account/delete`;
- `/beta`;
- `/support`;
- `/terms`.

Despues revisa manualmente en telefono real:

- registro;
- login/logout;
- feed y scroll;
- crear reporte con camara;
- mapa y ubicacion;
- solicitud de verificacion;
- borrar cuenta;
- soporte y aviso beta.

## Monitoreo Del Primer Dia

Durante las primeras 24 horas revisa cada 2-3 horas:

- Render logs del Web Service;
- `/healthz`;
- panel admin;
- `/admin/background-jobs`;
- errores de uploads en Supabase;
- reportes de alto riesgo;
- solicitudes de verificacion pendientes;
- correos o mensajes enviados a soporte.

## Backup Antes Del Anuncio

Antes de invitar usuarias reales:

- genera backup/snapshot de PostgreSQL desde el proveedor;
- confirma que Supabase Storage tiene bucket correcto y archivos accesibles;
- confirma que tienes acceso admin/super admin;
- guarda el commit estable que se desplego;
- no ejecutes migraciones manuales sin backup.

## Mensaje Sugerido Para Usuarias

> Violeta esta en Beta v1.0. Ya puedes usar la app, pero seguiremos ajustando funciones, seguridad y rendimiento. Si encuentras un problema, reportalo desde Soporte.

## Criterio Para Pausar El Lanzamiento

Pausa o retrasa si ocurre cualquiera de estos puntos:

- `/healthz` no responde `ok`;
- login o registro falla;
- crear reporte falla en telefono real;
- uploads no llegan a Supabase;
- el feed queda en loading infinito;
- no puedes entrar al panel admin;
- no existe backup reciente.
