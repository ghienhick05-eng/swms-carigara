"""
Django settings for the Solid Waste Management System - Carigara, Leyte.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Environment-driven config -------------------------------------------
# Locally, these fall back to safe dev defaults so `runserver` still works
# with zero setup. In production, set real values as environment variables
# (e.g. in your host's dashboard, systemd unit, or a .env file loaded by
# your process manager) and NEVER commit real secrets to source control.

# SECURITY WARNING: keep the secret key secret in production!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-do-not-use-in-production",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

# In production set DJANGO_ALLOWED_HOSTS="yourdomain.gov.ph,www.yourdomain.gov.ph"
_allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(",") if h.strip()] or (
    ["*"] if DEBUG else []
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "waste",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "swms.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "swms.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Allow authenticating with either the username or the email address.
# ModelBackend is kept as a fallback (e.g. for createsuperuser flows and
# the admin site) and is also what EmailOrUsernameBackend subclasses.
AUTHENTICATION_BACKENDS = [
    "waste.backends.EmailOrUsernameBackend",
]

# --- Email (used for login/security notifications) -----------------------
# Sends real emails via Gmail SMTP. Replace the placeholders below with your
# own Gmail address and a Gmail App Password (not your normal password) —
# generate one at https://myaccount.google.com/apppasswords
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = "ghienhick05@gmail.com"          # <-- put your Gmail address here
EMAIL_HOST_PASSWORD = "rhjkmbpcqxkkoydf"      # <-- put your Gmail App Password here
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = "SWMS Carigara <ghienhick05@gmail.com>"



# --- MENRO Admin self-registration ----------------------------------------
# The Create Account page lets a MENRO Admin sign up with a personal email,
# but only if they know this code. Set it via the environment, e.g.
#   set MENRO_ADMIN_REGISTRATION_CODE=some-long-secret   (Windows)
# Leave it empty to disable MENRO Admin self-registration completely.
MENRO_ADMIN_REGISTRATION_CODE = os.environ.get("MENRO_ADMIN_REGISTRATION_CODE", "10Ct9z6I7I0fxKJO3sn1BQ")

# --- Extra hardening, only enforced when DEBUG is off (i.e. production) --
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "True") == "True"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    # 1 year HSTS once you're confident HTTPS is solid everywhere.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"