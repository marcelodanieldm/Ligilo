from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scouting", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="patrol",
            name="invitation_token",
            field=models.CharField(blank=True, max_length=32, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="patrol",
            name="telegram_chat_id",
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
    ]
