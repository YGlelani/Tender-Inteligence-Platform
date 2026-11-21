from tender_ml.classifier import explain, known_words, likely_categories_many, predict_category, top_categories


def test_predicts_the_category_of_a_clear_tender(trained_pipeline):
    assert predict_category(trained_pipeline, "security guarding services for the warehouse") == "Security"


def test_returns_none_when_not_confident_enough(trained_pipeline):
    assert predict_category(trained_pipeline, "security guarding services", min_confidence=1.0) is None


def test_top_categories_are_sorted_best_first(trained_pipeline):
    suggestions = top_categories(trained_pipeline, "catering and meals for the clinic", limit=2)

    assert len(suggestions) == 2
    assert suggestions[0][0] == "Catering"
    assert suggestions[0][1] >= suggestions[1][1]


def test_likely_categories_keep_only_probable_ones(trained_pipeline):
    likely = likely_categories_many(trained_pipeline, ["catering and meals for the school"], min_share=0.5)

    assert likely == [["Catering"]]
    assert likely_categories_many(trained_pipeline, [], min_share=0.5) == []


def test_explain_lists_only_whole_words_behind_a_prediction(trained_pipeline):
    words = explain(trained_pipeline, "catering and meals for the school", "Catering")

    assert "catering" in words
    assert "school" not in words
    assert all(word.strip() == word for word in words)  # no character pieces such as " cat"


def test_known_words_ignores_character_pieces(trained_pipeline):
    assert known_words(trained_pipeline, "catering and meals") >= 3
    assert known_words(trained_pipeline, "cateringly mealsome") == 0
