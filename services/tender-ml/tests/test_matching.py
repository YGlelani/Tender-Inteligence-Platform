from tender_ml.matching import CategoryMatcher, shared_category


def test_company_categories_come_from_what_the_company_does(trained_pipeline):
    matcher = CategoryMatcher(trained_pipeline)

    assert matcher.company_categories("security guarding services") == ["Security"]


def test_company_with_too_few_known_words_gets_no_categories(trained_pipeline):
    matcher = CategoryMatcher(trained_pipeline)

    assert matcher.company_categories("zebra umbrella") == []
    assert matcher.company_categories("") == []


def test_tender_categories_are_predicted_once_and_remembered(trained_pipeline):
    matcher = CategoryMatcher(trained_pipeline)
    texts = ["catering and meals for the clinic", "catering and meals for the clinic"]

    first = matcher.tender_categories(texts)
    second = matcher.tender_categories(texts[:1])

    assert first[0] == first[1] == second[0]
    assert "Catering" in first[0]


def test_shared_category_checks_the_saved_category_first():
    assert shared_category(["Construction", "Security"], "Security", ["Construction"]) == "Security"


def test_shared_category_uses_predictions_when_the_saved_one_does_not_match():
    assert shared_category(["Civil engineering"], "Construction", ["Construction", "Civil engineering"]) == (
        "Civil engineering"
    )


def test_shared_category_ignores_unusable_saved_categories():
    assert shared_category(["Uncategorised"], "Uncategorised", []) is None
    assert shared_category(["Security"], None, []) is None
