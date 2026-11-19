from .keywords import score_keywords
from .rules import (
    category_matches,
    cidb_requirement,
    clean_list,
    format_requirement,
    has_text,
    normalise,
    parse_grades,
    phrase_in,
    tokens,
)
from .synonyms import industry_terms

__all__ = ["normalise", "score_profile"]

WEIGHTS = {
    "province": 20,
    "category": 25,
    "industry": 20,
    "keywords": 25,
    "services": 10,
}
NATIONAL = {"national", "national tenders", "all provinces"}


class _Tally:
    """Running totals for one profile/tender comparison."""

    def __init__(self):
        self.earned = 0.0
        self.possible = 0.0
        self.reasons = []

    def add(self, weight, earned, reason=None):
        self.possible += weight
        self.earned += earned
        if reason:
            self.reasons.append(reason)


def _searchable_text(tender):
    return " ".join(
        normalise(tender.get(field))
        for field in ("title", "description", "category", "organisation", "tender_number")
        if has_text(tender.get(field))
    )


def _score_province(tally, profile, province):
    """Returns False when the tender is outside the profile's chosen provinces."""
    weight = WEIGHTS["province"]
    provinces = set(clean_list(profile.get("provinces")))
    if not provinces:
        head_office = normalise(profile.get("province"))
        if head_office and province == head_office:
            tally.add(weight, weight, "In your head office province")
        return True
    if province in NATIONAL:
        return True
    if not province or province not in provinces:
        return False
    tally.add(weight, weight, "Province matches your business profile")
    return True


def _check_cidb(tally, profile, searchable):
    """Returns False when the profile's CIDB grade is too low for the tender."""
    required = cidb_requirement(searchable)
    if not required:
        return True
    grades = parse_grades(profile.get("cidb_grade"))
    requirement = format_requirement(required)
    if not grades:
        tally.reasons.append(f"Needs CIDB grade {requirement}")
        return True
    if not any(grades.get(grade_class, 0) >= level for grade_class, level in required.items()):
        return False
    tally.reasons.append(f"Your CIDB grade meets the requirement ({requirement})")
    return True


def _score_category(tally, profile, category, ml_category=None):
    """The ML model's answer can only turn a category mismatch into a match, never lower a score."""
    weight = WEIGHTS["category"]
    categories = clean_list(profile.get("categories"))
    if categories and category and category_matches(categories, category):
        tally.add(weight, weight, "Category matches your business profile")
    elif ml_category:
        tally.add(weight, weight, f"Category matches your business (ML: {ml_category})")
    elif categories and category:
        tally.add(weight, 0)


def _mentions_industry(industries, searchable):
    return any(phrase_in(term, searchable) for value in industries for term in industry_terms(value))


def _score_industry(tally, profile, searchable):
    weight = WEIGHTS["industry"]
    industry = normalise(profile.get("industry"))
    document_industries = [value for value in clean_list(profile.get("document_industries")) if value != industry]
    if not searchable:
        return
    if industry and _mentions_industry([industry], searchable):
        tally.add(weight, weight, "Industry matches your business profile")
    elif _mentions_industry(document_industries, searchable):
        tally.add(weight, weight, "Industry from your business documents matches")


def _score_services(tally, profile, searchable):
    weight = WEIGHTS["services"]
    services = normalise(profile.get("services_offered"))
    description = normalise(profile.get("company_description"))
    service_text = " ".join(value for value in (services, description) if value)
    if not (service_text and searchable):
        return
    meaningful_tokens = {token for token in tokens(service_text) if len(token) > 3}
    if not meaningful_tokens:
        tally.add(weight, 0)
        return
    ratio = len(meaningful_tokens & tokens(searchable)) / len(meaningful_tokens)
    reason = "Tender wording overlaps with your services" if ratio >= 0.2 else None
    tally.add(weight, weight * ratio, reason)


def score_profile(profile, tender, normalise_to_available=True, ml_category=None):
    """Score 0-100 with reasons. `ml_category` is the category tender-ml says the company and tender share."""
    tally = _Tally()
    searchable = _searchable_text(tender)

    if not _score_province(tally, profile, normalise(tender.get("province"))):
        return 0, []
    if not _check_cidb(tally, profile, searchable):
        return 0, []

    _score_category(tally, profile, normalise(tender.get("category")), ml_category)
    _score_industry(tally, profile, searchable)
    score_keywords(tally, profile, searchable, tokens(tender.get("title")), WEIGHTS["keywords"])
    _score_services(tally, profile, searchable)

    if tally.possible <= 0 or tally.earned <= 0:
        return 0, []

    score = round(tally.earned / tally.possible * 100) if normalise_to_available else round(tally.earned)
    return max(0, min(100, score)), tally.reasons
