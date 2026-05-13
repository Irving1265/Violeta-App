# Publicacion movil de Violeta

## Estado actual

- Backend Flask listo para PostgreSQL.
- Backend publico en Render y base de datos administrada ya contemplados en `docs/production-staging.md`.
- El scaffold movil vive en `/mobile`.
- Ya existen proyectos nativos de Capacitor en `/mobile/ios` y `/mobile/android`.
- El build movil aun debe apuntar a tu URL real de Render por medio de `MOBILE_WEB_URL`.

## Siguiente paso real

1. Configurar `mobile/.env` con la URL HTTPS de Render.
2. Ejecutar `npm run doctor` dentro de `/mobile`.
3. Ejecutar `npm run cap:sync` para que iOS y Android carguen el backend real.
4. Abrir iOS y Android:

```bash
cd mobile
npm run cap:open:ios
npm run cap:open:android
```

5. Probar login, feed, crear publicacion, ubicacion, camara, chat, reportes y logout en telefono real o simulador.

## Variables para release movil

```bash
MOBILE_WEB_URL=https://tu-app-en-render.onrender.com
STORE_PRIVACY_POLICY_URL=https://tu-dominio.com/privacy
STORE_ACCOUNT_DELETION_URL=https://tu-dominio.com/account/delete
```

Antes de enviar a tiendas:

```bash
cd mobile
npm run doctor:strict
```

## Ruta de salida a App Store y Google Play

1. Backend en HTTPS con `/healthz` sano.
2. Storage persistente fuera del disco local.
3. `MOBILE_WEB_URL` configurado y sincronizado con `npm run cap:sync`.
4. Flujo de borrado de cuenta disponible dentro de la app y desde una URL publica.
5. Politica de privacidad publica y alineada con los datos reales que usa Violeta.
6. Iconos, splash, nombre, descripcion y screenshots reales para iPhone y Android.
7. App Privacy Details en App Store Connect.
8. Data Safety en Google Play Console.
9. TestFlight para iOS.
10. Internal testing en Google Play.
11. Correccion de rechazos de revision antes de lanzar produccion.

## Riesgos de revision

- Una app que solo carga una web puede ser rechazada si no aporta experiencia movil suficiente. Violeta debe apoyarse en capacidades nativas reales: camara, ubicacion, notificaciones, seguridad y flujo de emergencia.
- Como hay cuentas de usuaria, las tiendas esperan borrado de cuenta y datos. Esto debe estar visible dentro de la app.
- Camara, ubicacion, fotos y notificaciones deben tener textos de permiso claros y coincidir con la politica de privacidad.
- La app debe funcionar bien en telefono con red lenta; no basta con que la web funcione en desktop.

## Referencias oficiales

- Capacitor Getting Started: https://capacitorjs.com/docs/getting-started
- Apple App Review Guidelines: https://developer.apple.com/app-store/review/guidelines/
- Account deletion: https://developer.apple.com/support/offering-account-deletion-in-your-app/
- App Privacy Details: https://developer.apple.com/app-store/app-privacy-details/
- Add a new app record: https://developer.apple.com/help/app-store-connect/create-an-app-record/add-a-new-app
- Google Play App Bundles: https://developer.android.com/guide/app-bundle
- Google Play App Signing: https://support.google.com/googleplay/android-developer/answer/9842756
- Google Play Data Safety: https://support.google.com/googleplay/android-developer/answer/10787469
- Google Play account deletion: https://support.google.com/googleplay/android-developer/answer/13327111
