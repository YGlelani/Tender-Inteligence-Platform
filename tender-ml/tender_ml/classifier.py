"""The tender category classifier: TF-IDF text features and logistic regression."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

# Below this probability a prediction is too unreliable to fill in a category.
# train.py reports how often confident predictions are right ("confident_accuracy").
MIN_CONFIDENCE = 0.5


def build_pipeline() -> Pipeline:
    """Create an untrained model.

    Two kinds of text features are combined:
    - words and word pairs: "security services" carries more meaning than the single words;
    - character pieces (3 to 5 letters): these still match misspelt words such as "laptps".
    Word features come first, so explanations can use them alone.

    min_df=2 ignores features seen in only one tender, and sublinear_tf stops a
    repeated word from dominating a short title. C=10 (weaker regularisation than
    the default of 1) scored best in 5-fold cross-validation. compare_models.py
    chose this model over word features alone and over sentence embeddings.
    """
    features = FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("characters", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
    ])
    return Pipeline(
        [("tfidf", features), ("classifier", LogisticRegression(C=10, max_iter=3000))], memory=None
    )


def _word_features(pipeline: Pipeline) -> TfidfVectorizer:
    return pipeline.named_steps["tfidf"].named_transformers["words"]


def known_words(pipeline: Pipeline, text: str) -> int:
    """How many of the words and word pairs in `text` the model learned during training."""
    return _word_features(pipeline).transform([text]).nnz


def _ranked(pipeline: Pipeline, probabilities, limit: int) -> list[tuple[str, float]]:
    best_first = probabilities.argsort()[::-1][:limit]
    return [(str(pipeline.classes_[index]), float(probabilities[index])) for index in best_first]


def top_categories(pipeline: Pipeline, text: str, limit: int = 3) -> list[tuple[str, float]]:
    """The most likely categories for one text, best first, with their probabilities."""
    return _ranked(pipeline, pipeline.predict_proba([text])[0], limit)


def predict_category(pipeline: Pipeline, text: str, min_confidence: float = MIN_CONFIDENCE) -> str | None:
    """The best category, or None when the model is not confident enough."""
    category, probability = top_categories(pipeline, text, limit=1)[0]
    return category if probability >= min_confidence else None


def likely_categories_many(pipeline: Pipeline, texts: list[str], min_share: float, limit: int = 3) -> list[list[str]]:
    """For each text, up to `limit` categories that have at least `min_share` probability."""
    if not texts:
        return []
    return [
        [category for category, probability in _ranked(pipeline, row, limit) if probability >= min_share]
        for row in pipeline.predict_proba(texts)
    ]


def explain(pipeline: Pipeline, text: str, category: str, limit: int = 5) -> list[str]:
    """The words in `text` that pushed the model most towards `category`.

    Each word's push is its TF-IDF value times the weight the model learned for
    that word and category. Only words that pushed towards the category are listed;
    character pieces are left out because they are not readable on their own.
    """
    words = _word_features(pipeline)
    classifier = pipeline.named_steps["classifier"]
    # Word features are the first columns of the combined features.
    weights = classifier.coef_[list(classifier.classes_).index(category)][: len(words.vocabulary_)]
    features = words.transform([text]).tocoo()
    pushes = sorted(zip(features.data * weights[features.col], features.col), reverse=True)
    names = words.get_feature_names_out()
    return [str(names[column]) for push, column in pushes[:limit] if push > 0]
