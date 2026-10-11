from django.db import migrations, models


BARANGAY_CHOICES = [
    ("Bagong Lipunan", "Bagong Lipunan"),
    ("Balilit", "Balilit"),
    ("Barayong", "Barayong"),
    ("Barugohay Central", "Barugohay Central"),
    ("Barugohay Norte", "Barugohay Norte"),
    ("Barugohay Sur", "Barugohay Sur"),
    ("Baybay", "Baybay"),
    ("Binibihan", "Binibihan"),
    ("Bislig", "Bislig"),
    ("Caghalo", "Caghalo"),
    ("Camansi", "Camansi"),
    ("Canal", "Canal"),
    ("Candigahub", "Candigahub"),
    ("Canfabi", "Canfabi"),
    ("Canlampay", "Canlampay"),
    ("Cogon", "Cogon"),
    ("Cutay", "Cutay"),
    ("East Guindapunan", "East Guindapunan"),
    ("East Visoria", "East Visoria"),
    ("Hiluctogan", "Hiluctogan"),
    ("Jugaban", "Jugaban"),
    ("Libo", "Libo"),
    ("Lower Hiraan", "Lower Hiraan"),
    ("Lower Sogod", "Lower Sogod"),
    ("Macalpi", "Macalpi"),
    ("Manloy", "Manloy"),
    ("Nauguisan", "Nauguisan"),
    ("Paglaum", "Paglaum"),
    ("Pangna", "Pangna"),
    ("Parag-um", "Parag-um"),
    ("Parina", "Parina"),
    ("Piloro", "Piloro"),
    ("Ponong", "Ponong"),
    ("Rizal", "Rizal"),
    ("Sagkahan", "Sagkahan"),
    ("San Isidro", "San Isidro"),
    ("San Juan", "San Juan"),
    ("San Mateo", "San Mateo"),
    ("Sawang", "Sawang"),
    ("Sta. Fe", "Sta. Fe"),
    ("Tagak", "Tagak"),
    ("Tangnan", "Tangnan"),
    ("Tigbao", "Tigbao"),
    ("Tinaguban", "Tinaguban"),
    ("Upper Hiraan", "Upper Hiraan"),
    ("Upper Sogod", "Upper Sogod"),
    ("Uyawan", "Uyawan"),
    ("West Guindapunan", "West Guindapunan"),
    ("West Visoria", "West Visoria"),
]


def fix_existing_barangay_values(apps, schema_editor):
    """Some records used the old parenthesized/alternate spellings that no
    longer exist in the updated official barangay list. Remap them to their
    closest new equivalent so no record is left with an invalid choice."""
    RENAMES = {
        "Jugaban (Poblacion)": "Jugaban",
        "Ponong (Poblacion)": "Ponong",
        "Sawang (Poblacion)": "Sawang",
        "San Mateo (Poblacion)": "San Mateo",
        "Baybay (Poblacion)": "Baybay",
        "Rizal (Tagak East)": "Rizal",
        "Santa Fe": "Sta. Fe",
        "Naugisan": "Nauguisan",
        "Libong": "Libo",
        "Guindapunan East": "East Guindapunan",
        "Guindapunan West": "West Guindapunan",
    }
    Profile = apps.get_model("waste", "Profile")
    Collection = apps.get_model("waste", "Collection")
    Complaint = apps.get_model("waste", "Complaint")
    Accomplishment = apps.get_model("waste", "Accomplishment")
    ActionPlan = apps.get_model("waste", "ActionPlan")
    SCMAR = apps.get_model("waste", "SCMAR")
    RecurringCollectionSchedule = apps.get_model("waste", "RecurringCollectionSchedule")

    for model in [Profile, Collection, Complaint, Accomplishment, ActionPlan, SCMAR, RecurringCollectionSchedule]:
        for old_value, new_value in RENAMES.items():
            model.objects.filter(barangay=old_value).update(barangay=new_value)


def noop_reverse(apps, schema_editor):
    # Not reversible: the old/new name mapping is lossy (multiple old
    # spellings could collapse to the same new one).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("waste", "0020_remove_scmar_actions_taken_and_more"),
    ]

    operations = [
        migrations.RunPython(fix_existing_barangay_values, noop_reverse),
        migrations.AlterField(
            model_name="profile",
            name="barangay",
            field=models.CharField(blank=True, choices=BARANGAY_CHOICES, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name="collection",
            name="barangay",
            field=models.CharField(choices=BARANGAY_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="barangay",
            field=models.CharField(choices=BARANGAY_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name="accomplishment",
            name="barangay",
            field=models.CharField(blank=True, choices=BARANGAY_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name="actionplan",
            name="barangay",
            field=models.CharField(blank=True, choices=BARANGAY_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name="scmar",
            name="barangay",
            field=models.CharField(blank=True, choices=BARANGAY_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name="recurringcollectionschedule",
            name="barangay",
            field=models.CharField(choices=BARANGAY_CHOICES, max_length=50),
        ),
    ]