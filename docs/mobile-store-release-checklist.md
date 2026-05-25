# Checklist de publicacion en App Store y Google Play

Usa esta checklist cuando `npm run doctor` no tenga errores y antes de crear builds para revision.

## 1. Identidad de la app

- Nombre visible: `Violeta`.
- Bundle ID iOS: `com.violeta.app`.
- Application ID Android: `com.violeta.app`.
- Icono iOS: 1024x1024 sin transparencia problematica.
- Iconos Android: launcher y round launcher generados para todas las densidades.
- Splash: fondo morado oscuro y asset consistente con la marca.
- Version inicial: `1.0`.
- Build number inicial: `1`.

## 2. Backend y legal

- `MOBILE_WEB_URL=https://violeta-app.onrender.com`.
- `/healthz` responde sano antes de compilar.
- `/privacy` abre publicamente y explica datos reales de Violeta.
- `/account/delete` abre publicamente y permite iniciar o explicar claramente el borrado de cuenta.
- `/beta` abre publicamente y explica que Violeta esta en Beta v1.0.
- `/support` abre publicamente para reportar problemas de la beta.
- `/terms` abre publicamente con condiciones de uso.
- El borrado de cuenta tambien esta accesible dentro de la app.
- No hay secretos en `mobile/.env`, screenshots, commits ni documentos.

## 3. Permisos

- Camara: evidencia de reportes.
- Microfono: no requerido para el flujo actual.
- Fotos: adjuntar imagenes a reportes y perfil.
- Ubicacion: reportes cercanos, rutas seguras y emergencia.
- Notificaciones: mensajes y seguimiento de reportes solo cuando la funcionalidad este habilitada.
- Si una usuaria niega un permiso, la app debe explicar como continuar o reintentar.

## 4. Privacidad en tiendas

- App Store Connect: completa App Privacy Details con cuenta, contenido de usuaria, ubicacion, contactos de seguridad y diagnostico operativo.
- Play Console: completa Data Safety y responde las preguntas de borrado de cuenta.
- Declara que no hay tracking si no se agregan ads, data brokers ni SDKs de tracking.
- Mantén App Privacy y Data Safety actualizados si agregas analytics, ads, crash reporting o nuevos SDKs.
- Incluye el disclaimer: Violeta no esta afiliada a autoridades ni servicios de emergencia y no reemplaza reportes oficiales.

## 5. Signing

- Android: `mobile/android/keystore.properties` existe localmente o se usan `ANDROID_KEYSTORE_*`.
- Android: `npm run build:android:release` genera `app-release.aab`.
- Google Play: Play App Signing habilitado antes de subir el primer release.
- iOS: Team ID configurado en Xcode.
- iOS: `Product > Archive` genera archive sin errores.
- TestFlight: subir primero a beta interna antes de revision publica.

## 6. QA obligatoria en telefono

- Login correcto e incorrecto.
- Feed sin overflow horizontal en iPhone y Android.
- Crear publicacion con foto, categoria y ubicacion.
- Comentarios, likes, reportar publicacion y reportar comentario.
- Chat con teclado abierto y cerrado.
- Perfil, editar perfil, centro de seguridad y logout.
- Admin movil si la cuenta tiene rol admin.
- Borrado de cuenta.
- Red lenta o cold start de Render.

## 7. Evidencia para revision

- Capturas iPhone: login, feed, crear reporte, permisos, seguridad, perfil y borrado de cuenta.
- Capturas Android: mismas pantallas.
- Cuenta demo verificada para Apple Review.
- Notas de revision explicando que Violeta usa camara, ubicacion y reportes comunitarios para seguridad contextual.
- Notas de revision explicando que la app usa Capacitor, capacidades moviles reales y backend en Render.
- Credenciales demo agregadas solo en App Store Connect o Play Console, nunca en GitHub.
- Release notes cortas y no promocionales.
- Textos de tienda validados con `cd mobile && npm run store:check`.

## 8. Orden recomendado

1. `cd mobile`
2. `npm run doctor`
3. `npm run store:check`
4. `npm run cap:sync`
5. `npm run build:android:debug`
6. `npm run build:ios:simulator`
7. QA con `docs/mobile-qa-checklist.md`
8. Preparar screenshots con `docs/mobile-screenshot-plan.md`
9. Configurar signing real.
10. `npm run doctor:strict`
11. `npm run build:android:release`
12. Archive en Xcode y TestFlight.
13. Prueba interna en Google Play.
14. Corregir rechazos antes de publicar.
