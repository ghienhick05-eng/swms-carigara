import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('waste', '0003_accomplishment'),
    ]

    operations = [
        migrations.CreateModel(
            name='ActionPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(help_text='e.g. Establishment of MRF, HAPAG, Desilting, BARKADA Day', max_length=150)),
                ('barangay', models.CharField(blank=True, choices=[('Bagong Lipunan', 'Bagong Lipunan'), ('Balilit', 'Balilit'), ('Barayong', 'Barayong'), ('Barugohay Norte', 'Barugohay Norte'), ('Barugohay Sur', 'Barugohay Sur'), ('Barugohay Central', 'Barugohay Central'), ('Baybay (Poblacion)', 'Baybay (Poblacion)'), ('Binibihan', 'Binibihan'), ('Bislig', 'Bislig'), ('Caghalo', 'Caghalo'), ('Camansi', 'Camansin'), ('Canal', 'Canal'), ('Cogon', 'Cogon'), ('Cutay', 'Cutay'), ('East Visoria', 'East Visoria'), ('West Visoria', 'West Visoria'), ('Guindapunan East', 'Guindapunan East'), ('Guindapunan West', 'Guindapunan West'), ('Hiluctogan', 'Hiluctogan'), ('Jugaban (Poblacion)', 'Jugaban (Poblacion)'), ('Libong', 'Libong'), ('Lower Hiraan', 'Lower Hiraan'), ('Upper Hiraan', 'Upper Hiraan'), ('Macalpi', 'Macalpi'), ('Manloy', 'Manloy'), ('Naugisan', 'Naugisan'), ('Paglaum', 'Paglaum'), ('Pangna', 'Pangna'), ('Parag-um', 'Parag-um'), ('Parina', 'Parina'), ('Piloro', 'Piloro'), ('Ponong (Poblacion)', 'Ponong (Poblacion)'), ('Rizal (Tagak East)', 'Rizal (Tagak East)'), ('Sagkahan', 'Sagkahan'), ('San Isidro', 'San Isidro'), ('San Mateo (Poblacion)', 'San Mateo (Poblacion)'), ('Santa Fe', 'Santa Fe'), ('Sawang (Poblacion)', 'Sawang (Poblacion)'), ('Tagak', 'Tagak'), ('Tangnan', 'Tangnan'), ('Tigbao', 'Tigbao'), ('Tinaguban', 'Tinaguban'), ('Uyawan', 'Uyawan')], max_length=50)),
                ('description', models.TextField(blank=True)),
                ('target_date', models.DateField(help_text='Target date of implementation')),
                ('status', models.CharField(choices=[('Planned', 'Planned'), ('Ongoing', 'Ongoing'), ('Completed', 'Completed')], default='Planned', max_length=15)),
                ('responsible_person', models.CharField(blank=True, help_text='Person or office in-charge', max_length=100)),
                ('date_created', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['target_date'],
            },
        ),
    ]
