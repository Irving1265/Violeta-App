# Publicacion movil de Violeta

## Estado actual

- Backend Flask listo para PostgreSQL.
- Falta desplegar backend publico con HTTPS.
- El scaffold movil vive en `/mobile`.

## Ruta de salida a App Store

1. Subir backend Flask a un dominio publico con HTTPS.
2. Configurar storage de archivos fuera del disco local.
3. Definir `MOBILE_WEB_URL`.
4. Generar proyecto iOS con Capacitor.
5. Configurar permisos:
   - Camara
   - Fotos
   - Ubicacion
   - Notificaciones
6. Preparar flujo de borrado de cuenta dentro de la app.
7. Crear registro en App Store Connect.
8. Probar en TestFlight.
9. Ajustar requisitos de App Review.
10. Ajustar Java/Xcode locales si quieres compilar en tu Mac.

## Referencias oficiales

- Capacitor Getting Started: https://capacitorjs.com/docs/getting-started
- Apple App Review Guidelines: https://developer.apple.com/app-store/review/guidelines/
- Account deletion: https://developer.apple.com/support/offering-account-deletion-in-your-app/
- App Privacy Details: https://developer.apple.com/app-store/app-privacy-details/
- Add a new app record: https://developer.apple.com/help/app-store-connect/create-an-app-record/add-a-new-app
