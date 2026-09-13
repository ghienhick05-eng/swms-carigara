from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Assigns a placeholder @swms-carigara.local email address to any "
        "existing user who doesn't already have one, so email login and "
        "login notifications work for accounts created before email was "
        "required. Existing emails are never overwritten."
    )

    def handle(self, *args, **options):
        updated = 0
        for user in User.objects.filter(email=""):
            placeholder = f"{user.username}@swms-carigara.local"
            # Guard against an unlikely collision with a real email.
            if User.objects.filter(email__iexact=placeholder).exclude(pk=user.pk).exists():
                placeholder = f"{user.username}.{user.pk}@swms-carigara.local"
            user.email = placeholder
            user.save(update_fields=["email"])
            updated += 1
            self.stdout.write(self.style.SUCCESS(f"{user.username} -> {placeholder}"))

        if updated == 0:
            self.stdout.write("No users needed a placeholder email.")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nDone. Assigned placeholder emails to {updated} account(s). "
                "Update these to real addresses when known."
            ))