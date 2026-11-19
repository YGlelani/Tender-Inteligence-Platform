"""
Rule-based bid strategy generator (v2).

Given a tender and a business profile, produces a detailed, realistic
bid strategy using pattern matching — no LLM involved.

Designed so the output reads like a professional consultant's report:
evidence quotes, deadline countdown, evaluation criteria, competitive
positioning, gap mitigation (JV/subcontract), and full SA doc baseline.
"""
import re
from datetime import datetime, timezone


# ============================================================
# Industry overlays — extend the SA baseline
# ============================================================
INDUSTRY_PROFILES = {
    "construction": {
        "certifications": ["CIDB grading", "SACPCMP registration"],
        "documents": [
            "CIDB registration certificate",
            "SACPCMP registration for site staff",
            "Letter of Good Standing (Compensation Fund)",
            "Construction work permit (where applicable)",
            "OHS Act appointments (Construction Regulations 2014)",
        ],
        "requirements": [
            "Demonstrated experience with similar construction projects",
            "Health and Safety Plan aligned with the Construction Regulations",
            "On-site qualified site manager",
        ],
        "differentiators": [
            "State your CIDB grading and any higher-than-required grading",
            "Highlight past projects of similar scope and value",
            "Mention safety record (zero lost-time injuries, etc.)",
        ],
        "pitfalls": [
            "Missing CIDB grading is an automatic disqualification on most civil tenders.",
            "OHS file must be site-specific, not generic.",
        ],
    },
    "it_services": {
        "certifications": ["ISO 27001", "CompTIA", "Cisco", "Microsoft Partner"],
        "documents": [
            "Relevant technical certifications for staff",
            "Data protection and POPIA compliance statement",
            "Service Level Agreement (SLA) template",
        ],
        "requirements": [
            "Demonstrated cloud/network/security experience",
            "24/7 support capability statement",
            "Scalability plan aligned with the tender's requirements",
        ],
        "differentiators": [
            "Highlight uptime guarantees (99.9%+)",
            "List past similar deployments with client names",
            "Offer a proof-of-concept or pilot phase",
        ],
        "pitfalls": [
            "No POPIA statement = weak data-protection score.",
            "Vague SLAs are penalised — give numbers.",
        ],
    },
    "cleaning": {
        "certifications": ["SABS approved chemicals", "B-BBEE Level 1"],
        "documents": [
            "Chemical safety data sheets (SDS)",
            "Staff training records",
            "Proof of cleaning equipment ownership or lease",
        ],
        "requirements": [
            "Demonstrated hygiene standards and cleaning methodology",
            "Staff vetting and supervision plan",
            "Waste disposal procedures (if required)",
        ],
        "differentiators": [
            "Offer a dedicated on-site supervisor",
            "Provide a detailed cleaning schedule",
            "Include a quality assurance audit plan",
        ],
        "pitfalls": [
            "No COA = disqualified on most catering-adjacent cleaning contracts.",
        ],
    },
    "catering": {
        "certifications": ["HACCP", "Food safety certification", "Local municipality health certificate"],
        "documents": [
            "Certificate of Acceptability (COA) from the local municipality",
            "Food handler medical certificates for staff",
            "HACCP or similar food safety plan",
        ],
        "requirements": [
            "Menu proposal aligned with the event/contract duration",
            "Staffing plan (chefs, servers, kitchen staff)",
            "Equipment and logistics plan",
        ],
        "differentiators": [
            "Provide sample menus with pricing",
            "Highlight any dietary or cultural accommodation",
            "Offer flexibility for changing guest numbers",
        ],
        "pitfalls": [
            "No COA = automatic disqualification.",
            "Missing food handler medicals on bid day is fatal.",
        ],
    },
    "events": {
        "certifications": ["Event safety certification", "Public liability insurance"],
        "documents": [
            "Public liability insurance certificate",
            "Event safety plan",
            "Staff qualification records (event coordinators)",
        ],
        "requirements": [
            "Demonstrated event management experience",
            "Logistics, venue, and vendor coordination plan",
            "Contingency and risk management plan",
        ],
        "differentiators": [
            "List past events of similar size/scope",
            "Provide a detailed project timeline",
            "Mention any media or marketing partnerships",
        ],
        "pitfalls": [
            "No public liability cover = disqualified.",
        ],
    },
    "security": {
        "certifications": ["PSIRA registration", "Grade A/B/C officers"],
        "documents": [
            "PSIRA registration certificate",
            "Staff vetting records (criminal checks)",
            "Public liability insurance",
        ],
        "requirements": [
            "Guarding staff deployment plan",
            "Control room / monitoring capabilities (if required)",
            "Emergency response protocol",
        ],
        "differentiators": [
            "Highlight armed vs unarmed response times",
            "List technology used (CCTV, access control, etc.)",
            "Mention any specialised capabilities (K9, etc.)",
        ],
        "pitfalls": [
            "No PSIRA = automatic disqualification.",
        ],
    },
    "consulting": {
        "certifications": ["Relevant professional body registration"],
        "documents": [
            "Consultant CVs and qualification certificates",
            "Previous similar project references",
            "Professional indemnity insurance",
        ],
        "requirements": [
            "Demonstrated subject matter expertise",
            "Proposed methodology and deliverables",
            "Project timeline and milestones",
        ],
        "differentiators": [
            "Provide a detailed methodology framework",
            "Include a case study of a similar engagement",
            "Offer post-engagement support",
        ],
        "pitfalls": [
            "Generic methodology = low functionality score.",
        ],
    },
    "training": {
        "certifications": ["Accredited training provider", "SETQAA / QCTO accreditation"],
        "documents": [
            "Accreditation certificate",
            "Facilitator qualifications",
            "Course materials outline",
        ],
        "requirements": [
            "Curriculum aligned with learning outcomes",
            "Trainer-to-learner ratios",
            "Assessment and certification methodology",
        ],
        "differentiators": [
            "Provide sample training materials",
            "Highlight practical/hands-on components",
            "Offer post-training support",
        ],
        "pitfalls": [
            "No accreditation = disqualified on SETA-funded programmes.",
        ],
    },
    "logistics": {
        "certifications": ["Fleet management certification", "Driver PDIs"],
        "documents": [
            "Vehicle registration and roadworthy certificates",
            "Driver licence and PDP records",
            "Goods-in-transit insurance",
        ],
        "requirements": [
            "Fleet capacity and route plan",
            "Tracking and reporting capability",
            "Contingency and backup vehicle plan",
        ],
        "differentiators": [
            "Highlight real-time tracking capabilities",
            "List previous similar routes/contracts",
            "Offer green/fuel-efficient options",
        ],
        "pitfalls": [
            "Missing PDPs on driver files = disqualified.",
        ],
    },
    "generic": {
        "certifications": [],
        "documents": [],
        "requirements": ["Demonstrated capability to deliver the tender scope"],
        "differentiators": ["Highlight relevant experience and capacity"],
        "pitfalls": ["No mandatory certifications detected — verify the tender document."],
    },
}


# Universal SA tender document baseline — always present
STANDARD_DOCUMENTS = [
    "Company registration certificate (CIPC)",
    "Valid Tax Compliance Status (SARS) — PIN must be active on submission date",
    "B-BBEE certificate or sworn affidavit (valid at closing date)",
    "Valid Central Supplier Database (CSD) registration — must reflect current B-BBEE level",
    "Company bank confirmation letter (not older than 3 months)",
    "Company profile (5–10 pages, include organogram)",
    "Completed and signed tender forms (SBD 1, 4, 6.1, 8, 9 as applicable)",
    "Pricing schedule completed and signed",
    "Audited financial statements (last 2–3 years) or affidavit for new entities",
    "Relevant industry experience and track record",
    "Proof of previous successful projects (completion certificates)",
    "Client reference letters (minimum 3 from similar projects)",
    "Qualified and experienced staff — CVs and qualification certificates",
    "Relevant professional licences and certifications",
    "Business insurance and liability cover (per tender minimum)",
    "Health and safety compliance documents (where applicable)",
    "Proof of financial capacity (bank statements, facilities)",
    "Detailed technical proposal or project plan",
    "Clear delivery timeline (Gantt or milestone table)",
    "Required equipment, tools and resources — proof of ownership/lease",
]


# ============================================================
# Utility detectors
# ============================================================
def _has(text: str, *words: str) -> bool:
    return any(w.lower() in text for w in words)


def _extract_grading(text: str) -> str | None:
    m = re.search(r'\b(\d{1,2})\s*(CE|EP|GB|EB|SB|SG|SK|ME|EE)\b', text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"
    return None


def _extract_amount(text: str) -> str | None:
    m = re.search(r'R\s*([\d][\d\s,\.]{3,})\s*(million|m\b|billion|b\b)?', text, re.IGNORECASE)
    if m:
        return m.group(0).strip()
    return None


def _extract_quote(text: str, keyword: str, window: int = 120) -> str | None:
    """Return a quote around the first occurrence of keyword, if any."""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return None
    start = max(0, idx - window // 2)
    end = min(len(text), idx + window // 2)
    snippet = text[start:end].strip().replace("\n", " ")
    return snippet


def _days_until(closing_date: str | None) -> int | None:
    if not closing_date:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d", "%d %B %Y", "%d/%m/%Y",
    ]
    s = str(closing_date).replace("Z", "")
    for fmt in formats:
        try:
            dt = datetime.strptime(s[:len(fmt) + 8], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = dt - datetime.now(timezone.utc)
            return delta.days
        except Exception:
            continue
    return None


def detect_industry(tender: dict, profile: dict) -> str:
    text = " ".join(filter(None, [
        tender.get("title", ""),
        tender.get("description", ""),
        tender.get("category_name", ""),
    ])).lower()

    if _has(text, "construction", "building", "civil works", "road", "bridge", "cement"):
        return "construction"
    if _has(text, "it ", "ict", "software", "cloud", "network", "cyber", "system", "database", "application"):
        return "it_services"
    if _has(text, "cleaning", "hygiene", "sanitation", "janitorial"):
        return "cleaning"
    if _has(text, "catering", "food", "meals", "kitchen"):
        return "catering"
    if _has(text, "event", "conference", "exhibition", "function"):
        return "events"
    if _has(text, "security", "guarding", "cctv", "access control"):
        return "security"
    if _has(text, "consulting", "advisory", "consultancy"):
        return "consulting"
    if _has(text, "training", "workshop", "capacity building", "learnership"):
        return "training"
    if _has(text, "logistics", "transport", "distribution", "fleet"):
        return "logistics"

    industries = " ".join(profile.get("industries") or []).lower()
    for key, _val in INDUSTRY_PROFILES.items():
        if key.replace("_", " ") in industries:
            return key

    return "generic"


# ============================================================
# Builders
# ============================================================
def _build_executive_summary(tender, profile, score, industry, days):
    business = profile.get("business_name", "your business")
    org = tender.get("organisation_name") or tender.get("organisation") or "the client"
    title = (tender.get("title") or "this tender").strip()
    industry_label = industry.replace("_", " ").title()

    if score >= 70:
        verdict = "an excellent match"
    elif score >= 50:
        verdict = "a strong match"
    elif score >= 30:
        verdict = "a moderate match"
    else:
        verdict = "a marginal match"

    timing = ""
    if days is not None:
        if days < 0:
            timing = " The closing date has already passed — verify before proceeding."
        elif days == 0:
            timing = " Closing is TODAY."
        elif days <= 3:
            timing = f" Only {days} day(s) left until closing — move fast."
        elif days <= 14:
            timing = f" {days} days until closing — this is urgent but doable."
        else:
            timing = f" You have {days} days — enough time for a quality submission."

    return (
        f"This tender from {org} is {verdict} for {business} "
        f"(suitability score: {score}/100) in the {industry_label} space. "
        f"Scope: {title}.{timing}"
    )


def _build_why_this_fits(tender, profile, match_reasons):
    why = list(match_reasons or [])

    if profile.get("services"):
        why.append(
            "Your services directly align with the tender scope: " +
            ", ".join(profile["services"][:5])
        )
    if profile.get("industries"):
        why.append(
            "Your industry focus matches the tender category: " +
            ", ".join(profile["industries"][:3])
        )
    if profile.get("certifications"):
        why.append(
            "Your certifications strengthen your bid: " +
            ", ".join(profile["certifications"])
        )
    if profile.get("service_areas"):
        why.append(
            "Your service areas cover: " + ", ".join(profile["service_areas"])
        )
    if not why:
        why.append("Some overlap detected between your profile and this tender.")
    return why


def _build_key_requirements(tender, profile, industry):
    text = " ".join(filter(None, [
        tender.get("title", ""),
        tender.get("description", ""),
        tender.get("special_conditions", ""),
    ])).lower()

    reqs: list[str] = list(INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["generic"])["requirements"])

    if _has(text, "cidb"):
        grade = _extract_grading(text)
        if grade:
            reqs.append(
                f"CIDB grading {grade} required. "
                f"Compare against your own CIDB grading — if lower, consider a JV or subcontract."
            )
        else:
            reqs.append("CIDB registration required — grading not explicitly stated in the advert. Request clarification.")

    if _has(text, "briefing", "compulsory"):
        reqs.append("Compulsory briefing session — attendance is mandatory. Non-attendance = disqualification.")

    if _has(text, "experience", "track record", "years"):
        m = re.search(r'(\d+)\s*\+?\s*years?', text)
        if m:
            reqs.append(f"Minimum {m.group(1)} years of relevant experience required.")
        else:
            reqs.append("Demonstrated relevant experience is required.")

    if _has(text, "turnover", "financial", "financial statements"):
        amount = _extract_amount(tender.get("description", ""))
        reqs.append(
            f"Financial capacity proof{f' (tender value ~{amount})' if amount else ''} — "
            "usually audited financials for last 2–3 years."
        )

    if _has(text, "80/20", "90/10", "preference point"):
        reqs.append("Preference point system applies — B-BBEE level directly affects your score.")

    if _has(text, "functionality"):
        reqs.append("Functionality evaluation applies — you must hit the minimum threshold to progress to price.")

    if _has(text, "local", "smmE", "small business"):
        reqs.append("SMME / local business preference noted — emphasise locality in your proposal.")

    # Dedup
    seen, unique = set(), []
    for r in reqs:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def _build_documents(tender, industry, profile):
    text = " ".join(filter(None, [
        tender.get("title", ""),
        tender.get("description", ""),
        tender.get("special_conditions", ""),
    ])).lower()

    docs = list(STANDARD_DOCUMENTS)

    for d in INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["generic"])["documents"]:
        if d not in docs:
            docs.append(d)

    optional = {
        "insurance": "Business insurance and liability cover certificate",
        "health": "Health and safety compliance documents",
        "financial": "Audited financial statements (last 2–3 years)",
        "equipment": "Proof of equipment ownership or lease agreements",
        "track record": "Proof of previous successful projects (project list + completion certificates)",
        "reference": "Client reference letters (minimum 3 from similar projects)",
        "certification": "Relevant professional licences and certifications",
        "training": "Staff training records and qualifications",
    }
    for key, doc in optional.items():
        if key in text and doc not in docs:
            docs.append(doc)

    for cert in profile.get("certifications") or []:
        entry = f"Copy of {cert}"
        if entry not in docs:
            docs.append(entry)

    return docs


def _build_winning_strategy(tender, profile, industry):
    text = " ".join(filter(None, [tender.get("title", ""), tender.get("description", "")])).lower()

    strategy = [
        "Read the tender document twice — highlight every 'must', 'shall', and 'minimum'.",
        "Answer every question in the order it is asked. Do not skip or merge sections.",
        "Match your pricing to the market — check recent similar awards if listed.",
    ]

    strategy.extend(INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["generic"])["differentiators"])

    if _has(text, "briefing", "compulsory"):
        strategy.append(
            "Attend the compulsory briefing. Take notes of verbal clarifications — "
            "these can be used in your proposal and may not be in writing."
        )
    if _has(text, "track record", "experience"):
        strategy.append(
            "Lead with your most relevant past project. Provide numbers: value, "
            "duration, client, and measurable outcome."
        )
    if _has(text, "local", "smmE", "preference point"):
        strategy.append(
            "Emphasise your local presence and SMME status. Attach proof of local "
            "registration and premises."
        )
    if _has(text, "bbbee", "b-bbee"):
        strategy.append(
            "Maximise B-BBEE points. If your level can be improved through a JV "
            "or subcontracting, note this in your proposal."
        )
    if _has(text, "innovation", "solution"):
        strategy.append(
            "Propose a clearly-named solution or methodology. Give it a short, "
            "memorable title so evaluators remember it."
        )

    for service in (profile.get("services") or [])[:5]:
        if service.lower() in text:
            strategy.append(
                f"Your {service} capability is directly relevant — dedicate a section "
                f"of the proposal to it with examples."
            )

    # Dedup
    seen, unique = set(), []
    for s in strategy:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def _build_differentiators(tender, profile, industry):
    items = []

    if profile.get("certifications"):
        items.append(
            "Your certifications — " + ", ".join(profile["certifications"]) +
            " — signal compliance and quality. Lead with them."
        )
    if profile.get("services"):
        items.append(
            "Your core services — " + ", ".join(profile["services"][:5]) +
            " — map each one to a specific tender requirement."
        )
    if profile.get("service_areas"):
        items.append(
            "Your service areas — " + ", ".join(profile["service_areas"]) +
            " — especially valuable if the tender prioritises local providers."
        )
    if profile.get("business_name"):
        items.append(
            f"Position {profile['business_name']} as a specialist, not a generalist. "
            "Explain why your focus matters for this tender."
        )

    for d in INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["generic"])["differentiators"]:
        if d not in items:
            items.append(d)

    if not items:
        items.append(
            "Emphasise any experience, qualifications, or past work directly relevant to the tender scope."
        )
    return items


def _build_gaps(tender, profile, industry):
    gaps = []
    text = " ".join(filter(None, [
        tender.get("title", ""), tender.get("description", ""), tender.get("special_conditions", ""),
    ])).lower()

    tender_province = (tender.get("province") or "").strip()
    profile_areas = profile.get("service_areas") or []
    if tender_province and profile_areas and tender_province not in profile_areas:
        gaps.append(
            f"Province mismatch: tender is in {tender_province}, your profile lists "
            f"{', '.join(profile_areas)}. Consider a JV with a local provider or explain "
            f"your delivery capability there."
        )

    if not profile.get("certifications"):
        gaps.append(
            "No certifications on your profile. If you hold any (B-BBEE, ISO, "
            "industry-specific), add them — they are scored."
        )
    if not profile.get("contact_email"):
        gaps.append(
            "No contact email on your profile. Tenders often need a dedicated contact "
            "for clarification questions."
        )

    if _has(text, "cidb"):
        gaps.append("CIDB required — verify your grading is current and covers the full scope.")
    if _has(text, "briefing", "compulsory"):
        gaps.append("Compulsory briefing — if you can't attend, you can't bid. Confirm early.")
    if _has(text, "insurance"):
        gaps.append("Check your public liability cover meets the tender minimum — top up now if needed.")
    if _has(text, "tax", "compliance"):
        gaps.append("Verify your SARS Tax Compliance PIN is valid for the submission date.")

    for p in INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["generic"]).get("pitfalls", []):
        if p not in gaps:
            gaps.append(p)

    if not gaps:
        gaps.append(
            "No critical gaps detected. Double-check the tender document for anything "
            "not captured here."
        )
    return gaps


def _build_next_steps(tender, score, days):
    steps = []
    if days is not None and days <= 7:
        steps.append(f"URGENT: only {days} days to closing — plan your submission now.")
    steps.extend([
        "Download and read the full tender document twice.",
        "Verify all mandatory documents are current (especially SARS, CSD, B-BBEE).",
        "Confirm closing date and time — late submissions are rejected.",
        "Plan to submit 24 hours before the deadline.",
    ])
    if _has((tender.get("description") or "").lower(), "briefing"):
        steps.insert(2, "Register for the compulsory briefing session.")
    if score >= 50:
        steps.append("Strong match — allocate dedicated time to a high-quality proposal.")
    else:
        steps.append("Moderate match — evaluate effort vs reward before committing.")
    return steps


def _build_deadlines(tender, days):
    out = {}
    closing = tender.get("closing_date")
    if closing:
        out["closing_date"] = str(closing)
    if days is not None:
        out["days_remaining"] = str(days)
    return out


def _build_evidence(tender, industry):
    text = " ".join(filter(None, [
        tender.get("title", ""), tender.get("description", ""), tender.get("special_conditions", ""),
    ]))

    evidence = {}
    for keyword, label in [
        ("cidb", "cidb"),
        ("briefing", "briefing"),
        ("experience", "experience"),
        ("turnover", "turnover"),
        ("80/20", "preference_points"),
        ("90/10", "preference_points"),
        ("functionality", "functionality"),
    ]:
        q = _extract_quote(text, keyword)
        if q:
            evidence[label] = q
    return evidence


# ============================================================
# Main entry point
# ============================================================
def generate_bid_strategy(tender, profile, match_reasons=None, score=0):
    match_reasons = match_reasons or []
    industry = detect_industry(tender, profile)
    days = _days_until(tender.get("closing_date"))

    return {
        "model": "rule-based-v2",
        "suitability_score": score,
        "industry_detected": industry.replace("_", " ").title(),
        "summary": _build_executive_summary(tender, profile, score, industry, days),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "why_this_fits": _build_why_this_fits(tender, profile, match_reasons),
        "key_requirements": _build_key_requirements(tender, profile, industry),
        "documents_to_prepare": _build_documents(tender, industry, profile),
        "winning_strategy": _build_winning_strategy(tender, profile, industry),
        "differentiators_to_highlight": _build_differentiators(tender, profile, industry),
        "gaps_to_address": _build_gaps(tender, profile, industry),
        "next_steps": _build_next_steps(tender, score, days),
        "deadlines": _build_deadlines(tender, days),
        "evidence": _build_evidence(tender, industry),
    }