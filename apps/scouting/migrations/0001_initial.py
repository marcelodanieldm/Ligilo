from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("slug", models.SlugField(max_length=200, unique=True)),
                ("host_city", models.CharField(max_length=120)),
                ("host_country", models.CharField(max_length=120)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("is_active", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-starts_at", "name"]},
        ),
        migrations.CreateModel(
            name="Patrol",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("delegation_name", models.CharField(max_length=160)),
                ("country_code", models.CharField(max_length=2)),
                ("country_name", models.CharField(max_length=120)),
                ("official_language_code", models.CharField(max_length=8)),
                ("official_language_name", models.CharField(max_length=120)),
                ("leader_name", models.CharField(max_length=160)),
                ("leader_email", models.EmailField(blank=True, max_length=254)),
                ("member_count", models.PositiveSmallIntegerField(default=1)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "event",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="patrols", to="scouting.event"),
                ),
            ],
            options={"ordering": ["event", "delegation_name", "name"]},
        ),
        migrations.CreateModel(
            name="PatrolMatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[("proposed", "Propuesto"), ("active", "Activo"), ("closed", "Cerrado")],
                        default="proposed",
                        max_length=20,
                    ),
                ),
                ("matched_at", models.DateTimeField(auto_now_add=True)),
                (
                    "event",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="matches", to="scouting.event"),
                ),
                (
                    "patrol_a",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="matches_as_a", to="scouting.patrol"),
                ),
                (
                    "patrol_b",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="matches_as_b", to="scouting.patrol"),
                ),
            ],
            options={"ordering": ["event", "-matched_at"]},
        ),
        migrations.CreateModel(
            name="Mission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("briefing", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Borrador"), ("published", "Publicada"), ("closed", "Cerrada")],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("opens_at", models.DateTimeField()),
                ("due_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "event",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="missions", to="scouting.event"),
                ),
                (
                    "patrol_match",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="missions", to="scouting.patrolmatch"),
                ),
            ],
            options={"ordering": ["event", "due_at", "title"]},
        ),
        migrations.CreateModel(
            name="Submission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("submitted_by", models.CharField(max_length=160)),
                ("payload", models.TextField()),
                ("evidence_url", models.URLField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("received", "Recibida"), ("reviewed", "Revisada"), ("rejected", "Rechazada")],
                        default="received",
                        max_length=20,
                    ),
                ),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "mission",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="scouting.mission"),
                ),
                (
                    "patrol",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="scouting.patrol"),
                ),
            ],
            options={"ordering": ["-submitted_at"]},
        ),
        migrations.AddConstraint(
            model_name="patrol",
            constraint=models.UniqueConstraint(fields=("event", "official_language_code"), name="unique_official_language_per_event"),
        ),
        migrations.AddConstraint(
            model_name="patrol",
            constraint=models.UniqueConstraint(fields=("event", "delegation_name", "name"), name="unique_patrol_per_delegation"),
        ),
        migrations.AddConstraint(
            model_name="patrol",
            constraint=models.CheckConstraint(condition=models.Q(("member_count__gte", 1)), name="member_count_gte_1"),
        ),
        migrations.AddConstraint(
            model_name="patrolmatch",
            constraint=models.UniqueConstraint(fields=("event", "patrol_a", "patrol_b"), name="unique_patrol_match_ordered"),
        ),
        migrations.AddConstraint(
            model_name="patrolmatch",
            constraint=models.CheckConstraint(condition=models.Q(models.Q(("patrol_a", models.F("patrol_b")), _negated=True)), name="patrols_must_be_different"),
        ),
        migrations.AddConstraint(
            model_name="submission",
            constraint=models.UniqueConstraint(fields=("mission", "patrol"), name="unique_submission_per_mission_and_patrol"),
        ),
    ]
