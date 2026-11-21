"""
Catalogue of the compliance documents South African public-sector tenders ask for.

Each entry tells the document AI what to look for and how to judge it:
  - fields:        what to extract from the document
  - max_age_days:  documents that must be recent (bank letters, certified copies…)
  - has_expiry:    documents with an expiry date the agent must watch
  - requirement:   "required" for almost every tender, "recommended" otherwise,
                   "sector" when only some industries need it (see `industries`)
"""

DOCUMENT_TYPES: list[dict] = [
    {
        "key": "company_registration",
        "label": "CIPC company registration",
        "hint": "CoR 14.3 / CK1 registration certificate from CIPC, including the list of directors.",
        "requirement": "required",
        "weight": 15,
        "multiple": False,
        "fields": ["company_name", "registration_number", "registration_date", "enterprise_type", "directors", "status"],
        "has_expiry": False,
        "max_age_days": None,
    },
    {
        "key": "director_id",
        "label": "Certified ID copies of directors",
        "hint": "Certified copy of each director's / member's South African ID (certified within the last 3 months).",
        "requirement": "required",
        "weight": 10,
        "multiple": True,
        "fields": ["full_name", "id_number", "date_of_birth", "certification_date", "certified_by"],
        "has_expiry": False,
        "max_age_days": 90,
        "age_field": "certification_date",
    },
    {
        "key": "tax_compliance",
        "label": "SARS tax compliance status (TCS PIN)",
        "hint": "Tax Compliance Status letter from SARS eFiling showing the PIN and expiry date.",
        "requirement": "required",
        "weight": 15,
        "multiple": False,
        "fields": ["taxpayer_name", "tax_reference_number", "tcs_pin", "compliance_status", "issue_date", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
    {
        "key": "csd_report",
        "label": "CSD registration report",
        "hint": "Central Supplier Database full registration report (supplier number starts with MAAA).",
        "requirement": "required",
        "weight": 15,
        "multiple": False,
        "fields": ["supplier_number", "legal_name", "registration_number", "tax_status", "bbbee_level", "report_date",
                   "commodities"],
        "has_expiry": False,
        "max_age_days": 180,
        "age_field": "report_date",
    },
    {
        "key": "bbbee",
        "label": "B-BBEE certificate or sworn affidavit",
        "hint": "Valid B-BBEE certificate from a SANAS-accredited agency, or a commissioned sworn affidavit (EME/QSE).",
        "requirement": "required",
        "weight": 10,
        "multiple": False,
        "fields": ["entity_name", "document_kind", "bbbee_level", "black_ownership_percent", "black_female_ownership_percent", "issuer", "issue_date", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
    {
        "key": "bank_confirmation",
        "label": "Bank confirmation letter",
        "hint": "Stamped letter from your bank confirming the business account (not older than 3 months).",
        "requirement": "required",
        "weight": 10,
        "multiple": False,
        "fields": ["bank_name", "account_holder", "account_number", "branch_code", "account_type", "letter_date", "stamped"],
        "has_expiry": False,
        "max_age_days": 90,
        "age_field": "letter_date",
    },
    {
        "key": "bank_statement",
        "label": "Bank statement (latest 3 months)",
        "hint": "Most recent business bank statement(s) covering the last 3 months.",
        "requirement": "required",
        "weight": 5,
        "multiple": True,
        "fields": ["bank_name", "account_holder", "account_number", "statement_period_start", "statement_period_end", "closing_balance"],
        "has_expiry": False,
        "max_age_days": 90,
        "age_field": "statement_period_end",
    },
    {
        "key": "proof_of_address",
        "label": "Proof of business address / municipal rates",
        "hint": "Municipal rates account, lease agreement or utility bill in the company's name (not older than 3 months).",
        "requirement": "required",
        "weight": 5,
        "multiple": False,
        "fields": ["name", "address", "issuer", "document_date", "account_in_arrears"],
        "has_expiry": False,
        "max_age_days": 90,
        "age_field": "document_date",
    },
    {
        "key": "coida",
        "label": "COIDA letter of good standing",
        "hint": "Compensation Fund letter of good standing (Department of Employment and Labour).",
        "requirement": "recommended",
        "weight": 5,
        "multiple": False,
        "fields": ["employer_name", "registration_number", "issue_date", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
    {
        "key": "uif",
        "label": "UIF registration / compliance",
        "hint": "UIF registration confirmation or letter of compliance.",
        "requirement": "recommended",
        "weight": 0,
        "multiple": False,
        "fields": ["employer_name", "uif_reference_number", "issue_date"],
        "has_expiry": False,
        "max_age_days": None,
    },
    {
        "key": "financial_statements",
        "label": "Financial statements",
        "hint": "Latest audited or independently reviewed annual financial statements (often required for larger tenders).",
        "requirement": "recommended",
        "weight": 0,
        "multiple": False,
        "fields": ["entity_name", "financial_year_end", "turnover", "net_profit", "auditor_or_reviewer", "audit_kind"],
        "has_expiry": False,
        "max_age_days": 550,
        "age_field": "financial_year_end",
    },
    {
        "key": "cidb",
        "label": "CIDB grading certificate",
        "hint": "Construction Industry Development Board registration showing your grade and class of works.",
        "requirement": "sector",
        "industries": ["construction", "civil", "building", "engineering", "electrical", "plumbing", "roads", "infrastructure", "renovation", "mechanical"],
        "weight": 0,
        "multiple": False,
        "fields": ["contractor_name", "crs_number", "grading_designation", "class_of_works", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
    {
        "key": "psira",
        "label": "PSIRA registration",
        "hint": "Private Security Industry Regulatory Authority certificate (security services only).",
        "requirement": "sector",
        "industries": ["security", "guarding", "cctv", "access control"],
        "weight": 0,
        "multiple": False,
        "fields": ["business_name", "psira_number", "grade", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
    {
        "key": "professional_registration",
        "label": "Professional body registration",
        "hint": "ECSA, SACAP, SACQSP, SAICA, LPC, HPCSA or similar registration for key personnel.",
        "requirement": "sector",
        "industries": ["engineering", "architecture", "quantity surveying", "legal", "accounting", "auditing", "medical", "healthcare", "consulting"],
        "weight": 0,
        "multiple": True,
        "fields": ["person_name", "professional_body", "registration_number", "category", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
    {
        "key": "insurance",
        "label": "Insurance (public liability / indemnity)",
        "hint": "Public liability or professional indemnity cover note.",
        "requirement": "recommended",
        "weight": 0,
        "multiple": True,
        "fields": ["insurer", "policy_holder", "policy_number", "cover_type", "cover_amount", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
    {
        "key": "other",
        "label": "Other supporting document",
        "hint": "Anything else you include in tenders: share certificates, JV agreements, reference letters…",
        "requirement": "optional",
        "weight": 0,
        "multiple": True,
        "fields": ["document_title", "issuer", "issue_date", "expiry_date"],
        "has_expiry": True,
        "max_age_days": None,
    },
]

DOCUMENT_TYPES_BY_KEY = {d["key"]: d for d in DOCUMENT_TYPES}

# Weight given to the business profile itself in the readiness score.
PROFILE_WEIGHT = 10


def get_type(key: str) -> dict | None:
    return DOCUMENT_TYPES_BY_KEY.get(key)


def applies_to(doc_type: dict, profile: dict | None) -> bool:
    """Whether a document type matters for this business (sector docs depend on industry)."""
    if doc_type["requirement"] != "sector":
        return True
    if not profile:
        return False
    haystack = " ".join(
        str(x) for x in (profile.get("industries") or []) + (profile.get("services") or [])
    ).lower()
    return any(word in haystack for word in doc_type.get("industries", []))


def public_catalogue() -> list[dict]:
    keep = ("key", "label", "hint", "requirement", "multiple", "has_expiry", "max_age_days")
    return [{k: d.get(k) for k in keep} for d in DOCUMENT_TYPES]
