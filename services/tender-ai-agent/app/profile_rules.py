# Copied from tender-scrapping-database/ai/profile_parser.py so the agent can read
# business profiles without the LLM (used when Azure is unavailable).
"""
Rule-based business profile parser.

Extracts structured fields from PDF text using regex and keyword matching.
No LLM. Deterministic. Fast.
"""
import re


INDUSTRY_KEYWORDS = [
    "information technology", "it services", "cloud computing", "cloud hosting",
    "telecommunications", "software development", "cybersecurity", "network",
    "construction", "civil engineering", "electrical", "mechanical",
    "consulting", "management consulting", "financial services", "banking",
    "cleaning", "facilities management", "security services", "events management",
    "training", "education", "healthcare", "medical", "logistics", "transport",
    "supply chain", "procurement", "marketing", "advertising", "media",
    "hospitality", "catering", "food services", "restaurant",
    "agriculture", "environmental", "mining",
]

SERVICE_KEYWORDS = [
    "cloud hosting", "cloud services", "isp", "internet service",
    "network design", "network installation", "cybersecurity", "managed it",
    "it support", "software development", "web development", "app development",
    "data centre", "data center", "disaster recovery", "backup",
    "consulting", "strategy consulting", "training", "workshops",
    "cleaning services", "office cleaning", "facilities management",
    "security services", "guarding", "cctv", "access control",
    "events management", "event coordination", "catering", "food services",
    "meal preparation", "menu design", "hospitality", "guest services",
    "graphic design", "marketing", "social media", "digital marketing",
    "content creation", "translation", "interpretation",
    "legal services", "auditing", "accounting", "bookkeeping",
    "payroll", "tax services",
    "civil engineering", "structural engineering", "electrical engineering",
    "construction", "building", "renovation", "plumbing", "hvac",
]

SOUTH_AFRICAN_PROVINCES = [
    "Western Cape", "Gauteng", "KwaZulu-Natal", "Eastern Cape",
    "Free State", "Limpopo", "Mpumalanga", "North West", "Northern Cape",
]


def parse_profile_from_text(text: str) -> dict:
    """
    Extract business profile fields from PDF text.
    Returns a dict compatible with BusinessProfileCreate.
    """
    text_lower = text.lower()

    # ----- Business name -----
    # Skip page markers, single words, and common noise lines
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) < 3:
            continue
        if line.startswith("[Page") or line.isdigit():
            continue
        # Skip common PDF noise
        if line.lower() in ("confidential", "table of contents", "page"):
            continue
        # Skip lines that are just numbers or all caps 1-word
        words = line.split()
        if len(words) == 1 and len(line) < 12:
            continue
        lines.append(line)

    business_name = lines[0] if lines else "Unknown Business"
    # Trim common suffixes
    business_name = re.sub(
        r'\s*\((?:pty|Pty|PTY)\s*(?:ltd|Ltd|LTD)\)\s*$', '',
        business_name
    ).strip()[:250]

    # ----- Email -----
    email_match = re.search(r'[\w\.\-]+@[\w\.\-]+\.\w+', text)
    contact_email = email_match.group(0) if email_match else None

    # ----- Website -----
    website_match = re.search(r'https?://[\w\.\-]+(?:/[\w\.\-/]*)?', text)
    website = website_match.group(0) if website_match else None

    # ----- Registration number -----
    reg_match = re.search(
        r'(?:Reg(?:istration)?\s*(?:No|Number|#)?[:\s]*)?(\d{4}/\d{6}/\d{2})',
        text, re.IGNORECASE
    )
    registration_number = reg_match.group(1) if reg_match else None

    # ----- Industries -----
    industries = []
    for keyword in INDUSTRY_KEYWORDS:
        if keyword in text_lower:
            industries.append(keyword.title())
    # de-dup
    industries = list(dict.fromkeys(industries))

    # ----- Services -----
    services = []
    for keyword in SERVICE_KEYWORDS:
        if keyword in text_lower:
            services.append(keyword.title())
    services = list(dict.fromkeys(services))

    # ----- Service areas -----
    service_areas = [p for p in SOUTH_AFRICAN_PROVINCES if p.lower() in text_lower]

    # ----- Certifications -----
    certifications = []
    cert_patterns = [
        r'B[\-\s]?BBEE\s+(?:Level\s+)?\d',
        r'ISO\s+\d{4,5}(?::\d{4})?',
        r'Cisco\s+(?:Certified\s+)?Partner',
        r'Microsoft\s+(?:Gold|Silver)\s+Partner',
        r'CompTIA\s+\w+',
        r'\bPMP\b',
        r'\bCISA\b',
        r'\bCISSP\b',
        r'\bSABS\b',
    ]
    for pattern in cert_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            certifications.append(m.group(0).strip())
    certifications = list(dict.fromkeys(certifications))

    # ----- Description -----
    desc_match = re.search(
        r'(?:about\s+us|company\s+(?:description|profile)|overview)[:\s]*\n?([\s\S]{80,600}?)(?:\n\n|\Z)',
        text, re.IGNORECASE
    )
    if desc_match:
        description = desc_match.group(1).strip()
    else:
        # Fallback: first 400 chars that aren't the name
        body = "\n".join(lines[1:])[:400]
        description = body or f"Business: {business_name}"

    # Ensure minimums for Pydantic validation
    if len(description) < 20:
        description = f"Business: {business_name}. {description}"
    if not industries:
        industries = ["General"]
    if not services:
        services = ["General services"]

    return {
        "business_name": business_name[:300],
        "registration_number": registration_number,
        "description": description[:5000],
        "industries": industries[:20],
        "services": services[:30],
        "service_areas": service_areas,
        "certifications": certifications,
        "contact_email": contact_email,
        "website": website,
    }