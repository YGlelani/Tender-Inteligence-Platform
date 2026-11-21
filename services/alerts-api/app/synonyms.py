WEB_DEVELOPMENT = "web development"
WEB_DESIGN = "web design"
WEBSITE_DEVELOPMENT = "website development"
WEB_PORTAL = "web portal"
WEBSITE_MAINTENANCE = "website maintenance"
CIVIL_WORKS = "civil works"

KEYWORD_SYNONYMS = {
    "it support": ["helpdesk", "help desk", "desktop support", "end user computing", "managed it services", "ict support", "technical support services"],
    "managed it": ["managed it services", "helpdesk", "end user computing", "ict support"],
    "website": [WEB_DEVELOPMENT, WEB_DESIGN, WEBSITE_DEVELOPMENT, WEB_PORTAL, WEBSITE_MAINTENANCE],
    "website services": [WEB_DEVELOPMENT, WEB_DESIGN, WEBSITE_DEVELOPMENT, WEB_PORTAL, WEBSITE_MAINTENANCE, "website hosting"],
    WEB_DEVELOPMENT: [WEBSITE_DEVELOPMENT, WEB_DESIGN, WEB_PORTAL, WEBSITE_MAINTENANCE],
    "software development": ["software solution", "application development", "system development", "custom software"],
    "cloud hosting": ["cloud services", "cloud computing", "iaas", "paas", "saas", "data hosting"],
    "network installation": ["network cabling", "structured cabling", "lan", "wan", "network infrastructure"],
    "cybersecurity": ["cyber security", "information security", "penetration testing", "security operations centre"],
    "office supplies": ["stationery", "office consumables", "printing paper", "toner", "office equipment"],
    "stationery": ["office supplies", "office consumables", "printing paper"],
    "administrative support": ["administration services", "back office", "secretarial services", "data capturing", "records management", "document management"],
    "data capturing": ["data capture", "data entry", "records management"],
    "cleaning services": ["cleaning", "hygiene services", "janitorial", "sanitation services"],
    "security services": ["guarding", "security guarding", "manned guarding", "access control"],
    "catering": ["catering services", "meals", "food services", "refreshments"],
    "events management": ["event management", "conference", "exhibition", "events"],
    "training": ["capacity building", "skills development", "learnership", "workshop"],
    "consulting": ["consultancy", "advisory services", "consulting services"],
    CIVIL_WORKS: ["civil engineering", "roadworks", "road construction", "earthworks", "stormwater"],
    "road maintenance": ["road repairs", "pothole", "road rehabilitation", "resurfacing", "routine road maintenance"],
    "paving": ["paved", "interlocking", "road surfacing", "resurfacing"],
    "construction": ["building works", CIVIL_WORKS, "construction works"],
    "plumbing": ["pipe replacement", "water reticulation", "sanitation", "sewer"],
    "electrical": ["electrical installation", "electrical maintenance", "wiring", "substation", "high mast lights"],
    "hvac": ["air conditioning", "ventilation", "refrigeration"],
    "renovation": ["refurbishment", "renovations"],
    "transport": ["logistics", "freight", "fleet management", "courier"],
    "marketing": ["advertising", "branding", "marketing campaign", "communication campaign"],
    "graphic design": ["branding", "design services", "printing and branding"],
    "printing": ["printing services", "branding material", "print media"],
}

INDUSTRY_SYNONYMS = {
    "information technology": ["ict", "information and communication technology", "information technology", "software", "computer equipment", "network infrastructure"],
    "construction": ["construction", CIVIL_WORKS, "building works", "roadworks"],
    "consulting": ["consulting", "consultancy", "advisory services"],
    "education and training": ["training", "learnership", "skills development", "education"],
    "healthcare": ["medical", "healthcare", "clinic", "hospital", "pharmaceutical"],
    "manufacturing": ["manufacturing", "fabrication", "production"],
    "transport and logistics": ["transport", "logistics", "freight", "fleet", "courier"],
    "security": ["security services", "guarding", "access control"],
    "professional services": ["professional services", "consulting", "accounting", "legal services", "auditing"],
}


def related_terms(keyword):
    key = " ".join(str(keyword or "").lower().split())
    terms = list(KEYWORD_SYNONYMS.get(key, []))
    if not terms:
        for name, values in KEYWORD_SYNONYMS.items():
            if name in key.split(" and ") or (len(name) > 5 and name in key):
                terms.extend(values)
    return [term for term in dict.fromkeys(terms) if term != key]


def industry_terms(industry):
    key = " ".join(str(industry or "").lower().split())
    return INDUSTRY_SYNONYMS.get(key, [key] if key else [])
