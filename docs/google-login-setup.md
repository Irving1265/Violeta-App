# Activar inicio de sesion con Google

## Credenciales

En Google Cloud / Google Auth Platform configura el nombre Violeta, correo de soporte,
pantalla de consentimiento y un cliente OAuth de tipo **Aplicacion web**.
Solicita solamente `openid email profile`. Durante pruebas agrega las cuentas de prueba;
antes del lanzamiento revisa el estado de publicacion y los requisitos de Google.

Registra exactamente estas URI de redireccion (no origenes JavaScript):

- Produccion: `https://violeta-app.onrender.com/auth/google/callback`
- Local, si usas puerto 5000: `http://localhost:5000/auth/google/callback`
- Si usas otro puerto, registralo explicitamente y usa esa misma direccion al navegar.

En Render configura estas variables; localmente usa `.env` (no lo subas a Git):

```dotenv
GOOGLE_CLIENT_ID=tu-cliente.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=tu-secreto
GOOGLE_REDIRECT_URI=https://violeta-app.onrender.com/auth/google/callback
```

Para local, cambia `GOOGLE_REDIRECT_URI` por la direccion local registrada y usa
`APP_ENV=development`. En produccion manten `SECRET_KEY` estable,
`SESSION_COOKIE_SECURE=true` y `REMEMBER_COOKIE_SECURE=true`. Nunca compartas el
secreto en el chat ni lo incluyas en plantillas o JavaScript.

## Instalacion y esquema

Instala `requirements.txt` con `.venv/bin/python -m pip install -r requirements.txt`.
La sincronizacion existente (`RUN_STARTUP_SCHEMA_SYNC=true`) crea la tabla nueva
`google_identity` sin modificar cuentas existentes. Si esta desactivada, crea la
tabla mediante el proceso de migracion del despliegue antes de habilitar Google:

```sh
./.venv/bin/python -m flask --app app shell
```

Dentro de esa consola:

```python
from models import db, GoogleIdentity
GoogleIdentity.__table__.create(db.engine, checkfirst=True)
```

Reinicia la aplicacion despues de configurar las variables. El boton solo se activa
cuando estan las tres variables y la URI es valida; no se necesita una clave Google Maps.

## Comportamiento y comprobaciones

- Una cuenta nueva confirma la misma declaracion obligatoria del registro y recibe un nombre `usuaria_...`, editable con las herramientas existentes,
  y queda **sin verificar**, sin roles ni acceso adicional.
- Google acredita la identidad de acceso, no la verificacion comunitaria de Violeta.
- Si el correo ya existe, se pide la contrasena de Violeta una sola vez para vincularlo
  (plazo de 10 minutos). Si la olvidas, recuperala y repite Google.
- Los accesos siguientes se resuelven por el identificador estable `sub`, no por correo.
- Se conservan bloqueos y cambio obligatorio de contrasena. No se guardan tokens de Google
  ni se importa la foto de Google. Al borrar la cuenta se elimina la vinculacion.
- `Recordarme` se respeta. El flujo usa CSRF, state, nonce y PKCE mediante Authlib.
- Prueba cuenta nueva, cuenta existente, cancelacion, sesion caducada y cuenta restringida.
- La aplicacion nativa debe abrir OAuth en un navegador del sistema, no en un WebView
  incrustado. Este cambio integra el sitio web; no implementa retorno nativo/deep links.

Las pruebas locales simulan Google y no sustituyen una prueba real con credenciales
en local y Render. La publicacion y las credenciales requieren acceso del propietario.

Referencias: https://developers.google.com/identity/openid-connect/openid-connect
y https://docs.authlib.org/en/latest/client/flask.html
