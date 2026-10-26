from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("solicitudes", "0003_flujo_completo"),
    ]

    operations = [
        migrations.AddField(
            model_name="solicitud",
            name="rechazo_observacion",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
