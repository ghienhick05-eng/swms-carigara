from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("waste", "0025_weekly_monthly_collection_schedules"),
    ]

    operations = [
        migrations.AddField(
            model_name="collection",
            name="notes",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Optional notes from the barangay about this collection.",
            ),
        ),
    ]