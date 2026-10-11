from django.db import migrations


class Migration(migrations.Migration):
    """No-op: the ActionPlan.budget field is already added by 0012.

    This migration originally duplicated that AddField, which made a fresh
    `migrate` fail with "duplicate column name: budget". It is kept (empty) so
    existing databases that recorded it stay consistent.
    """

    dependencies = [
        ("waste", "0013_collection_status_scheduling"),
    ]

    operations = []