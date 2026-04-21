# Ligilo

Estructura inicial fullstack para Ligilo con Django, FastAPI y PostgreSQL, lista para evolucionar hacia Docker.

## Stack

- Django para panel interno, autenticacion y Django Admin.
- FastAPI para webhooks y servicios futuros.
- PostgreSQL como base de datos compartida entre Django y FastAPI.
- Tailwind CSS via CDN en templates Django.

## Estructura principal

- `apps/scouting/models.py`: modelos de dominio `Event`, `Patrol`, `PatrolMatch`, `Mission` y `Submission`.
- `apps/scouting/admin.py`: admin personalizado para la SEL y gestion de delegaciones.
- `apps/dashboard/`: dashboard MVC del lider.
- `templates/registration/login.html`: login de lideres con Tailwind CDN.
- `fastapi_app/main.py`: instancia base de FastAPI.
- `fastapi_app/database.py`: conexion SQLAlchemy a la misma DB de Django.
- `config/settings.py`: configuracion Django orientada a PostgreSQL.
- `docker-compose.yml`: servicios base para `db`, `django` y `fastapi`.

## Reglas de negocio implementadas

- En un mismo evento no pueden coexistir patrullas de paises con el mismo idioma oficial.
- Los `PatrolMatch` solo son validos cuando las patrullas hablan idiomas oficiales distintos.
- Las `Submission` solo pueden venir de patrullas incluidas en el match asociado a la mision.

## Arranque local

1. Crear y activar entorno virtual.
2. Copiar `.env.example` a `.env` y ajustar credenciales de PostgreSQL.
3. Instalar dependencias con `pip install -r requirements.txt`.
4. Levantar PostgreSQL local o via Docker.
5. Ejecutar `python manage.py migrate`.
6. Crear superusuario con `python manage.py createsuperuser`.
7. Levantar Django con `python manage.py runserver`.
8. Levantar FastAPI con `uvicorn fastapi_app.main:app --reload --port 8001`.

## Arranque con Docker

1. Ajustar `.env` con credenciales seguras.
2. Ejecutar `docker compose up --build`.
3. Acceder a Django en `http://localhost:8000`.
4. Acceder a FastAPI en `http://localhost:8001`.

## Endpoints iniciales

- Django login: `/login/`
- Django admin: `/admin/`
- Dashboard lider: `/`
- FastAPI health: `/health`
- FastAPI webhook placeholder: `/webhooks/telegram`

## Nota de arquitectura

Se mantiene una estructura MVC pragmatica dentro de Django: la presentacion vive en templates, el dashboard usa controlador para preparar contexto y el dominio principal queda aislado en la app `scouting`. FastAPI comparte la misma base de datos para futuras integraciones sin duplicar estado.
