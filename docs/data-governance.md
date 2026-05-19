# Gobernanza de Datos y Privacidad de Violeta

## Objetivo

Este documento define cómo Violeta debe recolectar, usar, proteger, retener y eliminar datos sensibles de la plataforma. Está basado en el estado real del proyecto Flask actual, no en una arquitectura idealizada.

El objetivo principal es reducir tres riesgos:

1. Exposición de la ubicación o identidad de la reportera.
2. Abuso interno o externo de datos privados.
3. Retención innecesaria de datos sensibles que aumente el daño en caso de fuga.

## Alcance

Aplica a:

- cuentas y autenticación
- verificación de identidad/elegibilidad
- reportes públicos de incidentes
- funciones de seguridad personal
- mensajería privada y adjuntos
- moderación, reportes y strikes
- exportaciones, almacenamiento y acceso administrativo

## Principios Rectores

1. Minimización de datos. Violeta solo debe guardar lo que necesita para operar seguridad, moderación y soporte.
2. Separación de contextos. Los datos públicos del incidente nunca deben mezclarse con datos privados de seguridad de la usuaria.
3. Menor privilegio. Nadie debe acceder a datos sensibles solo por “ser admin”; el acceso debe responder a una función concreta.
4. Retención corta por defecto. Si un dato deja de ser operativo, debe eliminarse.
5. Evidencia y trazabilidad. Todo acceso administrativo a datos sensibles debe quedar auditado.
6. Protección de población vulnerable. Las decisiones deben priorizar la seguridad de mujeres usuarias, incluidas mujeres trans.
7. No reutilización secundaria. Los datos privados no deben reutilizarse para marketing, analítica invasiva o entrenamiento de modelos.

## Clasificación de Datos

### 1. Cuenta y acceso

Incluye:

- `User.username`
- `User.email`
- `User.password_hash`
- estado de verificación de la cuenta
- sesiones y eventos de autenticación

Sensibilidad: alta.

Motivo operativo:

- crear cuentas
- autenticar acceso
- aplicar controles de seguridad y moderación

Reglas:

- nunca exportar `password_hash`
- no usar email para fines promocionales sin consentimiento explícito
- no mostrar email públicamente

### 2. Verificación de identidad/elegibilidad

Incluye:

- `VerificationRequest.phone`
- `VerificationRequest.status`
- `VerificationRequest.admin_notes`
- `VerificationRequest.reviewed_at`
- `VerificationRequest.reviewed_by`

Sensibilidad: muy alta.

Motivo operativo:

- comprobar persona real y elegibilidad para participar en la comunidad
- prevenir suplantación, cuentas falsas y abuso

Reglas:

- no almacenar sexo asignado al nacer, ni etiquetas como `cis` o `trans`
- no almacenar “pruebas biométricas” más allá del video temporal necesario para revisión
- la decisión operativa que sí puede permanecer es: `approved/rejected/pending`, fecha, revisora y nota administrativa breve
- el copy y la operación de verificación deben ser consistentes con inclusión de mujeres trans

### 3. Reportes públicos de incidentes

Incluye:

- `Post.caption`
- `Post.image_filename`
- `Post.latitude`
- `Post.longitude`
- `Post.location_name`
- `Post.city`
- `Post.country`
- `Post.categories`
- `Post.publish_at`
- `PostMeta.location_visibility`

Sensibilidad: media a alta.

Motivo operativo:

- informar a otras usuarias sobre incidentes o zonas de riesgo
- alimentar mapas, hotspots y búsqueda

Reglas:

- la ubicación pública corresponde al incidente, no a una ruta privada de la usuaria
- la imagen debe limpiarse de metadata antes de guardarse
- la publicación debe respetar controles de seguridad de producto
- no debe mostrarse información textual o visual que haga doxxing de la reportera

### 4. Seguridad personal y emergencia

Incluye:

- `SafetyContact.name`
- `SafetyContact.phone`
- `SafetyContact.relationship`
- `PanicEvent.latitude`
- `PanicEvent.longitude`
- `PanicEvent.note`
- `PanicEvent.status`
- `SafetyCheckin.destination`
- `SafetyCheckin.note`
- `SafetyCheckin.latitude`
- `SafetyCheckin.longitude`
- `CheckinRoutePoint.latitude`
- `CheckinRoutePoint.longitude`
- `CheckinRoutePoint.speed_kmh`
- `CheckinRoutePoint.accuracy_m`

Sensibilidad: crítica.

Motivo operativo:

- alertar contactos de confianza
- acompañar trayectos
- registrar incidentes de pánico y seguimiento temporal

Reglas:

- estos datos nunca son públicos
- acceso solo para la dueña del dato y personal autorizado de seguridad
- debe existir borrado automático por vencimiento de retención
- la ubicación exacta de trayectos no debe quedar disponible indefinidamente en paneles administrativos

### 5. Comunicación privada

Incluye:

- `ChatRoom`
- `ChatParticipant`
- `ChatMessage.content`
- adjuntos de chat
- estados de lectura
- bloqueos entre usuarias

Sensibilidad: alta.

Motivo operativo:

- mensajería entre usuarias
- comunidades/salas
- control de acoso, spam y abuso

Reglas:

- el chat no debe tratarse como contenido “público”
- sus adjuntos deben limpiarse de metadata
- el acceso administrativo debe limitarse a investigación de abuso o revisión de reportes

### 6. Moderación y cumplimiento

Incluye:

- `Report`
- `CommentReport`
- `ChatMessageReport`
- `ModerationStrike`
- notas administrativas
- razones de ocultamiento o sanción

Sensibilidad: alta.

Motivo operativo:

- responder a acoso, doxxing, amenazas, spam y desinformación dañina
- documentar restauraciones, sanciones y escalamiento de strikes

Reglas:

- conservar trazabilidad de quién reportó, quién resolvió y por qué
- no usar campos libres para copiar datos privados innecesarios
- restringir exportación masiva de evidencia

## Definiciones Operativas

### Dato público del incidente

Dato que ayuda a otras usuarias a evitar un lugar o entender un riesgo, por ejemplo:

- punto del incidente
- categoría del evento
- foto del entorno
- descripción del hecho

### Dato privado de la reportera

Dato que podría identificar, ubicar o rastrear a la usuaria que reporta, por ejemplo:

- ruta de desplazamiento
- contactos de emergencia
- check-ins
- eventos de pánico
- teléfono
- email
- evidencia de verificación

### Doxxing

Exposición de información que permite identificar, localizar o acosar a una persona. Incluye nombre completo, teléfono, dirección, placas, rutina, lugar de trabajo, escuela, links de mapa o cualquier combinación de datos que permita ubicarla.

## Matriz de Acceso Recomendada

Roles objetivo para una versión operable en producción:

- `super_admin`
- `verification_reviewer`
- `moderation_reviewer`
- `safety_operator`
- `support_readonly`

### Reglas por rol

`super_admin`

- administra configuración y personal
- no debe revisar de rutina videos, rutas o chats privados si otro rol puede hacerlo

`verification_reviewer`

- puede ver solicitudes de verificación y videos pendientes
- no debe acceder a panic events, rutas o chats salvo incidente formal

`moderation_reviewer`

- puede ver contenido reportado, strikes y evidencia mínima asociada
- no debe acceder a contactos de seguridad ni a trayectos completos

`safety_operator`

- puede ver panic events abiertos, contactos de confianza y check-ins activos
- no debe revisar verificación salvo necesidad formal documentada

`support_readonly`

- puede ver estado general de cuenta y banderas operativas
- no debe ver videos, coordenadas exactas de seguridad ni contenido privado completo

## Política de Retención Recomendada

Las ventanas siguientes son metas operativas recomendadas para Violeta. Si existe una obligación legal superior, debe documentarse aparte.

| Tipo de dato | Retención recomendada | Regla de borrado |
| :--- | :--- | :--- |
| Solicitud manual de verificación | mientras la cuenta siga activa | anonimizar o borrar al cerrar cuenta |
| Estado de verificación y revisión mínima | mientras la cuenta siga activa | anonimizar o borrar al cerrar cuenta |
| Foto y texto de post público | mientras el post exista | borrar media y registro al eliminar post |
| Metadata privada temporal de captura | no persistir, o menos de 24 h | purga automática |
| Panic events | 30 a 90 días | purga automática, salvo incidente abierto |
| Safety check-ins | 30 días | purga automática tras cierre |
| Route points de check-in | 7 a 30 días | purga automática tras cierre |
| Contactos de confianza | mientras la usuaria los mantenga | borrar inmediato al eliminar contacto o cuenta |
| Mensajes privados y adjuntos | mientras exista la conversación o política definida | borrar/anonimizar al cierre de cuenta según política |
| Reportes y strikes | 6 a 12 meses | anonimizar o purgar según necesidad operativa |
| Logs de acceso a datos sensibles | 12 meses | purga automática |

## Reglas Específicas por Flujo

### Registro e inicio de sesión

- guardar solo `username`, `email`, `password_hash` y estado necesario de cuenta
- prohibir exportaciones automáticas sensibles en producción
- registrar eventos anómalos de acceso, no el contenido privado de la usuaria

### Verificación

- usar revisión manual sin códigos temporales ni dependencias externas de acceso
- las notas administrativas deben evitar describir rasgos físicos innecesarios
- la decisión final debe registrar solo el mínimo necesario para operar la cuenta

### Publicación de reportes

- la publicación debe salir de captura directa, no de una galería histórica, en la medida en que la plataforma lo permita
- la imagen debe procesarse para remover EXIF y metadata
- la ubicación del incidente puede ser pública si la regla de seguridad del producto lo permite
- la publicación no debe revelar rutas privadas ni contactos de la usuaria

### Emergencia y acompañamiento

- los datos de contactos, panic events y trayectos son confidenciales por defecto
- el acceso administrativo a estos datos debe registrarse siempre
- la notificación a contactos debe limitarse a la información mínima necesaria para ayudar
- no se debe afirmar integración automática con policía si no existe integración oficial real

### Chat y comunidades

- mensajes y adjuntos son privados por defecto
- solo se abren a moderación por reporte, abuso o investigación formal
- las herramientas internas deben mostrar la mínima evidencia necesaria

### Moderación

- alto riesgo debe permitir contención inmediata
- el motivo y la resolución deben quedar documentados
- los strikes deben ser trazables, consistentes y apelables

## Controles Técnicos Recomendados

1. RBAC formal en backend, no solo `username == 'admin'`.
2. Auditoría de acceso para:
   - solicitudes de verificación
   - panic events
   - contactos de confianza
   - route points
   - chats privados revisados por moderación
3. Jobs de purga automática por retención.
4. Separación de buckets o prefijos de almacenamiento por dominio:
   - público
   - verificación temporal
   - chat privado
   - evidencia de moderación
5. Cifrado en tránsito y en reposo donde aplique el proveedor.
6. Prohibición de dumps o exportaciones manuales no auditadas.
7. Eliminación o anonimización al cierre de cuenta.

## Estado Actual del Proyecto

### Ya implementado

- limpieza de metadata de imágenes al guardar archivos
- exportación automática de usuarias deshabilitada por defecto y sin `password_hash`
- moderación de alto riesgo con ocultamiento inmediato
- flujo de publicación con reglas de seguridad temporal y de distancia
- captura restringida a cámara y bloqueo por movimiento rápido como control de producto

### Aún pendiente

- RBAC formal por rol
- reemplazar el control actual concentrado en una sola cuenta `admin`
- bitácora de acceso a datos sensibles
- jobs automáticos de purga por retención
- flujo formal de borrado/anonimización de cuenta
- política visible para usuarias sobre retención y eliminación
- runbooks internos para incidentes de privacidad

## Decisiones de Producto que Deben Mantenerse Coherentes

1. Violeta es una comunidad para mujeres, incluidas mujeres trans.
2. El sistema de verificación debe resolver elegibilidad operativa sin almacenar categorías identitarias innecesarias.
3. La plataforma debe privilegiar seguridad física sobre velocidad de publicación.
4. Los datos de seguridad privada no deben reutilizarse para funciones sociales.

## Prioridad de Implementación Recomendada

1. RBAC formal para separar verificación, moderación y seguridad.
2. Purga automática de verificación pendiente, panic events y route points.
3. Auditoría de acceso a datos sensibles.
4. Flujo de eliminación/anonimización de cuenta.
5. Pantalla o política pública de privacidad y retención alineada con este documento.

## Próximo Entregable Técnico

Después de este documento, la implementación más importante es:

1. crear roles reales en base de datos y middleware de acceso
2. programar jobs de purga por retención
3. registrar accesos administrativos a recursos sensibles
