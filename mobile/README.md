# Violeta Mobile

Scaffold base para publicar Violeta en iOS y Android usando Capacitor sobre el backend Flask existente.

## Enfoque

- El backend actual sigue viviendo en Flask.
- La app movil se conecta a una URL publica por medio de `MOBILE_WEB_URL`.
- Si no defines `MOBILE_WEB_URL`, el build usa una pantalla local de bootstrap para no dejar el proyecto roto.

## Requisitos locales

- Node.js 22+
- npm 10+
- Xcode instalado y con licencia aceptada (`sudo xcodebuild -license`)
- Plataforma iOS instalada en Xcode > Settings > Components
- CocoaPods para iOS
- Android Studio para Android
- JDK 11 o superior para que Gradle sincronice Android

## Variables

Crea `mobile/.env` con la URL publica del backend o exporta en terminal:

```bash
export MOBILE_WEB_URL=https://tu-backend-publico.example.com
```

Para preparar envio a tiendas, tambien define:

```bash
export STORE_PRIVACY_POLICY_URL=https://tu-backend-publico.example.com/privacy
export STORE_ACCOUNT_DELETION_URL=https://tu-backend-publico.example.com/account/delete
```

## Comandos utiles

```bash
npm install
npm run doctor
npm run doctor:strict
npm run cap:add:ios
npm run cap:add:android
npm run cap:sync
npm run cap:open:ios
npm run cap:open:android
npm run run:ios
npm run run:android
npm run build:android:debug
npm run build:ios:simulator
```

Capacitor lee `mobile/.env` automaticamente porque `capacitor.config.ts` carga `dotenv/config`.

`doctor:strict` valida `/healthz` con retries porque Render puede tardar en responder cuando el servicio despierta. Si necesitas ajustar esa espera:

```bash
MOBILE_HEALTH_TIMEOUT_MS=30000 MOBILE_HEALTH_RETRIES=4 npm run doctor:strict
```

## Flujo recomendado

1. Despliega Flask en HTTPS.
2. Define `MOBILE_WEB_URL`.
3. Ejecuta `npm run doctor`.
4. Ejecuta `npm run cap:sync`.
5. Abre Xcode con `npm run cap:open:ios`.
6. Abre Android Studio con `npm run cap:open:android`.
7. Corre la checklist de QA movil en `docs/mobile-qa-checklist.md`.
8. Configura iconos, permisos, Push Notifications y App Groups si aplica.
9. Sube el build a TestFlight y crea una prueba interna en Google Play.

## Validacion de builds nativos

Android genera un APK debug con:

```bash
npm run build:android:debug
```

iOS compila el target nativo de simulador con:

```bash
npm run build:ios:simulator
```

Si el build iOS llega a `iOS 26.4 Platform Not Installed` o `No simulator runtime version available`, instala esa plataforma/runtime desde Xcode > Settings > Components. El proyecto ya tiene scheme compartido y paquetes SwiftPM resueltos; ese mensaje viene de la instalacion local de Xcode.

## QA movil

Despues de compilar, usa `docs/mobile-qa-checklist.md` para probar iPhone, Android, permisos nativos, feed, reportes, admin movil y borrado de cuenta antes de preparar TestFlight o Google Play internal testing.

## App Store

Antes de mandar a revision, revisa al menos estos puntos:

- La app debe tener funcionalidad suficiente y no verse como un simple wrapper de sitio.
- Si permites crear cuenta, Apple exige borrado de cuenta dentro de la app.
- Google Play tambien exige mecanismos de borrado de cuenta para apps con cuenta.
- Debes completar App Privacy Details, Data Safety y textos de permisos para camara, fotos, ubicacion y notificaciones.

Referencias oficiales:

- https://capacitorjs.com/docs/getting-started
- https://developer.apple.com/app-store/review/guidelines/
- https://developer.apple.com/support/offering-account-deletion-in-your-app/
- https://developer.apple.com/app-store/app-privacy-details/
