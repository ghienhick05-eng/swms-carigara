import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _backfill_status_for_existing_records(apps, schema_editor):
    Collection = apps.get_model("waste", "Collection")
    Collection.objects.filter(weight_kg__isnull=False).update(status="Completed")


class Migration(migrations.Migration):

    dependencies = [
        ('waste', '0012_collection_scheduling_monitoring'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='collection',
            options={'ordering': ['-scheduled_date', '-date_collected']},
        ),
        migrations.AddField(
            model_name='collection',
            name='scheduled_date',
            field=models.DateTimeField(blank=True, help_text='When this collection is scheduled to happen.', null=True),
        ),
        migrations.AddField(
            model_name='collection',
            name='status',
            field=models.CharField(choices=[('Scheduled', 'Scheduled'), ('Ongoing', 'Ongoing'), ('Completed', 'Completed')], default='Scheduled', max_length=15),
        ),
        migrations.AddField(
            model_name='collection',
            name='updated_by',
            field=models.ForeignKey(blank=True, help_text='Barangay user who last updated the monitoring status.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collections_monitored', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='collection',
            name='date_collected',
            field=models.DateTimeField(blank=True, help_text='Set automatically once the collection is marked Completed.', null=True),
        ),
        migrations.AlterField(
            model_name='collection',
            name='logged_by',
            field=models.ForeignKey(blank=True, help_text='Admin who scheduled this collection.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collections_scheduled', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='collection',
            name='weight_kg',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Actual weight collected. Filled in once the collection is marked Completed.', max_digits=8, null=True),
        ),
        migrations.RunPython(_backfill_status_for_existing_records, migrations.RunPython.noop),
    ]