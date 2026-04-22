from dataclasses import asdict
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.dashboard.models import (
    ConnectivityStatus,
    DashboardPageModel,
    FeaturedMission,
    FunnelStep,
    LeaderIdentity,
    LeaderTask,
    NavItem,
    PatrolStatus,
    PatrolCertificate,
    StatCard,
)
from apps.scouting.models import Event, Patrol, PatrolYouTubeSubmission, PointLog, Submission
from apps.scouting.services.poentaro_engine import PoentaroEngine


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

    def __init__(self, user=None) -> None:
        self.user = user

    def _led_patrols(self):
        qs = Patrol.objects.select_related("event").filter(is_active=True)
        if self.user and getattr(self.user, "is_authenticated", False):
            user_email = (self.user.email or "").strip().lower()
            if user_email:
                by_email = qs.filter(leader_email__iexact=user_email)
                if by_email.exists():
                    return by_email.order_by("delegation_name", "name")
            user_name = (getattr(self.user, "get_full_name", lambda: "")() or self.user.username or "").strip()
            if user_name:
                by_name = qs.filter(leader_name__icontains=user_name)
                if by_name.exists():
                    return by_name.order_by("delegation_name", "name")
        return qs.order_by("delegation_name", "name")[:6]

    @staticmethod
    def _telegram_link(chat_id: int | None) -> str:
        if not chat_id:
            return ""
        raw = str(chat_id)
        if raw.startswith("-100") and len(raw) > 4:
            return f"https://t.me/c/{raw[4:]}"
        return f"tg://openmessage?chat_id={raw}"

    def _build_group_participation_metrics(self) -> dict:
        now = timezone.now()
        window_start = now - timedelta(days=2)

        recent_logs = PointLog.objects.filter(created_at__gte=window_start)
        active_patrol_ids = list(
            recent_logs.values_list("patrol_id", flat=True).distinct()
        )

        active_patrols = Patrol.objects.filter(id__in=active_patrol_ids).count()
        text_count = recent_logs.filter(event_type=PointLog.EventType.TEXT_VALIDATED).count()
        audio_count = recent_logs.filter(event_type=PointLog.EventType.AUDIO_VALIDATED).count()
        yt_count = recent_logs.filter(event_type=PointLog.EventType.YOUTUBE_MISSION).count()

        recent_youtube = PatrolYouTubeSubmission.objects.filter(audited_at__gte=window_start)
        teamwork_votes = 0
        teamwork_total = 0
        for submission in recent_youtube:
            findings = submission.audit_findings or {}
            has_teamwork = findings.get("has_teamwork")
            if isinstance(has_teamwork, bool):
                teamwork_total += 1
                teamwork_votes += 1 if has_teamwork else 0

        teamwork_pct = int((teamwork_votes * 100 / teamwork_total)) if teamwork_total else 0

        return {
            "window_label": f"{window_start.strftime('%d/%m')} - {now.strftime('%d/%m')}",
            "active_patrols": active_patrols,
            "text_count": text_count,
            "audio_count": audio_count,
            "yt_count": yt_count,
            "teamwork_pct": teamwork_pct,
            "last_update_note": "Actualizado cada 2 dias (ventana movil).",
        }

    def _build_patrol_progress(self) -> list[PatrolStatus]:
        engine = PoentaroEngine()
        rows: list[PatrolStatus] = []
        for patrol in self._led_patrols():
            snapshot = engine.compute(patrol)
            if snapshot.mcer_level == "B1":
                dot = "bg-moss"
            elif snapshot.mcer_level == "A2":
                dot = "bg-amber-500"
            else:
                dot = "bg-rose-500"

            rows.append(
                PatrolStatus(
                    name=f"{patrol.delegation_name} / {patrol.name}",
                    status_dot=dot,
                    summary=(
                        f"Poentaro {snapshot.effective_score} pts · "
                        f"MCER {snapshot.mcer_level} · SEL {patrol.sel_points}"
                    ),
                    telegram_link=self._telegram_link(patrol.telegram_chat_id),
                    progress_label=f"Base {snapshot.base_points} · Telegram {snapshot.daily_telegram_points} · Pares {snapshot.peer_validation_points}",
                )
            )
        return rows

    def _build_leader_tasks(self) -> list[LeaderTask]:
        led_patrols = list(self._led_patrols())
        if not led_patrols:
            return [
                LeaderTask(
                    title="Sin patrullas asignadas",
                    description="No se encontraron patrullas lideradas por este usuario.",
                    tag="Info",
                    tag_tone="pine",
                )
            ]

        submissions = Submission.objects.filter(patrol__in=led_patrols).select_related("mission", "patrol")

        pending_qs = submissions.filter(status=Submission.Status.REJECTED).order_by("-submitted_at")[:3]
        to_validate_qs = submissions.filter(status=Submission.Status.RECEIVED).order_by("-submitted_at")[:3]
        validated_qs = submissions.filter(status=Submission.Status.REVIEWED).order_by("-submitted_at")[:3]

        tasks: list[LeaderTask] = []

        if to_validate_qs:
            for submission in to_validate_qs:
                tasks.append(
                    LeaderTask(
                        title=f"A validar: {submission.mission.title}",
                        description=f"{submission.patrol.delegation_name} / {submission.patrol.name}",
                        tag="A validar",
                        tag_tone="bark",
                    )
                )

        if pending_qs:
            for submission in pending_qs:
                tasks.append(
                    LeaderTask(
                        title=f"Pendiente: {submission.mission.title}",
                        description=f"{submission.patrol.delegation_name} / {submission.patrol.name}",
                        tag="Pendiente",
                        tag_tone="pine",
                    )
                )

        if validated_qs:
            for submission in validated_qs:
                tasks.append(
                    LeaderTask(
                        title=f"Validado: {submission.mission.title}",
                        description=f"{submission.patrol.delegation_name} / {submission.patrol.name}",
                        tag="Validado",
                        tag_tone="moss",
                    )
                )

        return tasks or [
            LeaderTask(
                title="Sin tareas operativas",
                description="No hay submissions pendientes, a validar o validadas para mostrar.",
                tag="Info",
                tag_tone="pine",
            )
        ]

    def _build_certificate(self) -> PatrolCertificate:
        active_event = Event.objects.filter(is_active=True).order_by("-starts_at").first()
        event = active_event or Event.objects.order_by("-starts_at").first()

        if not event:
            return PatrolCertificate(
                patrol_id=None,
                title="Certificado de patrulla lista",
                patrol_name="Sin patrulla disponible",
                event_name="Aun no hay eventos",
                achievement="Carga tu primer evento y submissions para habilitar certificados operativos.",
                issued_on=timezone.localdate().strftime("%d/%m/%Y"),
                scout_count="0 scouts",
                verification_code="LGL-PENDING-000",
                share_target_email="",
                accents=["Esperando datos reales", "Sin submissions registradas", "Estado: inicial"],
            )

        patrol = (
            Patrol.objects.filter(event=event, is_active=True)
            .annotate(
                submission_count=Count("submissions"),
                reviewed_count=Count(
                    "submissions",
                    filter=Q(submissions__status=Submission.Status.REVIEWED),
                ),
                last_submission_at=Max("submissions__submitted_at"),
            )
            .order_by("-reviewed_count", "-submission_count", "delegation_name", "name")
            .first()
        )

        if not patrol:
            return PatrolCertificate(
                patrol_id=None,
                title="Certificado de patrulla lista",
                patrol_name="Sin patrulla activa",
                event_name=event.name,
                achievement="El evento existe, pero todavia no hay patrullas activas para certificar.",
                issued_on=timezone.localdate().strftime("%d/%m/%Y"),
                scout_count="0 scouts",
                verification_code=f"LGL-{event.id:03d}-NOPATROL",
                share_target_email="",
                accents=["Evento preparado", "Sin patrullas activas", "Estado: pendiente"],
            )

        latest_submission = (
            Submission.objects.filter(patrol=patrol)
            .select_related("mission")
            .order_by("-submitted_at")
            .first()
        )

        submission_count = Submission.objects.filter(patrol=patrol).count()
        reviewed_count = Submission.objects.filter(
            patrol=patrol,
            status=Submission.Status.REVIEWED,
        ).count()

        mission_note = "Sin mision enviada aun"
        if latest_submission:
            mission_note = f"Ultima mision: {latest_submission.mission.title}"

        return PatrolCertificate(
            patrol_id=patrol.id,
            title="Certificado de patrulla lista",
            patrol_name=patrol.name,
            event_name=event.name,
            achievement=(
                f"Delegacion {patrol.delegation_name}. "
                f"Submissions revisadas: {reviewed_count}/{submission_count}."
            ),
            issued_on=timezone.localdate().strftime("%d/%m/%Y"),
            scout_count=f"{patrol.member_count} scouts",
            verification_code=(
                f"LGL-{event.id:03d}-{patrol.id:03d}-{timezone.localdate().strftime('%Y%m%d')}"
            ),
            share_target_email=patrol.leader_email,
            accents=[
                f"Idioma oficial: {patrol.official_language_name}",
                mission_note,
                f"Pais: {patrol.country_name}",
            ],
        )

    def get_context(self) -> dict:
        certificate = self._build_certificate()
        participation = self._build_group_participation_metrics()
        patrol_progress = self._build_patrol_progress()
        leader_tasks = self._build_leader_tasks()
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
                last_sync=participation["window_label"],
                pending_messages=str(participation["active_patrols"]),
            ),
            hero_copy=(
                "Supervisa el onboarding del bot, asigna misiones y detecta patrullas sin "
                "cobertura sin depender de imagenes pesadas ni tablas densas."
            ),
            stats=[
                StatCard(
                    label="Scouts activos",
                    value=str(participation["active_patrols"]),
                    caption="Patrullas activas en la ventana de 2 dias",
                    tone="bg-canvas",
                ),
                StatCard(
                    label="Idiomas en uso",
                    value=str(len(self.supported_languages)),
                    caption=", ".join(self.supported_languages),
                    tone="bg-fog",
                ),
                StatCard(
                    label="Participacion grupal (2 dias)",
                    value=f"{participation['teamwork_pct']}%",
                    caption=(
                        f"Textos {participation['text_count']} · Audios {participation['audio_count']} · "
                        f"YouTube {participation['yt_count']}"
                    ),
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
                        "204 eligieron idioma entre 15 opciones con botones grandes, "
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
                *leader_tasks,
            ],
            patrols=patrol_progress,
            certificate=certificate,
        )

        return asdict(page_model)