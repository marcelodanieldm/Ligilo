# Ligilo

Ligilo es una plataforma scout fullstack para coordinación internacional entre patrullas, validación de misiones y progresión lingüística en Esperanto. El proyecto combina Django para operación interna y paneles, FastAPI para integraciones y bot workflows, y PostgreSQL como fuente compartida de datos.

## Estado actual

El repositorio ya incluye estas capacidades operativas:

- Onboarding scout de 3 pasos para patrullas con activación de nodo Telegram.
- Dashboard de operaciones con métricas Poentaro y reglas de desbloqueo para marketplace.
- Certificado MCER `/atestilo` con generación PDF, QR y modo previsualización con marca de agua.
- Flujo de validación de video YouTube con auditoría IA y aprobación final humana.
- Hitos MCER A1, A2, B1, B2 calculados con `PoentaroEngine`.
- Admin de Django extendido para patrullas, miembros, intereses y certificados MCER.

## Stack

- Django para panel interno, autenticación, vistas, formularios y Django Admin.
- FastAPI para servicios complementarios y puente con Telegram.
- PostgreSQL como base de datos compartida entre Django y FastAPI.
- `python-telegram-bot` para los comandos y eventos del bot scout.
- ReportLab, Pillow y `qrcode` para certificados PDF.
- Integraciones Google para validación/auditoría de videos.

## Módulos principales

- `apps/scouting/models.py`: dominio scout, patrullas, match internacional, submissions, MCER, onboarding y YouTube review.
- `apps/scouting/forms.py`: formularios del onboarding de patrulla y carga de miembros.
- `apps/scouting/services/poentaro_engine.py`: cálculo compuesto de progreso MCER.
- `apps/scouting/services/certificate_generator.py`: generación de PDF para certificados de excelencia y Atestilo MCER.
- `apps/dashboard/views.py`: onboarding de 3 pasos, dashboard de operaciones y revisión humana de YouTube.
- `apps/dashboard/controllers/leader_dashboard_controller.py`: contexto operativo del dashboard de líder.
- `fastapi_app/services/telegram_bot.py`: comandos del bot, incluyendo `/atestilo` y notificaciones de hitos.
- `fastapi_app/services/telegram_manager.py`: generación de enlaces para nodos compartidos de Telegram.
- `fastapi_app/db_bridge.py`: puente FastAPI-Django para puntos, certificados, submissions e incidencias.

## Flujos implementados

### 1. Onboarding Promesa Digital

- Paso A: identidad de patrulla, delegación, país, idioma oficial, evento e intereses.
- Paso B: registro de 2 a 5 miembros con validación de edad entre 11 y 25 años.
- Paso C: activación del nodo Telegram con enlace único y control de miembros unidos.

Rutas:

- `/patrol/onboarding/<uuid:token>/step-a/`
- `/patrol/onboarding/<uuid:token>/step-b/`
- `/patrol/onboarding/<uuid:token>/step-c/`
- `/patrol/operations/<uuid:token>/`

### 2. Progresión MCER y Poentaro

`PoentaroEngine` calcula una puntuación efectiva a partir de:

- puntos base SEL,
- bono diario por participación de equipo en Telegram,
- validación entre pares,
- multiplicador del líder según aprobación final.

Umbrales definidos:

- A1: 0 a 1000 puntos
- A2: 1001 a 3000 puntos
- B1: 3001 a 6000 puntos
- B2: 6001 o más

### 3. Certificado MCER `/atestilo`

El bot genera un PDF con:

- nombre de patrulla y patrulla hermana,
- nivel MCER alcanzado,
- código único de certificación,
- QR al muro de la fama,
- marca de agua de previsualización si la patrulla está por debajo del 80% del umbral B1.

Regla de previsualización:

- menos de 2401 puntos: certificado con marca de agua,
- 2401 puntos o más: certificado completo sin marca de agua.

### 4. Video final YouTube

El flujo actual contempla:

- validación de metadata del video,
- auditoría IA del contenido y del Esperanto,
- revisión final del líder en `/scouts/youtube/review/<submission_id>/`,
- otorgamiento de puntos al aprobar.

### 5. Dashboard de operaciones

La central de operaciones muestra:

- nivel MCER actual,
- barra de energía Poentaro,
- desglose de puntos `Linguo`, `Amikeco` y `Agado`,
- feedback IA reciente,
- marketplace con candados por validación 360°.

Reglas de desbloqueo actuales:

- parche B1: 3500 puntos efectivos y 4 videos con validación 360°,
- parche B2: 6000 puntos efectivos y proyecto de liderazgo validado.

## Reglas de negocio principales

- En un mismo evento no pueden coexistir patrullas de países con el mismo idioma oficial.
- Los `PatrolMatch` solo son válidos cuando las patrullas hablan idiomas oficiales distintos.
- Las `Submission` solo pueden provenir de patrullas incluidas en el match asociado a la misión.
- `PatrolMember` valida edad mínima de 11 y máxima de 25 años.
- Los intereses de patrulla no se repiten por patrulla.
- El parche B1 y B2 no se muestra como pagable hasta cumplir validación 360° y condiciones de negocio.

## Migraciones

Migraciones relevantes del estado actual:

- `0014`: YouTube submissions y rover incidents.
- `0015`: flags de notificación MCER.
- `0016`: onboarding de patrulla, `PatrolMember`, `PatrolInterest` y `MCERCertificate`.

Situación verificada en este entorno:

- `makemigrations scouting --noinput`: sin cambios pendientes.
- `python manage.py check`: sin issues.
- `python -m py_compile apps/scouting/migrations/0016_patrol_leadership_project_validated_and_more.py`: correcto.
- `python manage.py migrate scouting`: bloqueado por timeout contra PostgreSQL en `localhost:5432`.

Mientras PostgreSQL no responda, la migración `0016` no puede aplicarse en este entorno.

## Arranque local

1. Crear y activar entorno virtual.
2. Copiar `.env.example` a `.env` y ajustar variables de PostgreSQL, Telegram, Stripe y Google si aplican.
3. Instalar dependencias con `pip install -r requirements.txt`.
4. Levantar PostgreSQL local o vía Docker.
5. Ejecutar `python manage.py migrate`.
6. Crear superusuario con `python manage.py createsuperuser`.
7. Levantar Django con `python manage.py runserver`.
8. Levantar FastAPI con `uvicorn fastapi_app.main:app --reload --port 8001`.

## Arranque con Docker

1. Ajustar `.env` con credenciales seguras.
2. Ejecutar `docker compose up --build`.
3. Acceder a Django en `http://localhost:8000`.
4. Acceder a FastAPI en `http://localhost:8001`.

## Endpoints y superficies útiles

- Django login: `/login/`
- Django admin: `/admin/`
- Dashboard líder: `/`
- Revisión humana YouTube: `/scouts/youtube/review/<submission_id>/`
- FastAPI health: `/health`
- FastAPI webhook placeholder: `/webhooks/telegram`
- Comando Telegram: `/atestilo`

## Validación reciente

Comandos verificados en esta sesión:

- `python manage.py makemigrations scouting --noinput`
- `python manage.py check`
- `python -m py_compile apps/scouting/migrations/0016_patrol_leadership_project_validated_and_more.py`

Resultado:

- código Python y migración `0016` válidos,
- sin cambios de migración pendientes,
- aplicación de migración bloqueada por falta de conectividad con PostgreSQL.

## Nota de arquitectura

La aplicación mantiene una separación pragmática:

- Django concentra dominio, admin, templates y vistas operativas.
- FastAPI expone integraciones y flujos asíncronos alrededor del bot.
- ambos comparten PostgreSQL para no duplicar estado.

El dashboard del líder usa un controlador para preparar contexto, mientras que la lógica de negocio más sensible queda encapsulada en servicios y modelos del dominio scout.
