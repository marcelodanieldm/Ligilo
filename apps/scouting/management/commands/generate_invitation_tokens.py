import csv
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.scouting.models import Event, Patrol


class Command(BaseCommand):
    help = (
        "Genera tokens UUID para patrullas de un evento y exporta un CSV "
        "listo para Product Owner."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "event_ref",
            help="ID numerico o slug del evento objetivo.",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help="Cantidad maxima de patrullas a tokenizar (default: 50).",
        )
        parser.add_argument(
            "--output",
            default="outputs/invitation_tokens_{event_slug}.csv",
            help=(
                "Ruta del CSV de salida. Puedes usar {event_slug} y {event_id} "
                "como placeholders."
            ),
        )

    def handle(self, *args, **options):
        event_ref = str(options["event_ref"]).strip()
        count = options["count"]
        output_pattern = options["output"]

        if count < 1:
            raise CommandError("--count debe ser mayor o igual a 1.")

        event = self._resolve_event(event_ref)

        patrols = list(
            Patrol.objects.filter(event=event, is_active=True)
            .order_by("delegation_name", "name")[:count]
        )
        if not patrols:
            raise CommandError("No hay patrullas activas para ese evento.")

        for patrol in patrols:
            # Ni uzas UUID-v4 por forta entropio kaj facila validigo.
            patrol.invitation_token = uuid.uuid4()
        Patrol.objects.bulk_update(patrols, ["invitation_token", "updated_at"])

        output_path = Path(
            output_pattern.format(event_slug=event.slug, event_id=event.id)
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "event_id",
                    "event_name",
                    "patrol_id",
                    "delegation_name",
                    "patrol_name",
                    "leader_email",
                    "invitation_token",
                ]
            )
            for patrol in patrols:
                writer.writerow(
                    [
                        event.id,
                        event.name,
                        patrol.id,
                        patrol.delegation_name,
                        patrol.name,
                        patrol.leader_email,
                        str(patrol.invitation_token),
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Se generaron {len(patrols)} tokens para '{event.name}'. CSV: {output_path}"
            )
        )

    @staticmethod
    def _resolve_event(event_ref: str) -> Event:
        if event_ref.isdigit():
            event = Event.objects.filter(id=int(event_ref)).first()
            if event:
                return event

        event = Event.objects.filter(slug=event_ref).first()
        if event:
            return event

        raise CommandError(f"Evento no encontrado con referencia '{event_ref}'.")
