import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from waste.models import Profile


class Command(BaseCommand):
    help = (
        "Creates or updates the MENRO Admin superuser from environment variables "
        "(MENRO_ADMIN_USERNAME, MENRO_ADMIN_EMAIL, MENRO_ADMIN_PASSWORD). "
        "Safe to run on every deploy."
    )

    def handle(self, *args, **options):
        username = os.environ.get("MENRO_ADMIN_USERNAME", "menroadmin").strip()
        email = os.environ.get("MENRO_ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("MENRO_ADMIN_PASSWORD", "")

        # Not configured: skip quietly so local builds don't fail.
        if not email or not password:
            self.stdout.write("MENRO_ADMIN_EMAIL / MENRO_ADMIN_PASSWORD not set. Skipping admin creation.")
            return

        clash = User.objects.filter(email__iexact=email).exclude(username=username).first()
        if clash:
            raise CommandError(f"Email {email} already belongs to another user ({clash.username}).")

        with transaction.atomic():
            user, created = User.objects.get_or_create(username=username)
            user.email = email
            user.is_superuser = True
            user.is_staff = True
            user.is_active = True
            user.set_password(password)
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = "admin"
            profile.barangay = None
            profile.email_verified = True
            profile.save()

        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} MENRO admin superuser '{username}' ({email})."
        ))