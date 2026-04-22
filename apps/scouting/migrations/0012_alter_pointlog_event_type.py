# Adds CONSISTENCY_BONUS choice to PointLog.event_type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scouting', '0011_pointlog_multiplier'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pointlog',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('text_validated', 'Mensaje de texto validado'),
                    ('audio_validated', 'Audio validado'),
                    ('youtube_mission', 'Video de YouTube (Mision cumplida)'),
                    ('consistency_bonus', 'Bono de Consistencia (3 audios en 24h)'),
                ],
                max_length=40,
            ),
        ),
    ]
