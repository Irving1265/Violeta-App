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
- CocoaPods para iOS
- Android Studio para Android
- JDK 11 o superior para que Gradle sincronice Android

## Variables

Crea `mobile/.env` con la URL publica del backend o exporta en terminal:

```bash
export MOBILE_WEB_URL=https://tu-backend-publico.example.com
```

## Comandos utiles

```bash
npm install
npm run doctor
npm run cap:add:ios
npm run cap:add:android
npm run cap:sync
npm run cap:open:ios
npm run cap:open:android
```

Capacitor lee `mobile/.env` automaticamente porque `capacitor.config.ts` carga `dotenv/config`.

## Flujo recomendado

1. Despliega Flask en HTTPS.
2. Define `MOBILE_WEB_URL`.
3. Ejecuta `npm run cap:add:ios`.
4. Abre Xcode con `npm run cap:open:ios`.
5. Configura iconos, permisos, Push Notifications y App Groups si aplica.
6. Sube el build a TestFlight.

## App Store

Antes de mandar a revision, revisa al menos estos puntos:

- La app debe tener funcionalidad suficiente y no verse como un simple wrapper de sitio.
- Si permites crear cuenta, Apple exige borrado de cuenta dentro de la app.
- Debes completar App Privacy Details y textos de permisos para camara, fotos, ubicacion y notificaciones.

Referencias oficiales:

- https://capacitorjs.com/docs/getting-started
- https://developer.apple.com/app-store/review/guidelines/
- https://developer.apple.com/support/offering-account-deletion-in-your-app/
- https://developer.apple.com/app-store/app-privacy-details/
