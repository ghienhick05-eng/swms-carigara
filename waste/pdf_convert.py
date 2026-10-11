"""
DOC / DOCX -> PDF conversion helpers.

Used in two places:
* at upload time (model save()) so new Word reports are stored as PDF, and
* by the "View" button for older Word files that are still stored as .docx.

Converters are tried in this order, and the first that works wins:
  1. LibreOffice (headless)             - Windows / Mac / Linux
  2. Microsoft Word via ``docx2pdf``    - Windows / Mac with Word installed
If none works the caller keeps the original file (upload) or falls back to an
HTML preview for .docx (view), so nothing is ever blocked.
"""
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)
CONVERTIBLE = {".doc", ".docx"}

_MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
_WIN_SOFFICE = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)


def _find_soffice():
    configured = getattr(settings, "LIBREOFFICE_PATH", None)
    if configured and os.path.exists(configured):
        return configured
    for name in ("soffice", "libreoffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (_MAC_SOFFICE, *_WIN_SOFFICE):
        if os.path.exists(candidate):
            return candidate
    return None


def _with_libreoffice(src, out_dir):
    soffice = _find_soffice()
    if not soffice:
        return None, "LibreOffice was not found"
    profile_dir = os.path.join(out_dir, "lo_profile")
    uri = ("file:///" + profile_dir.replace(os.sep, "/")) if os.name == "nt" else f"file://{profile_dir}"
    try:
        result = subprocess.run(
            [soffice, f"-env:UserInstallation={uri}", "--headless",
             "--convert-to", "pdf", "--outdir", out_dir, src],
            capture_output=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return None, f"LibreOffice failed ({exc})"
    pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    if os.path.exists(pdf):
        return pdf, ""
    err = (result.stderr or b"").decode(errors="ignore").strip()[:200]
    return None, f"LibreOffice produced no PDF {err}".strip()


def _with_word(src, out_dir):
    try:
        from docx2pdf import convert  # optional dependency
    except ImportError:
        return None, "docx2pdf is not installed"
    pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    try:
        convert(src, pdf)
    except Exception as exc:  # Word missing, COM errors, etc.
        return None, f"Microsoft Word conversion failed ({exc})"
    return (pdf, "") if os.path.exists(pdf) else (None, "Microsoft Word produced no PDF")


def convert_to_pdf(src, out_dir):
    """Convert src into out_dir. Returns (pdf_path or None, reason string)."""
    reasons = []
    for converter in (_with_libreoffice, _with_word):
        pdf, reason = converter(src, out_dir)
        if pdf:
            return pdf, ""
        reasons.append(reason)
    msg = "; ".join(reasons)
    logger.warning("PDF conversion failed for %s: %s", src, msg)
    return None, msg


def convert_file_cached(src_path):
    """PDF copy of src_path, cached in MEDIA_ROOT/previews. Returns (path, reason)."""
    stat = os.stat(src_path)
    key = hashlib.sha1(f"{src_path}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()
    cache_dir = os.path.join(settings.MEDIA_ROOT, "previews")
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, f"{key}.pdf")
    if os.path.exists(cached):
        return cached, ""
    with tempfile.TemporaryDirectory() as tmp:
        pdf, reason = convert_to_pdf(src_path, tmp)
        if not pdf:
            return None, reason
        shutil.move(pdf, cached)
    return cached, ""


def convert_field_to_pdf(instance, field_name):
    """If the field holds a freshly uploaded DOC/DOCX, replace it with a PDF."""
    f = getattr(instance, field_name, None)
    if not f or getattr(f, "_committed", True):
        return  # nothing new was uploaded
    base, ext = os.path.splitext(os.path.basename(f.name))
    if ext.lower() not in CONVERTIBLE:
        return
    f.seek(0)
    data = f.read()
    f.seek(0)  # leave the upload readable so it can still be saved unchanged
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "upload" + ext.lower())
        with open(src, "wb") as fh:
            fh.write(data)
        pdf, _ = convert_to_pdf(src, tmp)
        if pdf:
            with open(pdf, "rb") as fh:
                f.save(base + ".pdf", ContentFile(fh.read()), save=False)