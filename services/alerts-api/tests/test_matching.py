from app.matching import normalise, score_profile


def make_profile():
    return {
        "industry": "Technology",
        "categories": ["IT Services"],
        "provinces": ["Limpopo"],
        "keywords": ["network"],
        "services_offered": "network equipment installation",
        "company_description": "",
    }


def make_tender():
    return {
        "tender_number": "IT-001",
        "title": "Network equipment supply",
        "description": "Supply and installation of network equipment",
        "province": "Limpopo",
        "category": "IT Services",
        "organisation": "Test Municipality",
        "closing_date": None,
        "status": "Open",
    }


def test_normalise():
    assert normalise("  Limpopo   ") == "limpopo"


def test_profile_matching_score_has_reasons():
    score, reasons = score_profile(make_profile(), make_tender())

    assert score >= 75
    assert score <= 100
    assert len(reasons) >= 3
    assert "Province matches your business profile" in reasons
    assert "Category matches your business profile" in reasons
    assert "Profile keyword match: network" in reasons


def test_keyword_only_profile_match_is_normalised_to_available_criteria():
    profile = {
        "industry": "",
        "categories": [],
        "provinces": [],
        "keywords": ["network"],
    }

    score, reasons = score_profile(profile, make_tender())

    assert score == 100
    assert reasons == ["Profile keyword match: network"]


def test_industry_match_uses_category_text():
    profile = {
        "industry": "technology",
        "categories": [],
        "provinces": [],
        "keywords": [],
    }
    tender = make_tender()
    tender["category"] = "Technology Services"

    score, reasons = score_profile(profile, tender)

    assert score == 100
    assert reasons == ["Industry matches your business profile"]


def test_missing_tender_province_is_excluded_when_user_selected_provinces():
    profile = {
        "industry": "",
        "categories": ["IT Services"],
        "provinces": ["Limpopo"],
        "keywords": ["network"],
    }
    tender = {
        "title": "Network equipment supply",
        "description": "Network installation",
        "province": None,
        "category": None,
    }

    score, reasons = score_profile(profile, tender)

    assert score == 0
    assert reasons == []


def test_tender_from_unselected_province_is_excluded_even_if_keywords_match():
    profile = make_profile()
    tender = make_tender()
    tender["province"] = "Gauteng"

    score, reasons = score_profile(profile, tender)

    assert score == 0
    assert reasons == []


def test_national_tender_is_included_for_selected_province():
    profile = make_profile()
    tender = make_tender()
    tender["province"] = "National"

    score, reasons = score_profile(profile, tender)

    assert score > 0
    assert "Province matches your business profile" not in reasons


def test_national_tender_label_is_case_insensitive():
    profile = make_profile()
    tender = make_tender()
    tender["province"] = " NATIONAL "

    score, _ = score_profile(profile, tender)

    assert score > 0


def test_keyword_score_changes_when_tender_relevance_changes():
    profile = {
        "industry": "",
        "categories": [],
        "provinces": [],
        "keywords": ["network", "cybersecurity"],
    }
    tender = make_tender()

    partial_score, _ = score_profile(profile, tender)
    tender["title"] = "Cybersecurity and network services"
    full_score, _ = score_profile(profile, tender)

    assert partial_score == 80
    assert full_score == 100


def test_one_strong_keyword_is_enough_for_an_alert():
    profile = {
        "industry": "Information Technology",
        "categories": [],
        "provinces": ["Gauteng"],
        "keywords": ["IT support", "Office supplies", "Website services", "Administrative support"],
        "services_offered": "IT support, office supplies, website services",
    }
    tender = {
        "title": "Provision of IT support services for 36 months",
        "description": "Desktop and network IT support",
        "province": "Gauteng",
        "category": "Services: Professional",
    }

    score, reasons = score_profile(profile, tender)

    assert score >= 70
    assert "Profile keyword match: it support" in reasons


def test_keyword_words_scattered_in_description_do_not_match():
    profile = {"industry": "", "categories": [], "provinces": [], "keywords": ["administrative support"]}
    tender = {
        "title": "Supply of two-way radios",
        "description": "Administrative requirements apply. Technical support is required on site.",
        "province": "Limpopo",
        "category": "Supplies: Electrical",
    }

    assert score_profile(profile, tender)[0] == 0


def test_no_matching_profile_dimensions_returns_zero():
    profile = make_profile()
    tender = make_tender()
    tender["province"] = "Gauteng"
    tender["category"] = "Construction"
    tender["title"] = "Road resurfacing"
    tender["description"] = "Roadworks"
    tender["services_offered"] = ""

    assert score_profile(profile, tender)[0] == 0


def test_closed_tender_is_not_scored_by_matcher():
    # Open/closed eligibility is enforced by the database candidate query;
    # this function scores relevance only.
    profile = make_profile()
    tender = make_tender()
    tender["status"] = "Closed"

    score, reasons = score_profile(profile, tender)

    assert score > 0
    assert reasons


def test_document_keyword_counts_and_is_labelled():
    profile = {
        "industry": "",
        "categories": [],
        "provinces": [],
        "keywords": ["paving"],
        "document_keywords": ["stormwater drainage"],
    }
    tender = {"title": "Stormwater drainage upgrade", "description": "", "province": "Limpopo", "category": ""}

    score, reasons = score_profile(profile, tender)

    assert score >= 70
    assert reasons == ["Matches your business documents: stormwater drainage"]


def test_related_words_find_tenders_without_the_exact_keyword():
    profile = {"industry": "", "categories": [], "provinces": ["Gauteng"], "keywords": ["IT support"]}
    tender = {"title": "Provision of helpdesk services for 36 months", "description": "", "province": "Gauteng", "category": ""}

    score, reasons = score_profile(profile, tender)

    assert 50 <= score < 100
    assert reasons[-1] == "Related to your keywords: helpdesk (for it support)"


def test_exact_keyword_scores_higher_than_related_word():
    profile = {"industry": "", "categories": [], "provinces": [], "keywords": ["IT support"]}
    exact = {"title": "IT support services", "description": "", "province": "Gauteng", "category": ""}
    related = {"title": "Helpdesk services", "description": "", "province": "Gauteng", "category": ""}

    assert score_profile(profile, exact)[0] > score_profile(profile, related)[0] > 0


def test_short_industry_words_do_not_match_inside_other_words():
    profile = {"industry": "Information Technology", "categories": [], "provinces": [], "keywords": []}
    tender = {"title": "Supply of lawn mower within the facility", "description": "", "province": "Limpopo", "category": "Supplies: General"}

    assert score_profile(profile, tender)[0] == 0


def test_category_matches_without_typing_the_prefix():
    profile = {"industry": "", "categories": ["computer equipment"], "provinces": [], "keywords": []}
    tender = {"title": "Laptops", "description": "", "province": "Gauteng", "category": "Supplies: Computer Equipment"}

    score, reasons = score_profile(profile, tender)

    assert score == 100
    assert "Category matches your business profile" in reasons


def test_head_office_province_ranks_local_tenders_higher_without_hiding_others():
    profile = {"industry": "", "categories": [], "provinces": [], "province": "Limpopo", "keywords": ["paving"]}
    local = {"title": "Paving of streets", "description": "", "province": "Limpopo", "category": ""}
    elsewhere = dict(local, province="Gauteng")

    local_score, local_reasons = score_profile(profile, local)
    elsewhere_score, _ = score_profile(profile, elsewhere)

    assert "In your head office province" in local_reasons
    assert local_score >= elsewhere_score > 0


def test_cidb_grade_too_low_excludes_tender():
    profile = {"industry": "", "categories": [], "provinces": [], "keywords": ["paving"], "cidb_grade": "4CE"}
    tender = {"title": "Paving of streets. CIDB grading 7CE or higher", "description": "", "province": "Limpopo", "category": ""}

    assert score_profile(profile, tender) == (0, [])


def test_cidb_grade_that_qualifies_is_explained():
    profile = {"industry": "", "categories": [], "provinces": [], "keywords": ["paving"], "cidb_grade": "7CE"}
    tender = {"title": "Paving of streets. CIDB grading 5 CE and higher", "description": "", "province": "Limpopo", "category": ""}

    score, reasons = score_profile(profile, tender)

    assert score == 100
    assert "Your CIDB grade meets the requirement (5CE)" in reasons


def test_missing_cidb_grade_keeps_tender_but_warns():
    profile = {"industry": "", "categories": [], "provinces": [], "keywords": ["paving"]}
    tender = {"title": "Paving of streets. CIDB grading 3GB", "description": "", "province": "Limpopo", "category": ""}

    score, reasons = score_profile(profile, tender)

    assert score > 0
    assert "Needs CIDB grade 3GB" in reasons


def test_without_ml_the_score_is_unchanged():
    assert score_profile(make_profile(), make_tender(), ml_category=None) == score_profile(make_profile(), make_tender())


def test_ml_category_turns_a_category_mismatch_into_a_match():
    tender = dict(make_tender(), category="Supplies: Computer Equipment")

    before, before_reasons = score_profile(make_profile(), tender)
    after, after_reasons = score_profile(make_profile(), tender, ml_category="Supplies: Computer Equipment")

    assert after > before
    assert "Category matches your business (ML: Supplies: Computer Equipment)" in after_reasons
    assert not any(reason.startswith("Category matches") for reason in before_reasons)


def test_ml_category_counts_when_the_profile_has_no_categories():
    profile = dict(make_profile(), categories=[])

    _, reasons = score_profile(profile, make_tender(), ml_category="Services: Professional")

    assert "Category matches your business (ML: Services: Professional)" in reasons


def test_profile_category_match_keeps_its_own_reason():
    _, reasons = score_profile(make_profile(), make_tender(), ml_category="Services: Professional")

    assert "Category matches your business profile" in reasons
    assert not any("(ML:" in reason for reason in reasons)
