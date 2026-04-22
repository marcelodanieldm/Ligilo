from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scouting", "0014_patrol_is_rover_moderator_patrolyoutubesubmission_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="patrol",
            name="mcer_notified_a1",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="patrol",
            name="mcer_notified_a2",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="patrol",
            name="mcer_notified_b1",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="patrol",
            name="sel_patch_prep_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
