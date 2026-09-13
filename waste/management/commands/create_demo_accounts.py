from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from waste.models import Profile


class Command(BaseCommand):
    help = "Creates one Admin (MENRO), one Staff, and one Barangay User account for testing."

    def handle(self, *args, **options):
        accounts = [
            {
                "username": "menro_admin",
                "password": "Admin@12345",
                "role": "admin",
                "barangay": None,
                "is_superuser": True,
                "is_staff": True,
            },
            {
                "username": "collection_staff",
                "password": "Staff@12345",
                "role": "staff",
                "barangay": None,
                "is_superuser": False,
                "is_staff": False,
            },
            {
                "username": "brgy_bagonglipunan",
                "password": "Brgy@12345",
                "role": "user",
                "barangay": "Bagong Lipunan",
                "is_superuser": False,
                "is_staff": False,
            },
        ]

        with transaction.atomic():
            for acc in accounts:
                user, created = User.objects.get_or_create(username=acc["username"])
                user.set_password(acc["password"])
                user.is_superuser = acc["is_superuser"]
                user.is_staff = acc["is_staff"]
                user.save()

                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role = acc["role"]
                profile.barangay = acc["barangay"]
                profile.save()

                status = "Created" if created else "Updated"
                self.stdout.write(self.style.SUCCESS(
                    f"{status}: {acc['username']} / {acc['password']} "
                    f"(role={acc['role']}, barangay={acc['barangay'] or '-'})"
                ))

        self.stdout.write(self.style.SUCCESS("\nDone. Use the credentials above to log in."))