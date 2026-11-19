"""Keyword scoring: direct keyword hits first, then related synonyms."""
from .rules import clean_list, phrase_in, tokens
from .synonyms import related_terms

RELATED_SHARE = 0.6


def _direct_matches(keywords, searchable, title_tokens):
    return [
        keyword for keyword in keywords
        if phrase_in(keyword, searchable) or (
            tokens(keyword) and tokens(keyword).issubset(title_tokens)
        )
    ]


def _related_matches(keywords, searchable):
    related = []
    for keyword in keywords:
        term = next((term for term in related_terms(keyword) if phrase_in(term, searchable)), None)
        if term:
            related.append(f"{term} (for {keyword})")
    return related


def score_keywords(tally, profile, searchable, title_tokens, weight):
    keywords = clean_list(profile.get("keywords"))
    document_keywords = [value for value in clean_list(profile.get("document_keywords")) if value not in keywords]
    all_keywords = keywords + document_keywords
    if not (all_keywords and searchable):
        return

    own_matches = _direct_matches(keywords, searchable, title_tokens)
    document_matches = _direct_matches(document_keywords, searchable, title_tokens)
    matched = len(own_matches) + len(document_matches)
    if matched:
        total = len(all_keywords)
        share = 1.0 if total == 1 else 0.8 + 0.2 * (matched - 1) / (total - 1)
        tally.add(weight, weight * share)
    else:
        related = _related_matches(all_keywords, searchable)
        if related:
            tally.add(weight, weight * RELATED_SHARE, "Related to your keywords: " + ", ".join(related[:3]))
        else:
            tally.add(weight, 0)

    if own_matches:
        tally.reasons.append("Profile keyword match: " + ", ".join(own_matches[:5]))
    if document_matches:
        tally.reasons.append("Matches your business documents: " + ", ".join(document_matches[:5]))
