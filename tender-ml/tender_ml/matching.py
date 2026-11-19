"""Find tenders whose categories overlap with the categories a company works in.

eTenders uses two overlapping category schemes, so a company and a tender rarely
share one exact label. Comparing each side's few most likely categories lets
"Construction" and "Civil engineering" work meet.
"""
from sklearn.pipeline import Pipeline

from .classifier import known_words, likely_categories_many
from .dataset import is_usable_category

# A category counts as "likely" for a company or a tender when the model gives it at least this
# probability. On held-out tenders, a likely category at 20% is the saved one about half the time,
# against about a third at 10%, where weak second guesses caused false matches.
MIN_SHARE = 0.20
# With fewer recognised words than this, the model is guessing, so the company gets no categories.
MIN_KNOWN_WORDS = 3
MAX_CACHED_TENDERS = 50_000


class CategoryMatcher:
    """Matches companies to tenders, remembering each tender's predicted categories.

    The same open tenders are matched against every company, every few minutes,
    so each tender's text is only run through the model once.
    """

    def __init__(self, pipeline: Pipeline):
        self._pipeline = pipeline
        self._tender_cache: dict[str, list[str]] = {}

    def company_categories(self, text: str) -> list[str]:
        if known_words(self._pipeline, text) < MIN_KNOWN_WORDS:
            return []
        return likely_categories_many(self._pipeline, [text], MIN_SHARE)[0]

    def tender_categories(self, texts: list[str]) -> list[list[str]]:
        unique = list(dict.fromkeys(texts))
        if len(self._tender_cache) + len(unique) > MAX_CACHED_TENDERS:
            self._tender_cache.clear()
        missing = [text for text in unique if text not in self._tender_cache]
        self._tender_cache.update(zip(missing, likely_categories_many(self._pipeline, missing, MIN_SHARE)))
        return [self._tender_cache[text] for text in texts]


def shared_category(company_categories: list[str], saved_category, predicted: list[str]) -> str | None:
    """The first of the tender's categories (saved one first) that the company also works in."""
    candidates = ([saved_category] if is_usable_category(saved_category) else []) + predicted
    return next((category for category in candidates if category in company_categories), None)
