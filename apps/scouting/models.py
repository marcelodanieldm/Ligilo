import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


User = get_user_model()


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
    invitation_token = models.UUIDField(default=uuid.uuid4, blank=True, null=True, unique=True)
    training_points = models.PositiveIntegerField(default=0)
    sel_points = models.PositiveIntegerField(default=0)
    member_count = models.PositiveSmallIntegerField(default=1)
    onboarding_step = models.PositiveSmallIntegerField(default=0)
    onboarding_completed_at = models.DateTimeField(blank=True, null=True)
    telegram_node_token = models.UUIDField(default=uuid.uuid4, blank=True, null=True, unique=True)
    telegram_node_link = models.URLField(blank=True)
    telegram_node_active = models.BooleanField(default=False)
    leadership_project_validated = models.BooleanField(default=False)
    is_rover_moderator = models.BooleanField(default=False)
    mcer_notified_a1 = models.BooleanField(default=False)
    mcer_notified_a2 = models.BooleanField(default=False)
    mcer_notified_b1 = models.BooleanField(default=False)
    sel_patch_prep_notified_at = models.DateTimeField(blank=True, null=True)
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
    is_training = models.BooleanField(default=False)
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


class PatrolInterest(models.Model):
    patrol = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="interests")
    tag = models.CharField(max_length=40)

    class Meta:
        ordering = ["tag"]
        constraints = [
            models.UniqueConstraint(fields=["patrol", "tag"], name="unique_patrol_interest_tag"),
        ]

    def __str__(self) -> str:
        return f"{self.patrol.name}:{self.tag}"


class PatrolMember(models.Model):
    class Gender(models.TextChoices):
        FEMALE = "female", "Femenino"
        MALE = "male", "Masculino"
        NON_BINARY = "non_binary", "No binario"
        PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefiero no decir"

    class InitialLevel(models.TextChoices):
        A1 = "A1", "A1"
        A2 = "A2", "A2"
        B1 = "B1", "B1"
        B2 = "B2", "B2"

    patrol = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="members")
    full_name = models.CharField(max_length=160)
    alias = models.CharField(max_length=80, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices)
    birth_date = models.DateField()
    initial_level = models.CharField(max_length=2, choices=InitialLevel.choices)
    telegram_user_id = models.BigIntegerField(blank=True, null=True)
    joined_node_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]
        constraints = [
            models.UniqueConstraint(fields=["patrol", "full_name"], name="unique_member_name_per_patrol"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.patrol.name})"

    @property
    def age(self) -> int:
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    def clean(self):
        super().clean()
        age = self.age
        if age < 11 or age > 25:
            raise ValidationError(
                {"birth_date": "La edad del miembro debe estar entre 11 y 25 años."}
            )


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


class AuditLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="safe_from_harm_audit_logs",
    )
    user_identifier = models.CharField(max_length=120, blank=True)
    input_text = models.TextField()
    ai_response = models.JSONField(default=dict)
    flagged_status = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        identity = self.user_identifier or "anonymous"
        return f"AuditLog({identity}, flagged={self.flagged_status})"


class MatchCelebrationEvent(models.Model):
    event_name = models.CharField(max_length=40, default="match_celebrated")
    patrol_match = models.ForeignKey(
        PatrolMatch,
        on_delete=models.CASCADE,
        related_name="celebration_events",
    )
    patrol = models.ForeignKey(
        Patrol,
        on_delete=models.CASCADE,
        related_name="celebration_events",
    )
    telegram_chat_id = models.BigIntegerField(blank=True, null=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    first_interaction_at = models.DateTimeField(blank=True, null=True)
    first_interaction_seconds = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["patrol_match", "patrol"],
                name="unique_match_celebration_per_patrol",
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_name}::{self.patrol}"


class PointLog(models.Model):
    class EventType(models.TextChoices):
        TEXT_VALIDATED = "text_validated", "Mensaje de texto validado"
        AUDIO_VALIDATED = "audio_validated", "Audio validado"
        YOUTUBE_MISSION = "youtube_mission", "Video de YouTube (Mision cumplida)"
        CONSISTENCY_BONUS = "consistency_bonus", "Bono de Consistencia (3 audios en 24h)"

    patrol = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="point_logs")
    event_type = models.CharField(max_length=40, choices=EventType.choices)
    points = models.PositiveIntegerField()
    external_ref = models.CharField(max_length=120, blank=True)
    multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.00)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"PointLog({self.patrol_id}, {self.event_type}, +{self.points})"


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        COMPLETED = "completed", "Completado"
        FAILED = "failed", "Fallido"
        REFUNDED = "refunded", "Reembolsado"

    class PaymentMethod(models.TextChoices):
        STRIPE = "stripe", "Stripe"
        PAYPAL = "paypal", "PayPal"

    class ProductType(models.TextChoices):
        STELO_PASS = "stelo_pass", "Stelo Pass - Acceso a Misiones"
        PREMIUM_FEATURES = "premium_features", "Características Premium"
        TRAINING_BOOST = "training_boost", "Impulso de Entrenamiento"

    patrol = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="payments")
    product_type = models.CharField(max_length=40, choices=ProductType.choices)
    amount_cents = models.PositiveIntegerField()  # Amount in cents (USD)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    
    # Payment provider references
    stripe_payment_intent_id = models.CharField(max_length=200, blank=True, unique=True)
    paypal_transaction_id = models.CharField(max_length=200, blank=True, unique=True)
    
    # Metadata
    metadata = models.JSONField(default=dict)  # Store additional info (product details, user email, etc.)
    error_message = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patrol", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        amount_usd = self.amount_cents / 100
        return f"Payment({self.patrol.name}, {self.product_type}, ${amount_usd}, {self.status})"

    def clean(self):
        super().clean()
        if self.status == self.Status.COMPLETED:
            if not self.stripe_payment_intent_id and not self.paypal_transaction_id:
                raise ValidationError(
                    "Pagos completados deben tener una referencia de transaccion."
                )


class SteloCertification(models.Model):
    """
    Tracks issued Stelo-Meter certifications.
    One record per patrol (unique), regenerated on milestone upgrades.
    """

    THRESHOLD_BRONZE = 500
    THRESHOLD_SILVER = 1000
    THRESHOLD_GOLD = 2000

    class Tier(models.TextChoices):
        BRONZE = "bronze", "Bronce (500 pts)"
        SILVER = "silver", "Plata (1000 pts)"
        GOLD = "gold", "Oro (2000 pts)"

    patrol = models.OneToOneField(
        Patrol, on_delete=models.CASCADE, related_name="stelo_certification"
    )
    tier = models.CharField(max_length=10, choices=Tier.choices)
    points_at_issue = models.PositiveIntegerField()
    certification_code = models.CharField(max_length=60, unique=True)
    jwt_token = models.TextField()  # Signed JWT embedded in QR
    qr_png_b64 = models.TextField(blank=True)  # Base64-encoded PNG for offline display
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["certification_code"], name="scouting_st_certifi_476378_idx"),
            models.Index(fields=["patrol", "-issued_at"], name="scouting_st_patrol__94728f_idx"),
        ]

    def __str__(self) -> str:
        return f"SteloCert({self.patrol.name}, {self.tier}, {self.certification_code})"

    @classmethod
    def tier_for_points(cls, points: int) -> str | None:
        if points >= cls.THRESHOLD_GOLD:
            return cls.Tier.GOLD
        if points >= cls.THRESHOLD_SILVER:
            return cls.Tier.SILVER
        if points >= cls.THRESHOLD_BRONZE:
            return cls.Tier.BRONZE
        return None


class PatrolYouTubeSubmission(models.Model):
    """
    Sprint 3: Stores YouTube video submissions for final challenge.
    Tracks metadata validation and AI audit results.
    """
    class ValidationStatus(models.TextChoices):
        PENDING = "pending", "Esperando validación"
        VALID = "valid", "Validado"
        INVALID = "invalid", "No válido"
        REJECTED = "rejected", "Rechazado"
    
    class AuditStatus(models.TextChoices):
        PENDING = "pending", "Auditando"
        PASSED = "passed", "Pasó auditoría"
        FAILED = "failed", "Falló auditoría"
        MANUAL_REVIEW = "manual_review", "Revisión manual"

    class LeaderApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pendiente de aprobación"
        APPROVED = "approved", "Siempre Listos (Aprobado)"
        REJECTED = "rejected", "Rechazado por líder"
    
    patrol = models.OneToOneField(
        Patrol, on_delete=models.CASCADE, related_name="youtube_submission"
    )
    youtube_url = models.URLField()
    video_id = models.CharField(max_length=20, unique=True)
    embed_url = models.URLField(blank=True)
    
    # Validation (metadata QA)
    validation_status = models.CharField(
        max_length=20,
        choices=ValidationStatus.choices,
        default=ValidationStatus.PENDING
    )
    validation_errors = models.JSONField(default=list, blank=True)
    validation_warnings = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # title, duration, privacy, tags, etc.
    
    # Audit (Gemini AI analysis)
    audit_status = models.CharField(
        max_length=20,
        choices=AuditStatus.choices,
        default=AuditStatus.PENDING
    )
    audit_errors = models.JSONField(default=list, blank=True)
    audit_findings = models.JSONField(default=dict, blank=True)  # participants, teamwork, content_match, etc.
    
    # Final result
    leader_approval_status = models.CharField(
        max_length=20,
        choices=LeaderApprovalStatus.choices,
        default=LeaderApprovalStatus.PENDING,
    )
    leader_approved_at = models.DateTimeField(blank=True, null=True)
    leader_approval_notes = models.TextField(blank=True)
    leader_notification_sent_at = models.DateTimeField(blank=True, null=True)
    final_approved_at = models.DateTimeField(blank=True, null=True)
    approved_for_wall_of_fame = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    validated_at = models.DateTimeField(blank=True, null=True)
    audited_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        ordering = ["-submitted_at"]
    
    def __str__(self) -> str:
        return f"YouTubeSubmission({self.patrol.name}, {self.validation_status})"


class RoverIncident(models.Model):
    """
    Priority moderation incident reported by a Rover (18+) patrol role.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        IN_REVIEW = "in_review", "En revisión"
        RESOLVED = "resolved", "Resuelta"

    patrol = models.ForeignKey(Patrol, on_delete=models.CASCADE, related_name="rover_incidents")
    reported_by_chat_id = models.BigIntegerField(blank=True, null=True)
    description = models.TextField()
    priority = models.CharField(max_length=12, default="high")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["patrol", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"RoverIncident({self.patrol.name}, {self.status})"


class MCERCertificate(models.Model):
    """
    MCER Linguistic Excellence Certificate (Atestilo).
    Tracks scout patrol progression through MCER levels (A1/A2/B1/B2).
    """
    
    class MCERLevel(models.TextChoices):
        A1 = "A1", "A1 Malkovranto (0-1,000 pts)"
        A2 = "A2", "A2 Vojtrovanto (1,001-3,000 pts)"
        B1 = "B1", "B1 Esploristo (3,001-6,000 pts)"
        B2 = "B2", "B2 Gvidanto (6,001+ pts)"
    
    patrol = models.ForeignKey(
        Patrol, on_delete=models.CASCADE, related_name="mcer_certificates"
    )
    sister_patrol = models.ForeignKey(
        Patrol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mcer_certificates_as_sister",
    )
    mcer_level = models.CharField(max_length=2, choices=MCERLevel.choices)
    points_at_issue = models.PositiveIntegerField()
    certification_code = models.CharField(max_length=60, unique=True)
    qr_png_b64 = models.TextField(blank=True)
    pdf_file_path = models.CharField(max_length=255, blank=True)
    
    # Preview tracking
    preview_requested_count = models.PositiveIntegerField(default=0)
    last_preview_requested_at = models.DateTimeField(blank=True, null=True)
    
    # Leader notification
    leader_notified_at = models.DateTimeField(blank=True, null=True)
    
    # Timestamps
    issued_at = models.DateTimeField(auto_now_add=True)
    match_start_date = models.DateField(blank=True, null=True)
    
    class Meta:
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["patrol", "-issued_at"]),
            models.Index(fields=["certification_code"]),
        ]
    
    def __str__(self) -> str:
        return f"MCERCert({self.patrol.name}, {self.mcer_level}, {self.certification_code})"
    
    def is_preview_mode(self) -> bool:
        """Check if certificate should show watermark (< 80% of B1)."""
        # B1 threshold is 3,001 points
        # 80% of B1 = 0.8 * 3001 = 2,400.8 ≈ 2,401 points
        return self.points_at_issue < 2401
