from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("waste", "0011_profile_email_verified_loginverification"),
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
        migrations.AlterField(
            model_name="actionplan",
            name="target_date",
            field=models.DateField(
                blank=True,
                help_text="Due date / deadline for this action plan report. Set by the MENRO Admin only.",
                null=True,
            ),
        ),
    ]