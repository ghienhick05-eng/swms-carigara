import os

from django.core.files.storage import FileSystemStorage


def document_storage():
    """Storage for PDF/DOC/DOCX uploads.

    Cloudinary stores non-image files as "raw" resources, so documents need a
    different storage class from photos. Falls back to the normal local
    storage when CLOUDINARY_URL isn't set.
    """
    if os.environ.get("CLOUDINARY_URL"):
        from cloudinary_storage.storage import RawMediaCloudinaryStorage
        return RawMediaCloudinaryStorage()
    return FileSystemStorage()