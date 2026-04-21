import uuid

from django.db import migrations, models


def clear_non_uuid_tokens(apps, schema_editor):
    Patrol = apps.get_model("scouting", "Patrol")
    Patrol.objects.exclude(invitation_token__isnull=True).update(invitation_token=None)


class Migration(migrations.Migration):
    dependencies = [
        ("scouting", "0002_patrol_telegram_fields"),
    ]

    operations = [
        migrations.RunPython(clear_non_uuid_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="patrol",
            name="invitation_token",
            field=models.UUIDField(blank=True, default=uuid.uuid4, null=True, unique=True),
        ),
    ]
