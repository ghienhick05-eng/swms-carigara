import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("waste", "0024_reminderlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="recurringcollectionschedule",
            name="frequency",
            field=models.CharField(
                choices=[("Weekly", "Weekly"), ("Monthly", "Monthly")],
                default="Monthly",
                help_text="Weekly = every week on the chosen weekday. Monthly = once a month on the chosen day.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="recurringcollectionschedule",
            name="day_of_week",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
                         (4, "Friday"), (5, "Saturday"), (6, "Sunday")],
                help_text="Weekday for Weekly schedules.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="recurringcollectionschedule",
            name="day_of_month",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="Day of the month for Monthly schedules (1-28, to stay valid in every month).",
            ),
        ),
        migrations.AlterField(
            model_name="recurringcollectionschedule",
            name="last_generated_for",
            field=models.DateField(
                blank=True,
                help_text="Monthly schedules: the month (1st of month stored) this schedule last auto-created a Collection for.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="collection",
            name="frequency",
            field=models.CharField(
                blank=True,
                choices=[("Weekly", "Weekly"), ("Monthly", "Monthly")],
                default="",
                help_text="Weekly or Monthly. Filled in automatically when the collection comes from a recurring schedule.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="collection",
            name="schedule",
            field=models.ForeignKey(
                blank=True,
                help_text="The recurring schedule that auto-created this collection (if any).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="collections",
                to="waste.recurringcollectionschedule",
            ),
        ),
    ]