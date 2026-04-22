# Adds multiplier field to PointLog and CONSISTENCY_BONUS event type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scouting', '0010_rename_scouting_pay_patrol_idx_scouting_pa_patrol__23d8ba_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pointlog',
            name='multiplier',
            field=models.DecimalField(decimal_places=2, default=1.0, max_digits=4),
        ),
    ]
