"""
Synonym expansion for tender matching.

Expands service / industry keywords into related words so that
"cloud hosting" also matches "cloud", "hosting", "iaas", "paas".
"""

SERVICE_SYNONYMS = {
    # ---- IT / Cloud ----
    "cloud hosting": ["cloud", "hosting", "iaas", "paas", "saas", "infrastructure as a service"],
    "cloud services": ["cloud", "saas", "cloud computing"],
    "isp": ["internet", "broadband", "connectivity", "fibre", "fiber", "isp"],
    "internet service": ["internet", "broadband", "connectivity", "fibre", "isp"],
    "network design": ["network", "infrastructure", "lan", "wan"],
    "network installation": ["network", "cabling", "infrastructure"],
    "cybersecurity": ["security", "cyber", "infosec", "soc", "penetration"],
    "managed it": ["it support", "managed services", "helpdesk", "end user computing"],
    "it support": ["helpdesk", "managed", "end user", "it services"],
    "software development": ["software", "application", "development", "programming"],
    "web development": ["web", "website", "portal", "frontend"],
    "app development": ["app", "application", "mobile", "android", "ios"],
    "data centre": ["data center", "datacenter", "hosting", "colocation"],
    "disaster recovery": ["disaster", "recovery", "backup", "continuity"],
    "backup": ["backup", "storage", "archiving", "recovery"],

    # ---- Cleaning / Facilities ----
    "cleaning services": ["cleaning", "hygiene", "sanitation", "janitorial"],
    "office cleaning": ["cleaning", "hygiene", "office"],
    "facilities management": ["facilities", "maintenance", "building management"],
    "security services": ["security", "guarding", "manned guarding", "physical security"],
    "guarding": ["guarding", "security", "patrol", "access control"],

    # ---- Catering / Events ----
    "catering": ["catering", "food", "meals", "hospitality", "kitchen"],
    "food services": ["food", "catering", "meals", "kitchen"],
    "events management": ["events", "event", "conference", "exhibition"],
    "event coordination": ["events", "coordination", "conference", "logistics"],

    # ---- Training / Consulting ----
    "training": ["training", "workshop", "capacity building", "skills"],
    "consulting": ["consulting", "advisory", "consultancy"],
    "strategy consulting": ["strategy", "consulting", "advisory"],

    # ---- Construction / Engineering ----
    "construction": ["construction", "building", "civil", "infrastructure", "roads", "site"],
    "building": ["building", "construction", "civil", "infrastructure"],
    "civil engineering": ["civil", "engineering", "infrastructure", "roads", "bridges", "earthworks"],
    "structural engineering": ["structural", "engineering", "concrete", "steel"],
    "electrical engineering": ["electrical", "engineering", "power", "wiring", "substation"],
    "mechanical engineering": ["mechanical", "engineering", "hvac", "plant"],
    "renovation": ["renovation", "refurbishment", "upgrade", "remodel", "maintenance"],
    "plumbing": ["plumbing", "pipefitting", "sanitary", "water", "drainage"],
    "hvac": ["hvac", "air conditioning", "ventilation", "refrigeration"],
    "roads": ["roads", "roadworks", "paving", "surfacing", "tar"],
    "electrical": ["electrical", "power", "energy", "wiring"],

    # ---- Environmental / Professional ----
    "environmental": ["environmental", "waste", "recycling", "sustainability", "impact"],
    "procurement": ["procurement", "supply", "sourcing", "tendering"],
    "education": ["education", "training", "school", "learnership", "curriculum"],
    "legal services": ["legal", "litigation", "compliance", "contracts"],
    "auditing": ["audit", "auditing", "assurance", "review"],
    "accounting": ["accounting", "bookkeeping", "financial", "tax"],

    # ---- Marketing / Media ----
    "marketing": ["marketing", "advertising", "promotion", "campaign"],
    "social media": ["social media", "digital marketing", "content", "online"],
    "media": ["media", "broadcasting", "communication", "advertising"],
    "graphic design": ["graphic", "design", "branding", "creative"],

    # ---- Logistics / Transport ----
    "logistics": ["logistics", "transport", "distribution", "freight", "fleet"],
    "transport": ["transport", "logistics", "freight", "haulage", "fleet"],

    # ---- Health / Safety ----
    "health and safety": ["health", "safety", "ohs", "ohsa", "compliance"],
    "first aid": ["first", "aid", "emergency", "medical"],

    # ---- Generic catch-all for common profile verb/nouns ----
    "supply": ["supply", "supplying", "provision", "delivery"],
    "installation": ["installation", "install", "fitting", "commissioning"],
    "maintenance": ["maintenance", "servicing", "repairs", "upkeep"],
    "repairs": ["repairs", "maintenance", "servicing", "fixing"],
}


INDUSTRY_SYNONYMS = {
    "information technology": ["it", "ict", "technology", "software", "digital"],
    "cloud computing": ["cloud", "hosting", "iaas", "paas", "saas"],
    "telecommunications": ["telecom", "network", "communication", "isp"],
    "media": ["media", "communication", "advertising", "broadcasting"],
    "marketing": ["marketing", "advertising", "brand", "communication"],
    "catering": ["catering", "food", "hospitality", "kitchen"],
    "construction": ["construction", "building", "civil", "infrastructure", "roads"],
    "civil engineering": ["civil", "engineering", "infrastructure", "roads", "bridges"],
    "electrical": ["electrical", "power", "energy", "wiring"],
    "mechanical": ["mechanical", "engineering", "plant", "hvac"],
    "environmental": ["environmental", "waste", "sustainability", "impact"],
    "education": ["education", "training", "school", "learnership"],
    "procurement": ["procurement", "supply", "sourcing"],
    "healthcare": ["health", "medical", "clinic", "hospital"],
    "security": ["security", "guarding", "protection"],
    "cleaning": ["cleaning", "hygiene", "sanitation"],
    "logistics": ["logistics", "transport", "freight", "distribution"],
    "training": ["training", "workshop", "learnership", "skills"],
    "consulting": ["consulting", "advisory", "consultancy"],
}


def expand_services(services: list[str]) -> set[str]:
    """Return all synonyms of the given services, plus fuzzy fallbacks."""
    expanded = set()
    for s in services:
        key = s.lower().strip()
        expanded.add(key)

        # exact synonym lookup
        for syn in SERVICE_SYNONYMS.get(key, []):
            expanded.add(syn)

        # fuzzy fallback: if the exact key isn't in the dict, try to find
        # any synonym entry whose key is a substring of this service, or
        # vice versa. Handles "Civil Engineering" vs "civil engineering".
        if key not in SERVICE_SYNONYMS:
            for syn_key, syn_values in SERVICE_SYNONYMS.items():
                if syn_key in key or key in syn_key:
                    for syn in syn_values:
                        expanded.add(syn)

        # also split multi-word services so "civil engineering" yields
        # "civil" and "engineering" as separate searchable terms
        for word in key.split():
            if len(word) > 3:
                expanded.add(word)

    return expanded


def expand_industries(industries: list[str]) -> set[str]:
    """Return all synonyms of the given industries, plus fuzzy fallbacks."""
    expanded = set()
    for i in industries:
        key = i.lower().strip()
        expanded.add(key)

        for syn in INDUSTRY_SYNONYMS.get(key, []):
            expanded.add(syn)

        if key not in INDUSTRY_SYNONYMS:
            for syn_key, syn_values in INDUSTRY_SYNONYMS.items():
                if syn_key in key or key in syn_key:
                    for syn in syn_values:
                        expanded.add(syn)

        for word in key.split():
            if len(word) > 3:
                expanded.add(word)

    return expanded