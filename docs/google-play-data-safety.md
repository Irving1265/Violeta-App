# Google Play Data Safety - Violeta

Este documento resume las respuestas base para Data Safety en Play Console. Debe mantenerse alineado con la politica de privacidad y con el comportamiento real de la app.

## Account deletion

Violeta ofrece borrado de cuenta dentro de la app y por web.

- Web deletion URL: https://violeta-app.onrender.com/account/delete
- Privacy Policy: https://violeta-app.onrender.com/privacy

La ruta web debe cargar sin pedir reinstalar la app y debe mencionar Violeta de forma clara.

## Data collection

### Personal info

Collected:

- Email address.
- Username.
- Phone number si la usuaria lo agrega para verificacion o seguridad.

Purpose:

- Account management.
- App functionality.
- Security, fraud prevention and compliance.

Shared:

- No, salvo proveedores tecnicos necesarios para operar el servicio.

### Photos and videos

Collected:

- Imagenes de reportes.
- Avatar de perfil.
- Evidencia de verificacion si la funcion esta activa.

Purpose:

- App functionality.
- Safety and moderation.

Shared:

- No para publicidad.

### Location

Collected:

- Precise location para reportes, reportes cercanos, rutas seguras y emergencia.
- Approximate location para contexto de zona.

Purpose:

- App functionality.
- Safety.

Shared:

- No para publicidad.

### App activity

Collected:

- Publicaciones, comentarios, likes, reportes, chat y acciones de moderacion.

Purpose:

- App functionality.
- Security, fraud prevention and compliance.

Shared:

- No para publicidad.

### Contacts

Collected:

- Contactos de seguridad agregados por la usuaria.

Purpose:

- App functionality.
- Safety.

Shared:

- No para publicidad.

### Diagnostics

Collected:

- Logs operativos, health checks, eventos background y auditoria administrativa.

Purpose:

- App functionality.
- Security, fraud prevention and compliance.

Shared:

- No para publicidad.

## Security practices

- Data is encrypted in transit over HTTPS.
- Account deletion is available.
- Data retention and moderation/audit policies are documented in `docs/data-governance.md`.

## Sensitive permissions

Violeta usa camera, location, notifications and microphone only for app functionality and safety features. It does not request SMS or Call Log permissions.

