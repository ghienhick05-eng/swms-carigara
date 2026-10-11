"""
Django settings for the Solid Waste Management System - Carigara, Leyte.
"""

import os
from pathlib import Path

import dj_database_url

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

# Render injects the public hostname of the service automatically.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if _render_host:
    ALLOWED_HOSTS.append(_render_host)
    CSRF_TRUSTED_ORIGINS = [f"https://{_render_host}"]
_extra_csrf = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = globals().get("CSRF_TRUSTED_ORIGINS", []) + [
    o.strip() for o in _extra_csrf.split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cloudinary_storage",
    "cloudinary",
    "waste",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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

# Uses DATABASE_URL (Postgres on Render) when set, else local SQLite.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
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
STATIC_ROOT = BASE_DIR / "staticfiles"
# Cloudinary: set CLOUDINARY_URL (cloudinary://API_KEY:API_SECRET@CLOUD_NAME) on
# Render to store uploads (avatars, photos, documents) off the server's disk.
# Without it, uploads fall back to local MEDIA_ROOT, so local dev needs no setup.
USE_CLOUDINARY = bool(os.environ.get("CLOUDINARY_URL"))
STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if USE_CLOUDINARY
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
# On Render, point MEDIA_ROOT at a persistent disk mount (e.g. /var/data/media).
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

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
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))  # never hang on SMTP
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", f"SWMS Carigara <{EMAIL_HOST_USER or 'noreply@localhost'}>"
)
# No credentials configured -> print emails to the console/logs instead of failing.
if not EMAIL_HOST_USER:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"



# --- MENRO Admin self-registration ----------------------------------------
# The Create Account page lets a MENRO Admin sign up with a personal email,
# but only if they know this code. Set it via the environment, e.g.
#   set MENRO_ADMIN_REGISTRATION_CODE=some-long-secret   (Windows)
# Leave it empty to disable MENRO Admin self-registration completely.
MENRO_ADMIN_REGISTRATION_CODE = os.environ.get("MENRO_ADMIN_REGISTRATION_CODE", "")

# --- Extra hardening, only enforced when DEBUG is off (i.e. production) --
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "True") == "True"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # Render terminates TLS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    # 1 year HSTS once you're confident HTTPS is solid everywhere.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0