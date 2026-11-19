"""Compare candidate models with 5-fold cross-validation, then check them on held-out tenders.

The model used in production is chosen from the cross-validation results only, using a rule
fixed before the comparison was run (see `recommend`).

Usage:
    pip install -r requirements-experiments.txt
    python compare_models.py
"""
import json
import time

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, make_scorer, top_k_accuracy_score
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline

from tender_ml import config
from tender_ml.classifier import build_pipeline
from tender_ml.dataset import PARALLEL_FOLDS, RANDOM_STATE, load_tenders, prepare_dataset, split_dataset

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
WORD_TFIDF = "Word TF-IDF"
WORD_AND_CHARACTER_TFIDF = "Word + character TF-IDF"
# Gains needed (in top-3 accuracy) before a more complex model replaces a simpler one.
CHARACTER_GAIN_NEEDED = 0.01
EMBEDDING_GAIN_NEEDED = 0.03


def word_tfidf() -> Pipeline:
    """Words and word pairs only (the first version of the model)."""
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
            ("classifier", LogisticRegression(C=10, max_iter=3000)),
        ],
        memory=None,
    )


def embed(texts):
    """Turn each text into a 384-number meaning vector with a pre-trained sentence-transformer."""
    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer(EMBEDDING_MODEL)
    return encoder.encode(list(texts), batch_size=64, normalize_embeddings=True, show_progress_bar=False)


def cross_validated(model, features, categories) -> dict:
    """Mean and spread of each metric over 5 folds of the training tenders."""
    labels = sorted(set(categories))
    scoring = {
        "accuracy": "accuracy",
        "macro_f1": "f1_macro",
        "top_3_accuracy": make_scorer(top_k_accuracy_score, k=3, labels=labels, response_method="predict_proba"),
    }
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    scores = cross_validate(model, features, categories, cv=folds, scoring=scoring, n_jobs=PARALLEL_FOLDS)
    results = {name: _mean_and_spread(scores[f"test_{name}"]) for name in scoring}
    results["fit_seconds"] = round(float(scores["fit_time"].mean()), 1)
    return results


def _mean_and_spread(values) -> dict:
    return {"mean": round(float(values.mean()), 3), "std": round(float(values.std()), 3)}


def held_out(model, train_features, train_categories, test_features, test_categories) -> dict:
    """Train on all training tenders and score once on the held-out test tenders."""
    started = time.perf_counter()
    model.fit(train_features, train_categories)
    probabilities = model.predict_proba(test_features)
    predicted = model.classes_[probabilities.argmax(axis=1)]
    return {
        "accuracy": round(accuracy_score(test_categories, predicted), 3),
        "top_3_accuracy": round(
            top_k_accuracy_score(test_categories, probabilities, k=3, labels=model.classes_), 3
        ),
        "macro_f1": round(f1_score(test_categories, predicted, average="macro"), 3),
        "seconds": round(time.perf_counter() - started, 1),
    }


def recommend(results: dict) -> str:
    """Pick the production model with the rule fixed before the comparison."""
    top_3 = {name: result["cross_validation"]["top_3_accuracy"]["mean"] for name, result in results.items()}
    best_tfidf = WORD_TFIDF
    if top_3[WORD_AND_CHARACTER_TFIDF] >= top_3[WORD_TFIDF] + CHARACTER_GAIN_NEEDED:
        best_tfidf = WORD_AND_CHARACTER_TFIDF
    best_embedding = max(
        (name for name in top_3 if name.startswith("Sentence embeddings")), key=top_3.get
    )
    if top_3[best_embedding] >= top_3[best_tfidf] + EMBEDDING_GAIN_NEEDED:
        return best_embedding
    return best_tfidf


def write_report(results: dict, choice: str, embedding_seconds: float) -> None:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary = {"recommended": choice, "embedding_seconds": embedding_seconds, "results": results}
    (config.REPORTS_DIR / "model_comparison.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "| Model | CV accuracy | CV top-3 | CV macro F1 | Test accuracy | Test top-3 | Train + test time |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, result in results.items():
        cv, test = result["cross_validation"], result["test"]
        lines.append(
            f"| {name}{' (chosen)' if name == choice else ''} "
            f"| {_format(cv['accuracy'])} | {_format(cv['top_3_accuracy'])} | {_format(cv['macro_f1'])} "
            f"| {test['accuracy']:.1%} | {test['top_3_accuracy']:.1%} | {test['seconds']}s |"
        )
    lines.append("")
    lines.append(f"Sentence-embedding times exclude the {embedding_seconds}s spent creating the embeddings.")
    (config.REPORTS_DIR / "model_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def _format(score: dict) -> str:
    return f"{score['mean']:.1%} ± {score['std']:.1%}"


def main() -> None:
    dataset, _ = prepare_dataset(load_tenders(config.DATABASE_PATH))
    train, test = split_dataset(dataset)
    print("Creating sentence embeddings (first run downloads the model)...")
    started = time.perf_counter()
    train_vectors, test_vectors = embed(train["text"]), embed(test["text"])
    embedding_seconds = round(time.perf_counter() - started, 1)

    candidates = {
        WORD_TFIDF: (word_tfidf, train["text"], test["text"]),
        WORD_AND_CHARACTER_TFIDF: (build_pipeline, train["text"], test["text"]),  # the production model
        "Sentence embeddings (C=1)": (lambda: LogisticRegression(C=1, max_iter=3000), train_vectors, test_vectors),
        "Sentence embeddings (C=10)": (lambda: LogisticRegression(C=10, max_iter=3000), train_vectors, test_vectors),
    }
    results = {}
    for name, (make_model, train_features, test_features) in candidates.items():
        print(f"Evaluating {name}...")
        results[name] = {
            "cross_validation": cross_validated(make_model(), train_features, train["category"]),
            "test": held_out(make_model(), train_features, train["category"], test_features, test["category"]),
        }
    choice = recommend(results)
    write_report(results, choice, embedding_seconds)
    print(f"\nRecommended for production: {choice}")


if __name__ == "__main__":
    main()
