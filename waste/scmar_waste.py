"""
SCMAR waste table: catalog, parsing and totals.

This mirrors the paper "Weight and Processed (Monthly)" MRF form that each
Barangay fills in: every waste type is listed under one of six sections,
each section has a subtotal, and the sheet ends with TOTAL WASTE RECEIVED.

Only the Biodegradable section has processing columns (Composting,
Bio-digestion, Other's process). Every other section is a single
"quantity received" column in kilograms.

This module intentionally has no Django imports so the maths can be tested
on its own. models.py stores one SCMARWasteEntry row per catalog item.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_KG = Decimal("9999999.99")

# (key, label, hint)
SECTIONS = [
    {
        "key": "biodegradable",
        "short": "Biodegradable",
        "title": "Biodegradable Waste",
        "icon": "fa-leaf",
        "color": "#65A30D",
        "has_processing": True,
        "groups": [
            {"title": "", "items": [
                ("garden_yard", "Garden and yard waste", ""),
                ("kitchen", "Kitchen waste", ""),
                ("livestock", "Livestock waste", ""),
                ("agricultural", "Agricultural waste", ""),
            ]},
        ],
    },
    {
        "key": "recyclable",
        "short": "Recyclable",
        "title": "Recyclable Waste",
        "icon": "fa-recycle",
        "color": "#2563EB",
        "has_processing": False,
        "groups": [
            {"title": "Plastic", "items": [
                ("pet", "PET (1)", "Water / beverage bottles, cosmetic or personal care bottles"),
                ("hdpe", "HDPE (2)", "Beverage jugs, personal care containers"),
            ]},
            {"title": "Metals", "items": [
                ("aluminum", "Aluminum", "Aluminum cans, aluminum trays"),
                ("copper", "Copper", "Copper wire, copper tubes"),
                ("tin", "Tin", "Sardine cans, soup cans"),
                ("steel", "Steel", "Steel, steel sheets"),
            ]},
            {"title": "Paper", "items": [
                ("swl", "Selected white ledger (SWL)", "Bond paper, white envelopes"),
                ("occ", "Old corrugated cardboard", "Carton boxes, paper bags, brown envelopes"),
                ("onp", "Old newspaper", "Newspapers, old newsprint, textbooks"),
                ("mixed_paper", "Mixed paper", "Magazines, pamphlets"),
                ("beverage_cartons", "Used beverage cartons", "Juice cartons, milk cartons"),
            ]},
            {"title": "Glass", "items": [
                ("glass_bottles", "Bottles", "Flint / clear, green, amber / brown, colored"),
                ("flat_glass", "Flat glass", "Clear, mirror, tinted, low-e coated glass"),
                ("cullet", "Cullet", "Broken glass bottles and broken flat glass (sorted by color)"),
            ]},
        ],
    },
    {
        "key": "diversion",
        "short": "Diversion residuals",
        "title": "Residuals with Potential for Waste Diversion",
        "icon": "fa-arrows-rotate",
        "color": "#D97706",
        "has_processing": False,
        "groups": [
            {"title": "", "items": [
                ("joy_pack", "Joy pack, sachet, wrappers", ""),
                ("tarpaulin", "Tarpaulin", ""),
                ("grocery_bags", "Grocery and food bags", ""),
                ("straw", "Drinking straw", ""),
                ("slipper_mats", "Slippers and rubber mats", ""),
                ("rags", "Rags", ""),
            ]},
        ],
    },
    {
        "key": "residual",
        "short": "Residual",
        "title": "Residual Waste",
        "icon": "fa-trash-can",
        "color": "#64748B",
        "has_processing": False,
        "groups": [
            {"title": "", "items": [
                ("cigarette_butt", "Cigarette butt", ""),
                ("soiled_tissue", "Soiled tissue paper", ""),
                ("sanitary_napkin", "Sanitary napkin", ""),
                ("food_paper", "Food-contaminated paper", ""),
                ("coated_paper", "Coated paper", ""),
                ("diaper", "Diaper", ""),
            ]},
        ],
    },
    {
        "key": "special",
        "short": "Special",
        "title": "Special Waste",
        "icon": "fa-triangle-exclamation",
        "color": "#DC2626",
        "has_processing": False,
        "groups": [
            {"title": "", "items": [
                ("special_other", "Special (other)", ""),
                ("hazardous", "Hazardous waste", ""),
                ("paint_solvent", "Paint and solvent", ""),
                ("used_oil", "Used oil", "Motor oil, cooking oil"),
                ("white_goods", "White goods", ""),
                ("cleaning_chemicals", "Cleaning chemicals", ""),
                ("gadget_batteries", "Laptop / gadget batteries, power banks", ""),
                ("consumer_electronics", "Consumer electronics and tools", ""),
                ("pesticide_containers", "Pesticide and herbicide containers", ""),
                ("busted_lights", "Busted lights", ""),
                ("vehicle_batteries", "Industrial and vehicle batteries", ""),
                ("it_telco", "I.T. / telco gadgets and peripherals", ""),
                ("healthcare", "Household healthcare waste", ""),
            ]},
        ],
    },
    {
        "key": "bulky",
        "short": "Bulky",
        "title": "Bulky Waste",
        "icon": "fa-couch",
        "color": "#7C3AED",
        "has_processing": False,
        "groups": [
            {"title": "", "items": [
                ("bulky_yard", "Bulky yard waste", ""),
                ("rubber_tires", "Rubber tires", ""),
                ("construction", "Construction debris", ""),
                ("demolition", "Demolition debris", ""),
            ]},
        ],
    },
]

ITEM_LABELS = {}
BIO_KEYS = set()
for _s in SECTIONS:
    for _g in _s["groups"]:
        for _k, _label, _hint in _g["items"]:
            ITEM_LABELS[_k] = _label
            if _s["has_processing"]:
                BIO_KEYS.add(_k)
ALL_KEYS = list(ITEM_LABELS)

# POST field prefixes: w=received, c=composting, b=bio-digestion, o=other process
PREFIXES = ("w", "c", "b", "o")


def _num(value):
    """Lenient Decimal conversion for display math (invalid or blank = 0)."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except InvalidOperation:
        return ZERO


def fmt(value, blank_zero=False):
    """5.00 -> '5', 2.50 -> '2.5', 1234.5 -> '1,234.5'."""
    d = _num(value).quantize(CENT, rounding=ROUND_HALF_UP)
    if d == 0 and blank_zero:
        return ""
    text = f"{d:,.2f}".rstrip("0").rstrip(".")
    return text or "0"


def fmt_plain(value):
    """Like fmt() but without thousands separators and blank for zero (form inputs)."""
    d = _num(value).quantize(CENT, rounding=ROUND_HALF_UP)
    if d == 0:
        return ""
    return f"{d:.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Parsing a submitted form
# ---------------------------------------------------------------------------

def _parse_one(raw, label, what, errors):
    text = (raw or "").replace(",", "").strip()
    if not text:
        return ZERO
    try:
        d = Decimal(text)
    except InvalidOperation:
        errors.append(f"{label}: {what} must be a number.")
        return ZERO
    if not d.is_finite():
        errors.append(f"{label}: {what} must be a number.")
        return ZERO
    if d < 0:
        errors.append(f"{label}: {what} cannot be negative.")
        return ZERO
    if d > MAX_KG:
        errors.append(f"{label}: {what} is too large.")
        return ZERO
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_submission(post):
    """
    Read the waste table out of request.POST.

    Returns (entries, raw, errors):
      entries - {item_key: {"w": Decimal, "c": Decimal, "b": Decimal, "o": Decimal}}
      raw     - same shape but the untouched strings, used to re-render the
                form with the user's input if validation fails
      errors  - list of human-readable messages
    """
    entries, raw, errors = {}, {}, []
    for key in ALL_KEYS:
        label = ITEM_LABELS[key]
        raw[key] = {p: (post.get(f"{p}_{key}") or "") for p in PREFIXES}
        row = {"w": _parse_one(raw[key]["w"], label, "quantity received", errors)}
        if key in BIO_KEYS:
            row["c"] = _parse_one(raw[key]["c"], label, "composting", errors)
            row["b"] = _parse_one(raw[key]["b"], label, "bio-digestion", errors)
            row["o"] = _parse_one(raw[key]["o"], label, "other process", errors)
            if row["c"] + row["b"] + row["o"] > row["w"]:
                errors.append(
                    f"{label}: processed weight (composting + bio-digestion + other) "
                    f"cannot be more than the quantity received."
                )
        else:
            row["c"] = row["b"] = row["o"] = ZERO
        entries[key] = row
    return entries, raw, errors


# ---------------------------------------------------------------------------
# Building the structure the templates render
# ---------------------------------------------------------------------------

def values_from_entries(entries):
    """entries: iterable of SCMARWasteEntry-like objects -> values dict."""
    values = {}
    for e in entries:
        values[e.item_key] = {
            "w": e.weight_kg, "c": e.composting_kg,
            "b": e.biodigestion_kg, "o": e.other_process_kg,
        }
    return values


def build_sections(values=None, for_form=False):
    """
    Combine the catalog with a values dict and compute every subtotal.

    values: {item_key: {"w","c","b","o"}} of Decimals (saved data) or raw
            strings (a re-rendered form). Missing keys count as zero.
    for_form: if True, item input values are plain strings ready for
              <input value=...>; otherwise they are display-formatted.

    Returns {"sections": [...], "grand_total": Decimal, "grand_total_display": str,
             "diverted": Decimal, "diverted_pct": float, "has_data": bool,
             "processed_total": Decimal}
    """
    values = values or {}
    sections, grand = [], ZERO
    processed_total = ZERO

    for s in SECTIONS:
        sec_total = sec_c = sec_b = sec_o = ZERO
        groups = []
        for g in s["groups"]:
            items = []
            for key, label, hint in g["items"]:
                v = values.get(key, {})
                w, c, b, o = (_num(v.get(p)) for p in PREFIXES)
                sec_total += w
                if s["has_processing"]:
                    sec_c += c
                    sec_b += b
                    sec_o += o
                items.append({
                    "key": key, "label": label, "hint": hint,
                    "w": w, "c": c, "b": b, "o": o,
                    # strings for form inputs keep exactly what the user typed
                    "w_in": (v.get("w") if for_form and isinstance(v.get("w"), str) else fmt_plain(w)),
                    "c_in": (v.get("c") if for_form and isinstance(v.get("c"), str) else fmt_plain(c)),
                    "b_in": (v.get("b") if for_form and isinstance(v.get("b"), str) else fmt_plain(b)),
                    "o_in": (v.get("o") if for_form and isinstance(v.get("o"), str) else fmt_plain(o)),
                    "w_display": fmt(w), "c_display": fmt(c),
                    "b_display": fmt(b), "o_display": fmt(o),
                    "unprocessed": w - c - b - o,
                    "unprocessed_display": fmt(w - c - b - o),
                    "filled": w > 0,
                })
            groups.append({"title": g["title"], "items": items})
        grand += sec_total
        processed_total += sec_c + sec_b + sec_o
        sections.append({
            "key": s["key"], "short": s["short"], "title": s["title"], "icon": s["icon"], "color": s["color"],
            "has_processing": s["has_processing"], "groups": groups,
            "total": sec_total, "total_display": fmt(sec_total),
            "c_total": sec_c, "b_total": sec_b, "o_total": sec_o,
            "c_total_display": fmt(sec_c), "b_total_display": fmt(sec_b), "o_total_display": fmt(sec_o),
            "unprocessed_total_display": fmt(sec_total - sec_c - sec_b - sec_o),
            "filled_count": sum(1 for g in groups for i in g["items"] if i["filled"]),
            "item_count": sum(len(g["items"]) for g in groups),
        })

    for sec in sections:
        sec["pct"] = float((sec["total"] / grand * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if grand else 0.0
        sec["pct_display"] = f"{sec['pct']:.1f}".rstrip("0").rstrip(".") if grand else "0"
        sec["bar_width"] = float(sec["total"] / grand * 100) if grand else 0.0

    diverted = sum(
        (s["total"] for s in sections if s["key"] in ("biodegradable", "recyclable", "diversion")),
        ZERO,
    )
    return {
        "sections": sections,
        "grand_total": grand,
        "grand_total_display": fmt(grand),
        "diverted": diverted,
        "diverted_display": fmt(diverted),
        "diverted_pct": float(diverted / grand * 100) if grand else 0.0,
        "processed_total": processed_total,
        "processed_total_display": fmt(processed_total),
        "has_data": grand > 0,
    }