# App Store Privacy Answers - Violeta

Este documento resume las respuestas base para App Privacy Details en App Store Connect. Debe actualizarse si se agregan analytics, ads, crash reporting externo, SDKs nuevos o integraciones de terceros.

## Tracking

No tracking.

Violeta no debe declarar tracking mientras no use publicidad, data brokers, SDKs de atribucion publicitaria ni cruce datos con terceros para publicidad o medicion publicitaria.

## Data linked to the user

Declara estos datos como linked to the user porque se asocian con cuenta, perfil, contenido o acciones de una usuaria.

### Contact Info

- Email address.
- Phone number si se usa verificacion o contacto de seguridad.

Purpose:

- App Functionality.
- Account Management.
- Fraud Prevention, Security and Compliance.

### User Content

- Photos or videos enviados como evidencia.
- Publicaciones, categorias, comentarios, chat y reportes.
- Perfil, avatar y bio.

Purpose:

- App Functionality.
- Product Personalization.
- Fraud Prevention, Security and Compliance.

### Location

- Precise location cuando se crea reporte, se usa "Por mi zona", rutas seguras o emergencia.
- Coarse location cuando se muestra contexto cercano o zonas.

Purpose:

- App Functionality.
- Safety and Security.

### Contacts

- Contactos de seguridad que la usuaria decide agregar.

Purpose:

- App Functionality.
- Safety and Security.

### Identifiers

- User ID interno.
- Session/account identifiers.

Purpose:

- App Functionality.
- Fraud Prevention, Security and Compliance.

### Diagnostics

- Operational logs, moderation/audit events and background job diagnostics.

Purpose:

- App Functionality.
- Fraud Prevention, Security and Compliance.

## Data not used for tracking

Los datos anteriores no deben usarse para tracking publicitario. Si se agrega un SDK de analytics, crash reporting o push provider con coleccion propia, se debe revisar su privacy manifest y actualizar esta tabla.

## Privacy links

- Privacy Policy: https://violeta-app.onrender.com/privacy
- Privacy Choices / Account Deletion: https://violeta-app.onrender.com/account/delete
- Terms of Use: https://violeta-app.onrender.com/terms
- Beta Notice / Support: https://violeta-app.onrender.com/beta y https://violeta-app.onrender.com/support

## Beta v1.0 notes

La app puede describirse como Beta v1.0 mientras este abierta a usuarias reales y todavia se ajusten funciones. La metadata no debe prometer seguridad garantizada, respuesta oficial de emergencias ni verificacion infalible.

La evidencia visual de verificacion debe explicarse como revision humana autorizada para reducir riesgo comunitario, no como reconocimiento facial automatico ni clasificacion de genero.

## Review notes

Apple exige politica de privacidad dentro de la app y en metadata. Si la app permite crear cuenta, tambien exige borrado de cuenta dentro de la app.

Para revision, prepara una cuenta demo verificada y no la guardes en GitHub.
