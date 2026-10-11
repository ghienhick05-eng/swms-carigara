import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import waste.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("waste", "0017_scmar"),
    ]

    operations = [
        migrations.RemoveField(model_name="scmar", name="created_by"),
        migrations.RemoveField(model_name="scmar", name="reviewed_by"),
        migrations.RemoveField(model_name="scmar", name="submitted_by"),
        migrations.DeleteModel(name="SCMAR"),
        migrations.CreateModel(
            name="SCMAR",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("barangay", models.CharField(blank=True, choices=[
                    ("Bagong Lipunan", "Bagong Lipunan"), ("Balilit", "Balilit"), ("Barayong", "Barayong"),
                    ("Barugohay Norte", "Barugohay Norte"), ("Barugohay Sur", "Barugohay Sur"),
                    ("Barugohay Central", "Barugohay Central"), ("Baybay (Poblacion)", "Baybay (Poblacion)"),
                    ("Binibihan", "Binibihan"), ("Bislig", "Bislig"), ("Caghalo", "Caghalo"),
                    ("Camansi", "Camansi"), ("Canal", "Canal"), ("Cogon", "Cogon"), ("Cutay", "Cutay"),
                    ("East Visoria", "East Visoria"), ("West Visoria", "West Visoria"),
                    ("Guindapunan East", "Guindapunan East"), ("Guindapunan West", "Guindapunan West"),
                    ("Hiluctogan", "Hiluctogan"), ("Jugaban (Poblacion)", "Jugaban (Poblacion)"),
                    ("Libong", "Libong"), ("Lower Hiraan", "Lower Hiraan"), ("Upper Hiraan", "Upper Hiraan"),
                    ("Macalpi", "Macalpi"), ("Manloy", "Manloy"), ("Naugisan", "Naugisan"),
                    ("Paglaum", "Paglaum"), ("Pangna", "Pangna"), ("Parag-um", "Parag-um"),
                    ("Parina", "Parina"), ("Piloro", "Piloro"), ("Ponong (Poblacion)", "Ponong (Poblacion)"),
                    ("Rizal (Tagak East)", "Rizal (Tagak East)"), ("Sagkahan", "Sagkahan"),
                    ("San Isidro", "San Isidro"), ("San Mateo (Poblacion)", "San Mateo (Poblacion)"),
                    ("Santa Fe", "Santa Fe"),
                ], max_length=50)),
                ("reporting_period", models.CharField(help_text="e.g. Q3 2026 or September 2026", max_length=50)),
                ("date_prepared", models.DateField(blank=True, null=True)),
                ("prepared_by", models.CharField(blank=True, help_text="Name of the person who prepared this report", max_length=100)),
                ("estimated_waste_generated", models.DecimalField(blank=True, decimal_places=2, help_text="Estimated waste generated (kg/day)", max_digits=10, null=True)),
                ("estimated_waste_collected", models.DecimalField(blank=True, decimal_places=2, help_text="Estimated waste collected (kg/day)", max_digits=10, null=True)),
                ("collection_frequency", models.CharField(blank=True, help_text="e.g. Twice a week", max_length=100)),
                ("collection_schedule", models.CharField(blank=True, help_text="e.g. Mon & Thu, 6:00 AM", max_length=150)),
                ("areas_covered", models.TextField(blank=True)),
                ("areas_not_covered", models.TextField(blank=True)),
                ("collection_personnel_count", models.PositiveIntegerField(blank=True, null=True)),
                ("collection_equipment", models.TextField(blank=True, help_text="Collection vehicle(s)/equipment available")),
                ("composition_biodegradable", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("composition_recyclable", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("composition_residual", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("composition_special_waste", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("recycling_activities", models.TextField(blank=True)),
                ("composting_activities", models.TextField(blank=True)),
                ("mrf_utilization", models.TextField(blank=True, help_text="How the Materials Recovery Facility is used")),
                ("final_disposal_method", models.CharField(blank=True, max_length=150)),
                ("main_problems", models.TextField(blank=True)),
                ("affected_areas", models.TextField(blank=True)),
                ("actions_taken", models.TextField(blank=True)),
                ("allocated_budget", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("amount_spent", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("budget_purpose", models.TextField(blank=True, help_text="What the budget was/will be used for")),
                ("recommended_action", models.TextField(blank=True)),
                ("priority", models.CharField(blank=True, choices=[("Low", "Low"), ("Medium", "Medium"), ("High", "High")], max_length=10)),
                ("expected_improvement", models.TextField(blank=True)),
                ("evidence_photo", models.ImageField(blank=True, help_text="Photo evidence (JPG, JPEG, or PNG).", null=True, upload_to="scmar_evidence/", validators=[waste.models.validate_supporting_image])),
                ("evidence_document", models.FileField(blank=True, help_text="Collection records or other supporting documents (PDF, DOC, or DOCX).", null=True, upload_to="scmar_reports/", validators=[waste.models.validate_report_file])),
                ("status", models.CharField(choices=[
                    ("Draft", "Draft"), ("Submitted", "Submitted"), ("Under Review", "Under Review"),
                    ("Returned for Revision", "Returned for Revision"), ("Approved", "Approved"),
                ], default="Draft", max_length=25)),
                ("date_created", models.DateTimeField(auto_now_add=True)),
                ("date_updated", models.DateTimeField(auto_now=True)),
                ("submission_date", models.DateTimeField(blank=True, null=True)),
                ("review_date", models.DateTimeField(blank=True, null=True)),
                ("review_remarks", models.TextField(blank=True, help_text="MENRO Admin's remarks for the Barangay (required when returning for revision).")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scmars_created", to=settings.AUTH_USER_MODEL)),
                ("submitted_by", models.ForeignKey(blank=True, help_text="The Barangay user who submitted this SCMAR to MENRO Admin.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scmars_submitted", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, help_text="MENRO Admin who reviewed this submission.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scmars_reviewed", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "SCMAR",
                "verbose_name_plural": "SCMARs",
                "ordering": ["-date_created"],
            },
        ),
    ]

   