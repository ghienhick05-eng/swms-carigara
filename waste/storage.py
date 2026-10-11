import os

from django.core.files.storage import FileSystemStorage


def _clean(value):
    return (value or "").strip().strip("\"'").strip()


def clean_cloudinary_url():
    """Return CLOUDINARY_URL, tolerating a badly pasted value.

    Render env vars are often pasted with quotes, spaces or a leading
    "CLOUDINARY_URL=", which makes the cloudinary library raise at import time
    (a 500 on every page).
    """
    raw = os.environ.get("CLOUDINARY_URL", "")
    url = _clean(raw)
    if url.upper().startswith("CLOUDINARY_URL="):
        url = _clean(url.split("=", 1)[1])
    if url != raw:
        if url:
            os.environ["CLOUDINARY_URL"] = url
        else:
            os.environ.pop("CLOUDINARY_URL", None)
    return url


def cloudinary_credentials():
    """Credentials from the three separate variables, or None if any is missing.

    CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET.
    """
    name = _clean(os.environ.get("CLOUDINARY_CLOUD_NAME"))
    key = _clean(os.environ.get("CLOUDINARY_API_KEY"))
    secret = _clean(os.environ.get("CLOUDINARY_API_SECRET"))
    if name and key and secret:
        return {"CLOUD_NAME": name, "API_KEY": key, "API_SECRET": secret}
    return None


def cloudinary_enabled():
    return bool(cloudinary_credentials() or clean_cloudinary_url())


def document_storage():
    """Storage for PDF/DOC/DOCX uploads.

    Cloudinary stores non-image files as "raw" resources, so documents need a
    different storage class from photos. Falls back to the normal local
    storage when Cloudinary isn't configured.
    """
    if cloudinary_enabled():
        from .cloudinary_storages import SafeRawMediaCloudinaryStorage
        return SafeRawMediaCloudinaryStorage()
    return FileSystemStorage()