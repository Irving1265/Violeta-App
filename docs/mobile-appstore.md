# Publicacion movil de Violeta

## Estado actual

- Backend Flask listo para PostgreSQL.
- Backend publico en Render y base de datos administrada ya contemplados en `docs/production-staging.md`.
- El scaffold movil vive en `/mobile`.
- Ya existen proyectos nativos de Capacitor en `/mobile/ios` y `/mobile/android`.
- El build movil apunta a Render por medio de `MOBILE_WEB_URL=https://violeta-app.onrender.com`.
- La politica de privacidad publica existe en `/privacy`.
- La ruta publica de borrado de cuenta existe en `/account/delete`.
- Hay icono iOS 1024x1024, splash iOS 2732x2732, iconos Android por densidad y splash Android.
- Falta configurar signing real: Apple Developer Team ID y upload key de Android.

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

5. Probar login, feed, crear publicacion, ubicacion, camara, chat, reportes y logout en telefono real o simulador usando `docs/mobile-qa-checklist.md`.

## Variables para release movil

```bash
MOBILE_WEB_URL=https://violeta-app.onrender.com
STORE_PRIVACY_POLICY_URL=https://violeta-app.onrender.com/privacy
STORE_ACCOUNT_DELETION_URL=https://violeta-app.onrender.com/account/delete
```

Antes de enviar a tiendas:

```bash
cd mobile
npm run doctor:strict
```

## Validacion nativa

Android:

```bash
cd mobile
npm run build:android:debug
```

El APK debug queda en `mobile/android/app/build/outputs/apk/debug/app-debug.apk`.

iOS:

```bash
cd mobile
npm run build:ios:simulator
```

Si Xcode responde `iOS 26.4 Platform Not Installed` o `No simulator runtime version available`, instala la plataforma/runtime faltante desde Xcode > Settings > Components y vuelve a ejecutar el comando. Ese error es del entorno local de Xcode, no del codigo de Violeta.

## Signing para Google Play

1. Genera una upload key local fuera del repo o dentro de `mobile/android` ignorada por git:

```bash
cd mobile/android
keytool -genkeypair -v \
  -keystore release-upload-key.jks \
  -alias violeta-upload \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000
```

2. Copia la plantilla:

```bash
cp keystore.properties.example keystore.properties
```

3. Llena `keystore.properties` con tus passwords reales.
4. Genera el AAB:

```bash
cd ..
npm run build:android:release
```

5. Sube `mobile/android/app/build/outputs/bundle/release/app-release.aab` a Play Console.

Tambien puedes usar variables `ANDROID_KEYSTORE_PATH`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` y `ANDROID_KEY_PASSWORD`.

## Signing para App Store / TestFlight

1. Enrollate en Apple Developer Program si no lo has hecho.
2. Abre Xcode:

```bash
cd mobile
npm run cap:open:ios
```

3. En target `App`, configura Team, bundle id `com.violeta.app`, version y build number.
4. Usa `Product > Archive`.
5. Sube el archive a App Store Connect y distribuye primero por TestFlight.

`npm run doctor:strict` marca error si no detecta Team ID porque sin eso no puedes subir a TestFlight.

## Metadata inicial recomendada

- Nombre: Violeta
- Subtitulo iOS: Seguridad comunitaria para mujeres
- Short description Android: Reporta zonas inseguras y acompana rutas con herramientas de seguridad.
- Categoria iOS sugerida: Social Networking o Lifestyle, segun posicionamiento final.
- Categoria Android sugerida: Social o Lifestyle.
- Edad: revisar con las respuestas de contenido sensible, ubicacion y comunidad generada por usuarias.
- Demo account: prepara una cuenta verificada para revision de Apple si la app requiere login.

Los textos iniciales viven en:

- `mobile/store/app-store/`
- `mobile/store/google-play/`

Valida esos textos con:

```bash
cd mobile
npm run store:check
```

## Privacidad y datos para tiendas

Declara datos segun el uso real de Violeta:

- Cuenta: username, email, password hash, estado de verificacion.
- Contenido de usuaria: publicaciones, fotos, categorias, comentarios, chat y reportes.
- Ubicacion: coordenadas de reportes, reportes cercanos, rutas seguras y emergencia.
- Contactos de seguridad: solo si la usuaria los agrega.
- Identificadores operativos: logs de auditoria, moderacion, strikes y diagnostico.
- No declares tracking si no agregas ads, SDKs de tracking o data brokers.

La politica de privacidad debe permanecer accesible dentro de la app y en la ficha de tienda. Google tambien exige una URL web funcional para borrado de cuenta aunque exista borrado dentro de la app.

Documentos base para llenar formularios:

- `docs/app-store-privacy-answers.md`
- `docs/google-play-data-safety.md`
- `docs/mobile-screenshot-plan.md`

## Ruta de salida a App Store y Google Play

1. Backend en HTTPS con `/healthz` sano.
2. Storage persistente fuera del disco local.
3. `MOBILE_WEB_URL` configurado y sincronizado con `npm run cap:sync`.
4. Flujo de borrado de cuenta disponible dentro de la app y desde una URL publica.
5. Politica de privacidad publica y alineada con los datos reales que usa Violeta.
6. QA movil completa en iPhone y Android con `docs/mobile-qa-checklist.md`.
7. Iconos, splash, nombre, descripcion y screenshots reales para iPhone y Android.
8. App Privacy Details en App Store Connect.
9. Data Safety en Google Play Console.
10. TestFlight para iOS.
11. Internal testing en Google Play.
12. Correccion de rechazos de revision antes de lanzar produccion.

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
