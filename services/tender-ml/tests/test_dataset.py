import math
import sqlite3

import pandas as pd
import pytest

from tender_ml.dataset import (
    company_text,
    has_usable_category,
    load_tenders,
    prepare_dataset,
    split_dataset,
    tender_text,
)


def test_tender_text_skips_a_description_that_repeats_the_title():
    assert tender_text("Office Cleaning", "office cleaning", "City of Tshwane") == "Office Cleaning City of Tshwane"


def test_tender_text_keeps_a_different_description():
    assert tender_text("Cleaning", "For 36 months", "") == "Cleaning For 36 months"


def test_tender_text_handles_missing_values_and_extra_whitespace():
    assert tender_text("  Supply of\n chairs ", None, float("nan")) == "Supply of chairs"


def test_company_text_joins_what_the_company_does():
    text = company_text(["IT"], ["laptop supply", " network  installation "], [], "We serve schools.")

    assert text == "IT laptop supply network installation We serve schools."


def test_company_text_is_empty_when_nothing_is_known():
    assert company_text([], [""], [], "") == ""


def test_has_usable_category_rejects_missing_uncategorised_and_scraper_errors():
    categories = pd.Series(["Construction", None, "Uncategorised", "Details:\nTender Number: 12", "  "])
    assert has_usable_category(categories).tolist() == [True, False, False, False, False]


def _tenders(rows):
    frame = pd.DataFrame(rows, columns=["title", "description", "organisation", "category"])
    return frame.assign(id=range(1, len(frame) + 1))


def test_prepare_dataset_removes_unusable_duplicate_and_rare_rows():
    tenders = _tenders(
        [("Road repairs", None, "Roads Agency", "Civil engineering")] * 2
        + [(f"Road repairs phase {n}", None, "Roads Agency", "Civil engineering") for n in range(3)]
        + [("Laptops", None, "SITA", "Supplies: Computer Equipment")]
        + [("Unknown", None, "SITA", "Uncategorised")]
    )

    dataset, summary = prepare_dataset(tenders, min_per_category=2)

    assert set(dataset["category"]) == {"Civil engineering"}
    assert summary == {
        "tenders_loaded": 7,
        "removed_no_usable_category": 1,
        "removed_duplicate_text": 1,
        "removed_rare_category": 1,
        "tenders_used": 4,
        "categories_used": 1,
    }
    assert list(dataset.columns) == ["id", "text", "category"]


def test_split_dataset_keeps_every_category_in_both_sets(training_data):
    train, test = split_dataset(training_data)

    assert len(test) == math.ceil(len(training_data) * 0.2)  # scikit-learn rounds the test set up
    assert set(train["category"]) == set(test["category"]) == set(training_data["category"])


def test_load_tenders_joins_category_and_organisation_names(database_path):
    tenders = load_tenders(database_path).set_index("id")

    assert len(tenders) == 3
    assert tenders.loc[1, "category"] == "Security"
    assert tenders.loc[1, "organisation"] == "Department of Health"
    assert pd.isna(tenders.loc[3, "category"])


def test_load_tenders_never_creates_a_missing_database(tmp_path):
    missing = tmp_path / "missing.db"

    with pytest.raises(sqlite3.OperationalError):
        load_tenders(missing)
    assert not missing.exists()
