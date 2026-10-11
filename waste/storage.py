import os

from django.core.files.storage import FileSystemStorage


def clean_cloudinary_url():
    """Return CLOUDINARY_URL, tolerating a badly pasted value.

    Render env vars are often pasted with quotes, spaces or a leading
    "CLOUDINARY_URL=", which makes the cloudinary library raise at import time
    (a 500 on every page).
    """
    raw = os.environ.get("CLOUDINARY_URL", "")
    url = raw.strip().strip("\"'").strip()
    if url.upper().startswith("CLOUDINARY_URL="):
        url = url.split("=", 1)[1].strip().strip("\"'")
    if url != raw:
        if url:
            os.environ["CLOUDINARY_URL"] = url
        else:
            os.environ.pop("CLOUDINARY_URL", None)
    return url


def document_storage():
    """Storage for PDF/DOC/DOCX uploads.

    Cloudinary stores non-image files as "raw" resources, so documents need a
    different storage class from photos. Falls back to the normal local
    storage when CLOUDINARY_URL isn't set.
    """
    if clean_cloudinary_url():
        from .cloudinary_storages import SafeRawMediaCloudinaryStorage
        return SafeRawMediaCloudinaryStorage()
    return FileSystemStorage()