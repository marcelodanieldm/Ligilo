from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("scouting", "0007_training_mode_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="patrol",
            name="sel_points",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="PointLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("text_validated", "Mensaje de texto validado"),
                            ("audio_validated", "Audio validado"),
                            ("youtube_mission", "Video de YouTube (Mision cumplida)"),
                        ],
                        max_length=40,
                    ),
                ),
                ("points", models.PositiveIntegerField()),
                ("external_ref", models.CharField(blank=True, max_length=120)),
                ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "patrol",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="point_logs", to="scouting.patrol"),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
