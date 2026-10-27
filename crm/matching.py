"""Suggest projects that fit a lead's requirement (location, budget, property type)."""
from decimal import Decimal

from .locale_data import city_center, distance_km
from .models import Project

BUDGET_STRETCH = Decimal("1.15")  # show projects starting up to 15% above budget, flagged
NEARBY_KM = 15


def suggest_projects(lead, limit=6):
    """Ranked list of dicts: project, score, tier, tier_label, reasons, warnings, distance_km."""
    projects = list(Project.objects.filter(is_active=True))
    # A lead living in a country without our projects (e.g. an overseas investor) has no location preference.
    local = any(p.country == lead.country for p in projects)
    center = city_center(lead.country, lead.city) if local else None
    wanted_type = lead.property_type if lead.property_type and lead.property_type != "other" else ""
    budget = lead.budget_amount
    results = []
    for p in projects:
        reasons, warnings, score = [], [], 0
        if local:
            if p.country != lead.country:
                continue
            if lead.area and p.area and lead.area.strip().lower() == p.area.strip().lower():
                tier, label, score = "area", "Same area", 50
            elif lead.city and p.city and lead.city.strip().lower() == p.city.strip().lower():
                tier, label, score = "city", "Same city", 35
            else:
                tier, label, score = "country", "Other city", 10
        else:
            tier, label, score = "any", "Any location", 20

        dist = None
        if center and p.has_coordinates:
            dist = distance_km(center, (p.latitude, p.longitude))
            if tier == "country" and dist <= NEARBY_KM:
                tier, label, score = "nearby", "Nearby", 25

        if wanted_type and p.unit_type_list:
            if wanted_type not in p.unit_type_list:
                continue
            score += 25
            reasons.append(f"Has {lead.get_property_type_display()}")

        if budget:
            if p.price_from <= budget:
                score += 25
                reasons.append("Within budget")
            elif p.price_from <= budget * BUDGET_STRETCH:
                score += 5
                over = round((p.price_from / budget - 1) * 100)
                warnings.append(f"Starts {over}% above budget")
            else:
                continue

        if dist is not None:
            reasons.append(f"~{dist:.0f} km from {lead.city}")
        results.append({"project": p, "score": score, "tier": tier, "tier_label": label,
                        "reasons": reasons, "warnings": warnings, "distance_km": dist})

    results.sort(key=lambda r: (-r["score"], r["project"].price_from))
    return results[:limit] if limit else results
