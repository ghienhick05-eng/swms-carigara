"""
In-browser document viewer.

"View" buttons used to link straight to the uploaded file, so a .docx was
downloaded by the browser. These views instead show the document inline:

* PDF files are streamed with ``Content-Disposition: inline``.
* DOC / DOCX files are converted to PDF on the server (LibreOffice, or
  Microsoft Word if that is what is installed) and streamed inline. Converted
  copies are cached in MEDIA_ROOT/previews/.
* If no converter is available, .docx files are still shown as a readable
  HTML page (via ``mammoth``) so every document can be viewed.

The separate "Download" buttons still link to the original file.
"""
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.utils.html import escape
from django.shortcuts import get_object_or_404, redirect

from .models import ActionPlan, Accomplishment, SCMAR
from .pdf_convert import convert_file_cached

# kind -> (model, file field, list url name used for redirects on error)
DOCUMENT_KINDS = {
    "action-plan": (ActionPlan, "file", "action_plan_list"),
    "accomplishment": (Accomplishment, "report_file", "accomplishment_list"),
    "scmar": (SCMAR, "evidence_document", "scmar_list"),
}

@login_required
def document_view(request, kind, pk):
    if kind not in DOCUMENT_KINDS:
        raise Http404
    model, field_name, list_url = DOCUMENT_KINDS[kind]
    obj = get_object_or_404(model, pk=pk)

    # Same rule as the detail pages: Barangay Users only see their own barangay.
    profile = getattr(request.user, "profile", None)
    if (not request.user.is_superuser and profile and profile.role == "user"
            and getattr(obj, "barangay", None) != profile.barangay):
        messages.error(request, "You can only view records for your own barangay.")
        return redirect(list_url)

    f = getattr(obj, field_name)
    if not f:
        raise Http404("No document uploaded.")
    try:
        src_path = f.path
    except (ValueError, NotImplementedError):
        raise Http404
    if not os.path.exists(src_path):
        raise Http404("File not found.")

    base = os.path.splitext(os.path.basename(src_path))[0]
    ext = os.path.splitext(src_path)[1].lower()

    if ext == ".pdf":
        pdf_path = src_path
    else:
        pdf_path, reason = convert_file_cached(src_path)
        if not pdf_path:
            if ext == ".docx":
                html = _docx_to_html_page(src_path, base, f.url)
                if html:
                    return html
            messages.error(
                request,
                "This document could not be previewed on the server. "
                + ("Install LibreOffice (or Microsoft Word) to view .doc files. " if ext == ".doc" else "")
                + "You can still use the Download button.",
            )
            return redirect(request.META.get("HTTP_REFERER") or list_url)

    response = FileResponse(open(pdf_path, "rb"), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{base}.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _docx_to_html_page(src_path, title, download_url):
    """Last-resort viewer for .docx when no PDF converter is installed."""
    try:
        import mammoth
    except ImportError:
        return None
    try:
        with open(src_path, "rb") as fh:
            body = mammoth.convert_to_html(fh).value
    except Exception:
        return None
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
 body{{margin:0;background:#e9edf0;font-family:Georgia,'Times New Roman',serif;color:#111}}
 .bar{{position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;gap:12px;
      padding:10px 20px;background:#166534;color:#fff;font-family:system-ui,sans-serif;font-size:.95rem}}
 .bar a{{color:#fff;border:1px solid rgba(255,255,255,.6);padding:6px 14px;border-radius:8px;text-decoration:none}}
 .page{{max-width:820px;margin:24px auto;background:#fff;padding:56px 64px;box-shadow:0 2px 12px rgba(0,0,0,.15);
       line-height:1.6;overflow-wrap:anywhere}}
 table{{border-collapse:collapse;max-width:100%}} td,th{{border:1px solid #999;padding:4px 8px}}
 img{{max-width:100%;height:auto}}
 @media(max-width:700px){{.page{{padding:24px 18px;margin:0}}}}
</style></head><body>
<div class="bar"><span>{escape(title)}</span><a href="{escape(download_url)}" download>Download</a></div>
<div class="page">{body}</div></body></html>"""
    response = HttpResponse(page)
    # The page only needs inline styles and embedded images - block anything else.
    response["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    return response