from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("scouting", "0005_auditlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="MatchCelebrationEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("event_name", models.CharField(default="match_celebrated", max_length=40)),
                ("telegram_chat_id", models.BigIntegerField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                ("first_interaction_at", models.DateTimeField(blank=True, null=True)),
                ("first_interaction_seconds", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "patrol",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="celebration_events",
                        to="scouting.patrol",
                    ),
                ),
                (
                    "patrol_match",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="celebration_events",
                        to="scouting.patrolmatch",
                    ),
                ),
            ],
            options={
                "ordering": ["-sent_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="matchcelebrationevent",
            constraint=models.UniqueConstraint(
                fields=("patrol_match", "patrol"),
                name="unique_match_celebration_per_patrol",
            ),
        ),
    ]
