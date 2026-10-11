"""Django email backend that sends through Brevo's HTTPS API.

Render's free plan blocks outgoing SMTP (Gmail etc.), so mail is sent over
HTTPS instead. Every existing send_mail() call keeps working unchanged.

Env vars:
    BREVO_API_KEY       your Brevo API key (starts with "xkeysib-")
    DEFAULT_FROM_EMAIL  must be a sender verified in Brevo, e.g.
                        "SWMS Carigara <you@gmail.com>"
"""
import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

API_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        api_key = getattr(settings, "BREVO_API_KEY", "")
        if not api_key:
            if not self.fail_silently:
                raise RuntimeError("BREVO_API_KEY is not set.")
            return 0

        sent = 0
        for message in email_messages:
            name, address = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
            sender = {"email": address}
            if name:
                sender["name"] = name
            payload = {
                "sender": sender,
                "to": [{"email": r} for r in message.to],
                "subject": message.subject,
                "textContent": message.body,
            }
            for content, mimetype in getattr(message, "alternatives", []):
                if mimetype == "text/html":
                    payload["htmlContent"] = content
            try:
                resp = requests.post(
                    API_URL,
                    json=payload,
                    headers={"api-key": api_key, "accept": "application/json"},
                    timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
                )
                resp.raise_for_status()
                sent += 1
            except Exception:
                logger.exception("Brevo send failed for %s", message.to)
                if not self.fail_silently:
                    raise
        return sent