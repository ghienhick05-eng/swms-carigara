import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Profile

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, role="admin" if instance.is_superuser else "staff")
    else:
        Profile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def notify_user_of_login(sender, request, user, **kwargs):
    """
    Sends a security notification to the user's email address every time
    their account is logged in to (self-service users and admins alike).
    Failures are logged but never block the login itself.
    """
    if not user.email:
        return

    login_time = timezone.localtime().strftime("%B %d, %Y at %I:%M %p")
    ip_address = request.META.get("REMOTE_ADDR", "unknown") if request else "unknown"

    subject = "New login to your SWMS account"
    message = (
        f"Hi {user.get_full_name() or user.username},\n\n"
        f"Your SWMS (Solid Waste Management System) account was just logged in to.\n\n"
        f"Time: {login_time}\n"
        f"IP address: {ip_address}\n\n"
        "If this was you, no action is needed. If you don't recognize this "
        "activity, please change your password immediately and contact the "
        "system administrator.\n\n"
        "- SWMS Carigara"
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send login notification email to %s", user.email)