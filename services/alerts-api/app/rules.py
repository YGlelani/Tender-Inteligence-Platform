"""Text normalisation, category and CIDB-grade rules used by tender matching."""
import re
from typing import Any

CATEGORY_PREFIX = re.compile(r"^(supplies|services|works|disposals)\s*:\s*")
CIDB_CLASS = r"(?:ce|gb|me|eb|ep|s[a-q])"
GRADE = re.compile(r"(?<![a-z0-9])(\d{1,2})\s?(" + CIDB_CLASS + r")(?![a-z])")
CIDB_REQUIREMENT = re.compile(
    r"cidb[^0-9]{0,40}((?:\d{1,2}\s?" + CIDB_CLASS + r"(?![a-z])(?:\s?/\s?" + CIDB_CLASS + r"(?![a-z]))*[\s,]*(?:and|or|&)?\s*)+)"
)
REQUIRED_GRADE = re.compile(r"(\d{1,2})\s?(" + CIDB_CLASS + r"(?![a-z])(?:\s?/\s?" + CIDB_CLASS + r"(?![a-z]))*)")


def normalise(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalise(value)))


def phrase_in(phrase: str, text: str) -> bool:
    return bool(phrase) and re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None


def has_text(value: Any) -> bool:
    return bool(normalise(value))


def clean_list(values):
    seen = []
    for value in values or []:
        cleaned = normalise(value)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def _category_core(value):
    return CATEGORY_PREFIX.sub("", normalise(value)).strip()


def category_matches(wanted, category):
    tender_core = _category_core(category)
    if not tender_core:
        return False
    for value in wanted:
        core = _category_core(value)
        if not core:
            continue
        if core == tender_core or phrase_in(core, tender_core) or phrase_in(tender_core, core):
            return True
        core_tokens = {token for token in tokens(core) if len(token) > 3}
        if core_tokens and core_tokens.issubset(tokens(tender_core)):
            return True
    return False


def parse_grades(value):
    grades = {}
    for level, grade_class in GRADE.findall(normalise(value)):
        grades[grade_class] = max(grades.get(grade_class, 0), int(level))
    return grades


def cidb_requirement(text):
    found = CIDB_REQUIREMENT.search(text)
    if not found:
        return {}
    required = {}
    for level, classes in REQUIRED_GRADE.findall(found.group(1)):
        for grade_class in re.split(r"\s?/\s?", classes):
            current = required.get(grade_class)
            required[grade_class] = int(level) if current is None else min(current, int(level))
    return required


def format_requirement(required):
    return " or ".join(f"{level}{grade_class.upper()}" for grade_class, level in sorted(required.items()))
