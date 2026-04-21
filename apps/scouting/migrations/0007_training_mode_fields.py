from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scouting", "0006_matchcelebrationevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="patrol",
            name="training_points",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="patrolmatch",
            name="is_training",
            field=models.BooleanField(default=False),
        ),
    ]
