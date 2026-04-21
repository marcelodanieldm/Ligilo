import secrets

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


class Event(models.Model):
    name = models.CharField(max_length=180)
    slug = models.SlugField(unique=True, max_length=200)
    host_city = models.CharField(max_length=120)
    host_country = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_at", "name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Patrol(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="patrols")
    name = models.CharField(max_length=120)
    delegation_name = models.CharField(max_length=160)
    country_code = models.CharField(max_length=2)
    country_name = models.CharField(max_length=120)
    official_language_code = models.CharField(max_length=8)
    official_language_name = models.CharField(max_length=120)
    leader_name = models.CharField(max_length=160)
    leader_email = models.EmailField(blank=True)
    telegram_chat_id = models.BigIntegerField(blank=True, null=True, unique=True)
    invitation_token = models.CharField(max_length=32, blank=True, null=True, unique=True)
    member_count = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["event", "delegation_name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "official_language_code"],
                name="unique_official_language_per_event",
            ),
            models.UniqueConstraint(
                fields=["event", "delegation_name", "name"],
                name="unique_patrol_per_delegation",
            ),
            models.CheckConstraint(
                condition=Q(member_count__gte=1),
                name="member_count_gte_1",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.delegation_name} - {self.name}"

    @staticmethod
    def _build_invitation_token() -> str:
        # Ni uzas mallongan URL-sekuran token por facila mana enigo en Telegram.
        return secrets.token_urlsafe(10).replace("-", "").replace("_", "")[:16].upper()

    def save(self, *args, **kwargs):
        if not self.invitation_token:
            token = self._build_invitation_token()
            while Patrol.objects.filter(invitation_token=token).exists():
                token = self._build_invitation_token()
            self.invitation_token = token
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        duplicated_language = Patrol.objects.filter(
            event=self.event,
            official_language_code__iexact=self.official_language_code,
        ).exclude(pk=self.pk)
        if duplicated_language.exists():
            raise ValidationError(
                {
                    "official_language_code": (
                        "En la sama evento ne rajtas ekzisti landoj kun la sama oficiala lingvo."
                    )
                }
            )


class PatrolMatch(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Propuesto"
        ACTIVE = "active", "Activo"
        CLOSED = "closed", "Cerrado"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="matches")
    patrol_a = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="matches_as_a")
    patrol_b = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="matches_as_b")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    matched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["event", "-matched_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "patrol_a", "patrol_b"],
                name="unique_patrol_match_ordered",
            ),
            models.CheckConstraint(
                condition=~Q(patrol_a=models.F("patrol_b")),
                name="patrols_must_be_different",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.patrol_a} <> {self.patrol_b}"

    def clean(self):
        super().clean()
        if self.patrol_a_id and self.patrol_b_id and self.patrol_a_id == self.patrol_b_id:
            raise ValidationError("Patrola kongruo postulas du malsamajn patrolojn.")
        if self.patrol_a_id and self.patrol_b_id:
            if self.patrol_a.event_id != self.event_id or self.patrol_b.event_id != self.event_id:
                raise ValidationError("Ambaŭ patroloj devas aparteni al la sama evento de la kongruo.")
            if (
                self.patrol_a.official_language_code.lower()
                == self.patrol_b.official_language_code.lower()
            ):
                raise ValidationError(
                    "Patroloj devas kongrui nur kiam ili parolas malsamajn oficialajn lingvojn."
                )
            reverse_exists = PatrolMatch.objects.filter(
                event=self.event,
                patrol_a=self.patrol_b,
                patrol_b=self.patrol_a,
            ).exclude(pk=self.pk)
            if reverse_exists.exists():
                raise ValidationError("La inversa kongruo jam ekzistas por tiuj patroloj.")


class Mission(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicada"
        CLOSED = "closed", "Cerrada"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="missions")
    patrol_match = models.ForeignKey(
        PatrolMatch,
        on_delete=models.CASCADE,
        related_name="missions",
    )
    title = models.CharField(max_length=180)
    briefing = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    opens_at = models.DateTimeField()
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["event", "due_at", "title"]

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()
        if self.patrol_match_id and self.event_id != self.patrol_match.event_id:
            raise ValidationError("Misio devas aparteni al la sama evento kiel ĝia patrola kongruo.")


class Submission(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", "Recibida"
        REVIEWED = "reviewed", "Revisada"
        REJECTED = "rejected", "Rechazada"

    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name="submissions")
    patrol = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="submissions")
    submitted_by = models.CharField(max_length=160)
    payload = models.TextField()
    evidence_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["mission", "patrol"],
                name="unique_submission_per_mission_and_patrol",
            )
        ]

    def __str__(self) -> str:
        return f"{self.mission} - {self.patrol}"

    def clean(self):
        super().clean()
        if self.mission_id and self.patrol_id:
            valid_patrol_ids = {
                self.mission.patrol_match.patrol_a_id,
                self.mission.patrol_match.patrol_b_id,
            }
            if self.patrol_id not in valid_patrol_ids:
                raise ValidationError(
                    "Submeto povas veni nur de patrolo kiu apartenas al la misia kongruo."
                )
            if self.patrol.event_id != self.mission.event_id:
                raise ValidationError("Submeto devas uzi la saman eventon por misio kaj patrolo.")
