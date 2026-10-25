from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitudes', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitud',
            name='negocio',
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='inmueble',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='comprador_nombre',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='comprador_documento',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='comprador_correo',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='valor_venta',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='valor_credito',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='nuevo_credito',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='otp_hash',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='otp_vence',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='otp_intentos',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='decision_comentario',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='enviada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='cargada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='verificada_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='solicitud',
            name='firma_doc',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='solicitud',
            name='estado',
            field=models.CharField(
                choices=[
                    ('borrador', 'Borrador'),
                    ('pendiente_firma', 'Pendiente firma'),
                    ('firmada', 'Firmada'),
                    ('pendiente_aprobacion', 'Pendiente aprobación'),
                    ('aprobada', 'Aprobada'),
                    ('rechazada', 'Rechazada'),
                    ('cargada', 'Cargada en IngeMAX'),
                    ('verificada', 'Verificada contra IngeMAX'),
                ],
                default='borrador',
                max_length=30,
            ),
        ),
    ]
