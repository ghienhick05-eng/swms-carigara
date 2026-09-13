from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("waste", "0013_collection_status_scheduling"),
    ]

    operations = [
        migrations.AddField(
            model_name="actionplan",
            name="budget",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Estimated budget for this activity, submitted by the barangay (PHP).",
                max_digits=12,
                null=True,
            ),
        ),
    ]
