from dataclasses import asdict

from apps.dashboard.models import (
    ConnectivityStatus,
    DashboardPageModel,
    FeaturedMission,
    FunnelStep,
    LeaderIdentity,
    LeaderTask,
    NavItem,
    PatrolStatus,
    StatCard,
)


class LeaderDashboardController:
    # Subtenataj lingvoj de la platformo — ĉiu reprezentas oficialan lingvon de delegacio
    supported_languages = [
        "ES",
        "EN",
        "PT",
        "TH",
        "KO",
        "JA",
        "FR",
        "ZH",
        "HI",
        "AR",
        "DE",
        "RU",
        "PL",  # Pola
        "UK",  # Ukraina
        "IT",  # Itala
    ]

    def get_context(self) -> dict:
        page_model = DashboardPageModel(
            lang="es",
            leader=LeaderIdentity(initial="L"),
            nav_items=[
                NavItem(label="Resumen de patrulla", href="#", active=True),
                NavItem(label="Misiones activas", href="#"),
                NavItem(label="Progreso por equipo", href="#"),
                NavItem(label="Mensajes offline", href="#"),
                NavItem(label="Ajustes de idioma", href="#"),
            ],
            connectivity=ConnectivityStatus(
                note=(
                    "Modo ligero activado. El panel prioriza texto, iconos simples y colas "
                    "sincronizables para conexiones lentas."
                ),
                last_sync="Hace 42 s",
                pending_messages="12",
            ),
            hero_copy=(
                "Supervisa el onboarding del bot, asigna misiones y detecta patrullas sin "
                "cobertura sin depender de imagenes pesadas ni tablas densas."
            ),
            stats=[
                StatCard(
                    label="Scouts activos",
                    value="128",
                    caption="94% completo en onboarding",
                    tone="bg-canvas",
                ),
                StatCard(
                    label="Idiomas en uso",
                    value=str(len(self.supported_languages)),
                    caption=", ".join(self.supported_languages),
                    tone="bg-fog",
                ),
                StatCard(
                    label="Misiones urgentes",
                    value="07",
                    caption="2 esperan confirmacion",
                    tone="bg-white",
                    emphasis="warn",
                ),
            ],
            funnel_steps=[
                FunnelStep(
                    badge="Paso 1",
                    title="Inicio",
                    description="221 scouts recibieron el mensaje de bienvenida con CTA unico y ligero.",
                    value="221",
                ),
                FunnelStep(
                    badge="Paso 2",
                    title="Idioma",
                    description=(
                        "204 eligieron idioma entre 12 opciones con botones grandes, "
                        "etiquetas cortas y scroll ligero."
                    ),
                    value="92%",
                ),
                FunnelStep(
                    badge="Paso 3",
                    title="Mision recibida",
                    description=(
                        "176 confirmaron mision. Hay friccion en patrullas con senal intermitente."
                    ),
                    value="176",
                    highlight=True,
                ),
                FunnelStep(
                    badge="Paso 4",
                    title="Listo para salida",
                    description=(
                        "165 scouts ya enviaron PREPARADO y pueden arrancar la actividad."
                    ),
                    value="75%",
                ),
            ],
            featured_mission=FeaturedMission(
                title="Ruta del faro",
                status="En curso",
                objective="Confirmar orientacion y registrar punto seguro antes de las 18:30.",
                channel="Telegram bot en modo texto plano",
                response="RECIBIDA o NECESITO AYUDA",
                note=(
                    "El mensaje evita bloques largos, prioriza verbos claros y deja una "
                    "ruta de emergencia visible en el primer scroll."
                ),
            ),
            tasks=[
                LeaderTask(
                    title="Revisar scouts sin idioma confirmado",
                    description=(
                        "13 usuarios entraron por enlace compartido y no terminaron la "
                        "seleccion entre 12 idiomas disponibles."
                    ),
                    tag="Prioridad alta",
                    tag_tone="bark",
                ),
                LeaderTask(
                    title="Reenviar mision a patrulla Norte",
                    description=(
                        "La confirmacion no llego tras 2 intentos; sugerido fallback SMS interno."
                    ),
                    tag="Automatizable",
                    tag_tone="moss",
                ),
                LeaderTask(
                    title="Cerrar briefing de seguridad",
                    description=(
                        "El panel sugiere convertir el briefing en mensaje fijo para 5 grupos nuevos."
                    ),
                    tag="Hoy",
                    tag_tone="pine",
                ),
            ],
            patrols=[
                PatrolStatus(
                    name="Patrulla Roble",
                    status_dot="bg-moss",
                    summary="10 scouts. 100% mision recibida.",
                ),
                PatrolStatus(
                    name="Patrulla Brasa",
                    status_dot="bg-amber-500",
                    summary="8 scouts. 2 respuestas retrasadas.",
                ),
                PatrolStatus(
                    name="Patrulla Rio",
                    status_dot="bg-rose-500",
                    summary="12 scouts. Activar modo de reintento ligero.",
                ),
            ],
        )

        return asdict(page_model)