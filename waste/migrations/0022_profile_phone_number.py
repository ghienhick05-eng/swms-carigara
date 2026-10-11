from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("waste", "0021_update_barangay_choices"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="phone_number",
            field=models.CharField(
                blank=True,
                max_length=20,
                null=True,
                help_text="Optional contact number, e.g. 09171234567.",
            ),
        ),
    ]