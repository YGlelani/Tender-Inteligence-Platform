"""Load labelled tenders from the platform database and prepare them for training."""
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

UNCATEGORISED = "Uncategorised"
# Some category names are whole tender detail blocks that the scraper saved by mistake.
SCRAPER_ERROR_PREFIX = "Details:"
MIN_TENDERS_PER_CATEGORY = 20
TEST_SIZE = 0.2
# A fixed seed gives the same train/test split on every run, so results can be compared.
RANDOM_STATE = 42
# Cross-validation folds trained at the same time. Each model with character features needs a lot
# of memory: training all five folds at once exhausted a development laptop's resources.
PARALLEL_FOLDS = 2

TENDERS_QUERY = """
    SELECT t.id, t.title, t.description, o.name AS organisation, c.name AS category
    FROM tenders t
    LEFT JOIN categories c ON c.id = t.category_id
    LEFT JOIN organisations o ON o.id = t.organisation_id
"""


def load_tenders(database_path: Path) -> pd.DataFrame:
    """Read every tender with its organisation and category name.

    The database is opened read-only, so training can never change it, and a
    missing file raises an error instead of silently creating an empty database.
    """
    uri = Path(database_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return pd.read_sql_query(TENDERS_QUERY, connection)


def _clean(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def tender_text(title, description, organisation) -> str:
    """Combine the fields the model reads into one string.

    Training and prediction must both use this function so the model always
    sees text in the same shape. Most tenders repeat the title as the
    description, so an identical description is skipped. The organisation name
    is included because many organisations buy the same kinds of things; it
    raised cross-validated accuracy by about 5 percentage points.
    """
    title, description = _clean(title), _clean(description)
    parts = [title]
    if description.lower() != title.lower():
        parts.append(description)
    parts.append(_clean(organisation))
    return " ".join(part for part in parts if part)


def company_text(industries=(), services=(), keywords=(), description="") -> str:
    """Describe a company in one string, using the same kind of words tenders use.

    The model was trained on tenders, so a company is described by what it does.
    """
    parts = [*industries, *services, *keywords, description]
    return " ".join(cleaned for cleaned in map(_clean, parts) if cleaned)


def is_usable_category(category) -> bool:
    """True when the category is a real label, not missing, "Uncategorised" or a scraper error."""
    return (
        isinstance(category, str)
        and bool(category.strip())
        and category != UNCATEGORISED
        and not category.startswith(SCRAPER_ERROR_PREFIX)
    )


def has_usable_category(categories: pd.Series) -> pd.Series:
    """True where the category is a real label the model can learn from."""
    return categories.map(is_usable_category).astype(bool)


def prepare_dataset(tenders: pd.DataFrame, min_per_category: int = MIN_TENDERS_PER_CATEGORY):
    """Return the training rows (text, category) and a count of what was removed and why.

    - Tenders without a usable category cannot teach the model anything.
    - Re-advertised tenders have identical text. Keeping copies would let the same
      tender appear in both the training and test sets and overstate accuracy.
    - Categories with fewer than `min_per_category` tenders are too small to learn
      or to test reliably, so the model does not predict them.
    """
    labelled = tenders[has_usable_category(tenders["category"])]
    texts = [
        tender_text(title, description, organisation)
        for title, description, organisation in zip(
            labelled["title"], labelled["description"], labelled["organisation"]
        )
    ]
    dataset = pd.DataFrame({
        "id": labelled["id"].to_numpy(),
        "text": texts,
        "category": labelled["category"].to_numpy(),
    })
    unique = dataset.drop_duplicates(subset="text")

    counts = unique["category"].value_counts()
    kept = unique[unique["category"].isin(counts[counts >= min_per_category].index)]

    summary = {
        "tenders_loaded": len(tenders),
        "removed_no_usable_category": len(tenders) - len(labelled),
        "removed_duplicate_text": len(dataset) - len(unique),
        "removed_rare_category": len(unique) - len(kept),
        "tenders_used": len(kept),
        "categories_used": int(kept["category"].nunique()),
    }
    return kept.reset_index(drop=True), summary


def split_dataset(dataset: pd.DataFrame):
    """Hold back 20% of tenders for testing.

    stratify keeps each category's share the same in the training and test sets.
    """
    return train_test_split(
        dataset, test_size=TEST_SIZE, stratify=dataset["category"], random_state=RANDOM_STATE
    )
