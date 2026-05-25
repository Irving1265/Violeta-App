# Violeta - Red Social de Reporte Ciudadano

Violeta es una plataforma social moderna diseñada para fomentar la seguridad ciudadana a través del reporte comunitario. Inspirada en la fluidez de Instagram, permite a los usuarios compartir situaciones de riesgo o interés (hotspots), interactuar en tiempo real y visualizar zonas de seguridad mediante mapas interactivos.

---

## 📋 Tabla de Contenidos

1. [Características Principales](#-características-principales)
2. [Arquitectura del Sistema](#-arquitectura-del-sistema)
    - [Backend (Python/Flask)](#backend-pythonflask)
    - [Frontend (HTML/CSS/JS)](#frontend-htmlcssjs)
    - [Base de Datos](#base-de-datos)
3. [Diseño y UX/UI](#-diseño-y-uxui)
4. [Instalación y Configuración](#-instalación-y-configuración)
5. [Estructura del Proyecto](#-estructura-del-proyecto)
6. [API Reference](#-api-reference)

---

## 🚀 Características Principales

*   **Autenticación Segura**: Sistema robusto de registro e inicio de sesión con protección CSRF.
*   **Geolocalización en Tiempo Real**:
    *   **Hotspots**: Visualización de zonas de peligro/interés en un mapa interactivo (Leaflet).
    *   **Mini Mapa**: Widget lateral que muestra reportes cercanos a tu ubicación actual.
    *   **Filtrado por Ciudad**: Navegación rápida por municipios (Monterrey, San Pedro, etc.).
*   **Interacción Social**:
    *   Feed infinito con carga progresiva.
    *   Likes y Comentarios en tiempo real.
    *   Chat privado entre usuarios (Socket.IO).
*   **Reportes Completos**: Subida de imágenes con conversión automática (soporte HEIC), detección de hashtags y categorización automática.
*   **Búsqueda Inteligente**: Buscador unificado para usuarios, hashtags y ubicaciones.

---

## 🏗 Arquitectura del Sistema

### Backend (Python/Flask)
El núcleo de la aplicación está construido sobre **Flask**, utilizando un patrón MVC (Modelo-Vista-Controlador).

*   **App Core (`app.py`)**: Maneja la lógica de ruteo, autenticación (`Flask-Login`), y sockets (`Flask-SocketIO`).
*   **Manejo de Imágenes**: Procesamiento con **Pillow** y **pillow_heif** para asegurar que todas las fotos (incluso de iPhone) sean compatibles y ligeras.
*   **Geocodificación**: Integración con **Nominatim (OSM)** para convertir coordenadas GPS en direcciones legibles automáticamente.

### Frontend (HTML/CSS/JS)
La interfaz no depende de frameworks pesados como React o Vue, sino que utiliza una arquitectura ligera y rápida:

*   **Jinja2 Templates**: Renderizado del lado del servidor para una carga inicial veloz y SEO amigable.
*   **Vanilla JS Moderno (`app.js`)**: Manejo de interacciones asíncronas (`fetch` API), animaciones y lógica del cliente (Optimistic UI para comentarios/likes).
*   **Diseño Responsivo**: CSS nativo con variables (`:root`) para un tema oscuro consistente y "Mobile-First".

### Base de Datos
En desarrollo local puede usar **SQLite**, pero para staging/producción ya está preparada para usar **PostgreSQL administrado** vía `DATABASE_URL`.

**Modelos Principales (`models.py`):**
*   `User`: Perfil, auth y relaciones.
*   `Post`: Contenido, metadatos de ubicación (lat/lng), y media.
*   `Comment` / `Like`: Interacciones sociales.
*   `ChatRoom` / `ChatMessage`: Mensajería instantánea.

---

## 🎨 Diseño y UX/UI

El diseño "Violeta" se centra en una estética nocturna y elegante, utilizando una paleta de colores violetas y oscuros para reducir la fatiga visual y destacar el contenido.

### Sistema de Diseño (`style.css`)
*   **Colores**:
    *   Primario: `#8b5cf6` (Violeta vibrante)
    *   Fondo: `#13111C` (Deep Dark)
    *   Superficie: `#1E1B2E` (Tarjetas y paneles)
*   **Tipografía**: **Inter** (Google Fonts) para máxima legibilidad en UI.

### Experiencia de Usuario (UX)
*   **Transiciones de Página**: Navegación suave estilo SPA (Single Page Application) simulada con CSS transitions (`.page-enter`, `.page-leave`).
*   **Feedback Inmediato**: Los likes y comentarios aparecen instantáneamente (Optimistic UI) antes de confirmar con el servidor.
*   **Micro-interacciones**: Animaciones al dar like (corazón flotante), hover en botones y tooltips informativos.

---

## 🛠 Instalación y Configuración

### Prerrequisitos
*   Python 3.8+
*   Pip

### Pasos

1.  **Clonar el repositorio**:
    ```bash
    git clone https://github.com/tu-usuario/Violeta-App.git
    cd Violeta-App
    ```

2.  **Instalar dependencias**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Ejecutar la aplicación**:
    ```bash
    python app.py
    ```
    La aplicación iniciará en `http://localhost:5000`.

### Validación antes de subir cambios

Ejecuta el mismo bloque que corre GitHub Actions:

```bash
./.venv/bin/python scripts/ci_checks.py
```

Este comando compila los archivos críticos, bloquea hallazgos Bandit `High` y ejecuta el smoke suite completo. Si falla, corrige localmente antes de hacer commit o subir a GitHub.

Para revisar layout real en navegador, teléfono y web:

```bash
RUN_UI_SMOKE=1 ./.venv/bin/python scripts/ci_checks.py
```

Ese smoke levanta una base temporal, crea usuarias de prueba y valida feed, perfil, seguridad, chat y admin en viewports móvil/escritorio. Requiere Playwright Chromium instalado localmente.

### Health checks de producción

La app expone un endpoint seguro para monitoreo:

```bash
curl http://localhost:8000/healthz
```

También puedes ejecutarlo desde Flask CLI:

```bash
flask --app app:app health-check
```

El check valida base de datos, cache, backend de uploads, configuración de correo y workers background sin exponer secretos ni URLs internas. Usa `/healthz` como health check en Render o cualquier plataforma de deploy.

### Preflight antes de deploy

Antes de subir a producción, corre:

```bash
flask --app app:app preflight-check --strict
```

Este comando revisa configuración crítica de producción: `SECRET_KEY`, base de datos, storage de uploads, correo, cookies seguras, Redis recomendado y health check. No imprime secretos ni URLs completas.

### PostgreSQL administrado

Si vas a mover la app a una base administrada, revisa:

- [Migración a PostgreSQL](./docs/postgresql.md)
- [Gobernanza de datos y privacidad](./docs/data-governance.md)
- [Runbook operativo](./docs/operational-runbook.md)
- [Preparación de staging y producción](./docs/production-staging.md)
- [Checklist de lanzamiento Beta v1.0](./docs/beta-launch-checklist.md)

---

## 📂 Estructura del Proyecto

```
Violeta-App/
├── app.py              # Controlador principal y rutas
├── models.py           # Definición de esquema de BD
├── forms.py            # Formularios WTF (Validación)
├── config.py           # Variables de entorno y configuración
├── static/
│   ├── css/
│   │   ├── style.css   # Estilos globales y tema
│   │   └── post_create.css
│   ├── js/
│   │   ├── app.js      # Lógica principal (Likes, Comentarios, UI)
│   │   └── post_map.js # Lógica de mapas
│   └── uploads/        # Almacenamiento local de imágenes
└── templates/
    ├── base.html       # Layout maestro (Sidebar, Scripts comunes)
    ├── index.html      # Feed principal + Widget de Mapa
    ├── post_card.html  # Componente reutilizable de post
    └── chat.html       # Interfaz de mensajería
```

---

## 🔌 API Reference

Aunque es una aplicación SSR (Server Side Rendering), cuenta con endpoints JSON para funcionalidades dinámicas:

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `GET` | `/feed` | Obtiene posts paginados (Scroll Infinito). |
| `GET` | `/api/hotspots` | Devuelve coordenadas de zonas de riesgo para el mapa. |
| `GET` | `/api/search` | Búsqueda de usuarios y posts (`?q=query`). |
| `POST` | `/like/<id>` | Toggle like en una publicación. |
| `POST` | `/comment/<id>` | Agregar un comentario. |

---

> Propiedad de **Violeta App Team**.
> Desarrollado con ❤️ para la comunidad.
