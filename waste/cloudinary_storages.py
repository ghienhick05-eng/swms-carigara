"""Cloudinary storage classes that never crash on read-only lookups.

Only import this module when CLOUDINARY_URL is set (it pulls in
django-cloudinary-storage, which refuses to load without credentials).

The stock ``size()`` returns None (and ``exists()`` raises) when Cloudinary
answers anything but 200 - e.g. 401 for PDFs on accounts with "PDF and ZIP
delivery" turned off, or 404 for old files that only exist on local disk.
Django's validators then fail with ``TypeError: '>' not supported between
'NoneType' and 'int'``, which surfaced as HTTP 500.
"""
import logging

from cloudinary_storage.storage import MediaCloudinaryStorage, RawMediaCloudinaryStorage

logger = logging.getLogger(__name__)


class _SafeLookups:
    def size(self, name):
        try:
            return super().size(name) or 0
        except Exception:
            logger.warning("Cloudinary size() failed for %s", name, exc_info=True)
            return 0

    def exists(self, name):
        try:
            return super().exists(name)
        except Exception:
            logger.warning("Cloudinary exists() failed for %s", name, exc_info=True)
            return False


class SafeMediaCloudinaryStorage(_SafeLookups, MediaCloudinaryStorage):
    pass


class SafeRawMediaCloudinaryStorage(_SafeLookups, RawMediaCloudinaryStorage):
    pass