# Adds SteloCertification model

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scouting', '0012_alter_pointlog_event_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='SteloCertification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tier', models.CharField(
                    choices=[
                        ('bronze', 'Bronce (500 pts)'),
                        ('silver', 'Plata (1000 pts)'),
                        ('gold', 'Oro (2000 pts)'),
                    ],
                    max_length=10,
                )),
                ('points_at_issue', models.PositiveIntegerField()),
                ('certification_code', models.CharField(max_length=60, unique=True)),
                ('jwt_token', models.TextField()),
                ('qr_png_b64', models.TextField(blank=True)),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('revoked', models.BooleanField(default=False)),
                ('patrol', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='stelo_certification',
                    to='scouting.patrol',
                )),
            ],
            options={
                'ordering': ['-issued_at'],
            },
        ),
        migrations.AddIndex(
            model_name='stelocertification',
            index=models.Index(fields=['certification_code'], name='scouting_st_certifi_476378_idx'),
        ),
        migrations.AddIndex(
            model_name='stelocertification',
            index=models.Index(fields=['patrol', '-issued_at'], name='scouting_st_patrol__94728f_idx'),
        ),
    ]
