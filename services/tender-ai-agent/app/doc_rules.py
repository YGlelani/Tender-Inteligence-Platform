"""
Rule-based reading of compliance documents from their pdfplumber text.

Runs on every text PDF: it is instant and free, fills in fields the LLM missed,
and keeps uploads working when the LLM is unavailable. Output has the same
shape as the LLM extraction so validation treats both the same way.
"""
import re
from datetime import date, datetime

from .doc_catalog import DOCUMENT_TYPES

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_RE = re.compile(
    rf"\b(\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}"
    rf"|\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{4}}"
    rf"|\d{{1,2}}\s+(?:{MONTHS})[a-z]*\.?\s+\d{{4}}"
    rf"|(?:{MONTHS})[a-z]*\.?\s+\d{{1,2}},?\s+\d{{4}})\b",
    re.I,
)

# Words that identify each document type, used to spot a document in the wrong slot.
TYPE_KEYWORDS = {
    "company_registration": ["cipc", "companies and intellectual property", "cor14.3", "cor 14.3", "registration certificate", "enterprise name"],
    "director_id": ["identity document", "identity number", "republic of south africa", "id no", "certified a true copy", "commissioner of oaths"],
    "tax_compliance": ["tax compliance status", "tcs pin", "sars", "south african revenue service"],
    "csd_report": ["central supplier database", "csd", "supplier number", "maaa"],
    "bbbee": ["b-bbee", "bbbee", "broad-based black economic empowerment", "sworn affidavit", "verification certificate"],
    "bank_confirmation": ["confirmation of banking details", "account confirmation", "bank confirmation", "confirm that"],
    "bank_statement": ["statement period", "opening balance", "closing balance", "bank statement", "transaction"],
    "proof_of_address": ["municipal", "rates", "account statement", "lease agreement", "utility", "electricity", "water"],
    "coida": ["compensation fund", "coida", "letter of good standing"],
    "uif": ["unemployment insurance", "uif"],
    "financial_statements": ["annual financial statements", "statement of financial position", "income statement", "auditor"],
    "cidb": ["construction industry development board", "cidb", "crs number", "grading"],
    "psira": ["private security industry regulatory authority", "psira"],
    "professional_registration": ["ecsa", "sacap", "sacqsp", "saica", "legal practice council", "hpcsa", "professional registration"],
    "insurance": ["policy number", "insurer", "public liability", "professional indemnity", "sum insured"],
}

BANKS = ["ABSA", "FNB", "First National Bank", "Standard Bank", "Nedbank", "Capitec", "Investec",
         "TymeBank", "African Bank", "Discovery Bank", "Bidvest Bank", "Bank Zero"]


def to_iso(value: str) -> str | None:
    value = re.sub(r"\s+", " ", value.strip().replace(",", ""))
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value.replace("Sept", "Sep"), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _date_after(text: str, labels: str) -> str | None:
    """First date within ~60 characters after one of the labels."""
    m = re.search(rf"(?:{labels})[^\n]{{0,60}}?{DATE_RE.pattern}", text, re.I)
    return to_iso(m.group(1)) if m else None


def _after(text: str, labels: str, value: str = r"[^\n]{2,80}") -> str | None:
    m = re.search(rf"(?:{labels})\s*[:\-]?\s*({value})", text, re.I)
    return m.group(1).strip(" .:-") if m else None


def _sa_ids(text: str) -> list[str]:
    from .doc_ai import sa_id_valid
    return [n for n in dict.fromkeys(re.findall(r"(?<!\d)(\d{13})(?!\d)", re.sub(r"(?<=\d) (?=\d)", "", text))) if sa_id_valid(n)]


def detect_type(text: str) -> tuple[str, int]:
    lower = text.lower()
    scores = {key: sum(lower.count(word) for word in words) for key, words in TYPE_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best, scores[best]


def extract(doc_type_key: str, text: str) -> dict:
    fields: dict = {}
    reg = re.search(r"\b((?:19|20)\d{2}/\d{6}/\d{2})\b", text)
    csd = re.search(r"\b(MAAA\d{7})\b", text, re.I)
    level = re.search(r"\blevel\s*[:\-]?\s*([1-8])\b", text, re.I)
    expiry = _date_after(text, r"expir\w*|valid\s+(?:until|to|till)|date of expiry")
    issue = _date_after(text, r"date\s+of\s+issue|issue\s+date|issued(?:\s+on)?|date\s+issued|date\s+printed"
                              r"|letter\s+date|statement\s+date|dated|(?m:^)\s*date\b")

    if doc_type_key == "company_registration":
        fields["registration_number"] = reg.group(1) if reg else None
        fields["company_name"] = _after(text, r"enterprise name|company name|name of company")
        fields["registration_date"] = _date_after(text, r"registration date|date of registration|incorporat\w*")
        fields["status"] = _after(text, r"enterprise status|status", r"[A-Za-z ]{3,40}")
        fields["directors"] = [{"name": None, "id_number": n} for n in _sa_ids(text)]
    elif doc_type_key == "director_id":
        ids = _sa_ids(text)
        fields["id_number"] = ids[0] if ids else None
        fields["full_name"] = _after(text, r"names?|surname", r"[A-Za-z][A-Za-z '\-]{2,60}")
        fields["certification_date"] = _date_after(text, r"certified|commissioner|true copy")
    elif doc_type_key == "tax_compliance":
        fields["tcs_pin"] = _after(text, r"\bpin\b", r"[A-Z0-9]{10}")
        fields["taxpayer_name"] = _after(text, r"taxpayer name|taxpayer|name of taxpayer")
        status = re.search(r"\b(non[\s-]?compliant|compliant)\b", text, re.I)
        fields["compliance_status"] = status.group(1).title() if status else None
        fields["tax_reference_number"] = _after(text, r"tax reference(?: number| no)?|income tax", r"\d{10}")
    elif doc_type_key == "csd_report":
        fields["supplier_number"] = csd.group(1).upper() if csd else None
        fields["registration_number"] = reg.group(1) if reg else None
        fields["legal_name"] = _after(text, r"legal name|supplier name")
        fields["bbbee_level"] = int(level.group(1)) if level else None
        tax = re.search(r"tax\s+(?:compliance\s+)?status[^\n]{0,20}?\b(non[\s-]?compliant|compliant)\b", text, re.I)
        fields["tax_status"] = tax.group(1).title() if tax else None
        fields["report_date"] = issue
    elif doc_type_key == "bbbee":
        fields["bbbee_level"] = int(level.group(1)) if level else None
        fields["document_kind"] = "affidavit" if re.search(r"affidavit", text, re.I) else "certificate"
        fields["entity_name"] = _after(text, r"entity name|name of entity|enterprise name|company name")
        own = re.search(r"black\s+ownership[^\n\d]{0,30}(\d{1,3}(?:[.,]\d+)?)\s*%", text, re.I)
        fields["black_ownership_percent"] = float(own.group(1).replace(",", ".")) if own else None
    elif doc_type_key in ("bank_confirmation", "bank_statement"):
        fields["bank_name"] = next((b for b in BANKS if re.search(rf"\b{re.escape(b)}\b", text, re.I)), None)
        acc = re.search(r"account\s*(?:number|no\.?|#)\s*[:\-]?\s*(\d[\d\s]{6,16}\d)", text, re.I)
        fields["account_number"] = re.sub(r"\s", "", acc.group(1)) if acc else None
        fields["account_holder"] = _after(text, r"account holder|account name|name of account holder")
        if doc_type_key == "bank_confirmation":
            fields["branch_code"] = _after(text, r"branch code", r"\d{6}")
            fields["letter_date"] = issue
            fields["stamped"] = True if re.search(r"\bstamp", text, re.I) else None
        else:
            dates = [to_iso(d) for d in DATE_RE.findall(text)]
            dates = sorted(d for d in dates if d)
            fields["statement_period_end"] = dates[-1] if dates else None
            fields["statement_period_start"] = dates[0] if dates else None
    elif doc_type_key == "proof_of_address":
        fields["document_date"] = issue
        fields["account_in_arrears"] = True if re.search(r"\barrears?\b", text, re.I) else None
    elif doc_type_key == "cidb":
        fields["crs_number"] = _after(text, r"crs(?: number| no)?", r"\d{4,10}")
        fields["grading_designation"] = _after(text, r"grad(?:e|ing)(?: designation)?", r"\d{1,2}\s?[A-Z]{1,3}")

    if doc_type_key not in ("bank_statement",):
        fields.setdefault("expiry_date", expiry)
    fields = {k: v for k, v in fields.items() if v not in (None, [], "")}

    detected, score = detect_type(text)
    expected_score = sum(text.lower().count(w) for w in TYPE_KEYWORDS.get(doc_type_key, []))
    # Only claim a different type when the evidence is clear, to avoid false "wrong slot" errors.
    if score >= 3 and expected_score == 0 and detected != doc_type_key:
        detected_type = detected
    else:
        detected_type = doc_type_key if expected_score else "unknown"

    label = next((d["label"] for d in DOCUMENT_TYPES if d["key"] == doc_type_key), doc_type_key)
    return {
        "detected_type": detected_type,
        "fields": fields,
        "issue_date": issue,
        "expiry_date": expiry,
        "holder_name": fields.get("company_name") or fields.get("legal_name") or fields.get("entity_name")
                       or fields.get("taxpayer_name") or fields.get("account_holder") or fields.get("full_name"),
        "summary": f"{label} read from its text (basic extraction).",
        "quality_issues": [],
        "read_mode": "rules",
    }


def merge(llm: dict, rules: dict) -> dict:
    """LLM answer first; rule-based values fill whatever the LLM left empty."""
    out = dict(llm)
    fields = dict(rules.get("fields") or {})
    fields.update({k: v for k, v in (llm.get("fields") or {}).items() if v not in (None, "", [])})
    out["fields"] = fields
    for key in ("issue_date", "expiry_date", "holder_name"):
        if not out.get(key) and rules.get(key):
            out[key] = rules[key]
    return out
