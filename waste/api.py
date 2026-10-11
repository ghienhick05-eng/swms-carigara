"""
Read-only JSON API for the barangays of Carigara, Leyte.

    GET /api/barangays/            -> all 49 barangays (public, names only)
                                      optional: ?search=<text>
    GET /api/barangays/<slug>/     -> one barangay + activity summary
                                      (login required; Barangay Users can
                                      only view their own barangay)

No new dependencies, models, or migrations: the barangay list comes from
BARANGAY_CHOICES, the single source of truth used by the rest of the system.
"""
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.http import require_GET
from django.db.models import Count

from .models import (
    BARANGAY_CHOICES, Collection, Complaint, Accomplishment, ActionPlan,
)

MUNICIPALITY = "Carigara"
PROVINCE = "Leyte"

# slug -> official name, in the same order as BARANGAY_CHOICES
BARANGAYS = {slugify(name): name for name, _label in BARANGAY_CHOICES}


def _brief(slug, name):
    return {
        "slug": slug,
        "name": name,
        "municipality": MUNICIPALITY,
        "province": PROVINCE,
        "url": f"/api/barangays/{slug}/",
    }


def _by_status(qs):
    return {row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))}


@require_GET
def barangay_list(request):
    search = request.GET.get("search", "").strip().lower()
    results = [
        _brief(slug, name)
        for slug, name in BARANGAYS.items()
        if not search or search in name.lower()
    ]
    return JsonResponse({"count": len(results), "results": results})


@require_GET
def barangay_detail(request, slug):
    name = BARANGAYS.get(slug)
    if name is None:
        return JsonResponse({"detail": "Barangay not found."}, status=404)

    user = request.user
    if not user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)

    # Barangay Users may only see their own barangay (same rule as the web UI).
    profile = getattr(user, "profile", None)
    if (not user.is_superuser and profile is not None
            and profile.role == "user" and profile.barangay != name):
        return JsonResponse({"detail": "You can only view your own barangay."}, status=403)

    data = _brief(slug, name)
    data["summary"] = {
        "collections": _by_status(Collection.objects.filter(barangay=name)),
        "complaints": _by_status(Complaint.objects.filter(barangay=name)),
        "action_plans": _by_status(ActionPlan.objects.filter(barangay=name)),
        "accomplishments": Accomplishment.objects.filter(barangay=name).count(),
    }
    return JsonResponse(data)