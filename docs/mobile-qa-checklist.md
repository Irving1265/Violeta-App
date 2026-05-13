# QA movil antes de tiendas

Usa esta lista despues de que `npm run build:ios:simulator` y `npm run build:android:debug` compilen correctamente.

## Preparacion

```bash
cd mobile
npm run doctor:strict
npm run cap:sync
```

Si Render esta despertando y `/healthz` tarda demasiado:

```bash
MOBILE_HEALTH_TIMEOUT_MS=30000 MOBILE_HEALTH_RETRIES=4 npm run doctor:strict
```

Para abrir en herramientas nativas:

```bash
npm run cap:open:ios
npm run cap:open:android
```

Para instalar y lanzar desde terminal:

```bash
npm run run:ios
npm run run:android
```

Si `run:ios` o `run:android` no encuentra dispositivo, abre Xcode o Android Studio, selecciona un simulador/emulador y vuelve a ejecutar.

## Matriz minima

- iPhone pequeno: SE o pantalla compacta.
- iPhone grande: Pro Max o similar.
- Android pequeno: 360px de ancho o similar.
- Android grande: Pixel grande o similar.
- Telefono real al menos una vez antes de enviar a revision.

## Flujos criticos

- Abrir app desde cero y confirmar que carga `https://violeta-app.onrender.com/`.
- Login correcto, login incorrecto y logout.
- Feed: carga inicial, scroll, likes, comentarios y abrir/cerrar mapa.
- Crear publicacion con imagen, descripcion, categoria y ubicacion.
- Permiso de ubicacion: aceptar, rechazar y volver a intentar.
- Permiso de camara/fotos: aceptar, rechazar y volver a intentar.
- Filtros: categorias, "Por mi zona" y "Reportados hoy".
- Reportar publicacion y reportar comentario.
- Perfil: editar perfil, bio de maximo 50 caracteres y centro de seguridad.
- Borrado de cuenta: la pantalla debe estar accesible desde la app.
- Admin movil: dashboard usable en telefono, acciones principales visibles y sin overflow horizontal.

## Criterios visuales

- No debe haber scroll horizontal en telefono.
- La barra inferior no debe tapar botones importantes.
- Modales de reportes deben caber en pantalla y poder cerrarse.
- Formularios deben mantener el boton principal visible o alcanzable con scroll.
- Los botones tactiles deben ser faciles de tocar con el pulgar.
- La app debe seguir usable con zoom de accesibilidad/tamano de texto alto.

## Rendimiento y red

- Cold start de Render: si tarda, la app debe mostrar carga sin romperse.
- Red lenta: feed y formularios no deben duplicar acciones por taps repetidos.
- Sin conexion: debe mostrarse error entendible o permitir reintentar.
- Imagenes: feed debe usar recursos optimizados cuando existan.

## Evidencia para tiendas

- Capturas de login, feed, crear reporte, perfil, seguridad y borrado de cuenta.
- Capturas en iPhone y Android.
- Notas de permisos: camara, fotos, ubicacion y notificaciones.
- Confirmacion de que `/privacy` y `/account/delete` son publicas.
- Confirmacion de que `/healthz` responde sano antes de generar builds.

## Bloqueantes

- Crash al abrir.
- Login no funciona.
- Crear publicacion no funciona.
- Permisos nativos sin texto claro.
- No existe borrado de cuenta desde la app.
- Dashboard admin inutilizable en telefono.
- Cualquier pantalla critica con overflow horizontal.
