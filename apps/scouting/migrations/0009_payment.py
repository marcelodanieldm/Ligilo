# Generated migration for Payment model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('scouting', '0008_points_gamification'),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_type', models.CharField(choices=[('stelo_pass', 'Stelo Pass - Acceso a Misiones'), ('premium_features', 'Características Premium'), ('training_boost', 'Impulso de Entrenamiento')], max_length=40)),
                ('amount_cents', models.PositiveIntegerField()),
                ('currency', models.CharField(default='USD', max_length=3)),
                ('status', models.CharField(choices=[('pending', 'Pendiente'), ('completed', 'Completado'), ('failed', 'Fallido'), ('refunded', 'Reembolsado')], default='pending', max_length=20)),
                ('payment_method', models.CharField(choices=[('stripe', 'Stripe'), ('paypal', 'PayPal')], max_length=20)),
                ('stripe_payment_intent_id', models.CharField(blank=True, max_length=200, unique=True)),
                ('paypal_transaction_id', models.CharField(blank=True, max_length=200, unique=True)),
                ('metadata', models.JSONField(default=dict)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('patrol', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='scouting.patrol')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['patrol', '-created_at'], name='scouting_payment_patrol_ca0f4b_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['status', '-created_at'], name='scouting_payment_status_ca0f4b_idx'),
        ),
    ]
