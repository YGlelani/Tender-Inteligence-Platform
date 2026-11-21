"""List tenders whose saved category the model strongly disagrees with.

Each tender is judged by a model that never saw it during training (5-fold
cross-validation), so the model cannot simply repeat the saved label. The list
is a starting point for checking the scraper's categories by hand: some entries
will be model mistakes, not wrong labels.

Usage:
    python audit.py
"""
import pandas as pd
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from tender_ml import config
from tender_ml.classifier import build_pipeline
from tender_ml.dataset import PARALLEL_FOLDS, RANDOM_STATE, load_tenders, prepare_dataset

MIN_CONFIDENCE_TO_FLAG = 0.8


def suspected_mislabels(dataset: pd.DataFrame, probabilities, classes) -> pd.DataFrame:
    """Tenders where the model is at least 80% sure of a different category than the saved one."""
    report = pd.DataFrame({
        "id": dataset["id"].to_numpy(),
        "text": dataset["text"].to_numpy(),
        "saved_category": dataset["category"].to_numpy(),
        "model_category": classes[probabilities.argmax(axis=1)],
        "confidence": probabilities.max(axis=1).round(3),
    })
    flagged = report[
        (report["model_category"] != report["saved_category"])
        & (report["confidence"] >= MIN_CONFIDENCE_TO_FLAG)
    ]
    return flagged.sort_values("confidence", ascending=False)


def main() -> None:
    dataset, _ = prepare_dataset(load_tenders(config.DATABASE_PATH))
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    probabilities = cross_val_predict(
        build_pipeline(), dataset["text"], dataset["category"],
        cv=folds, method="predict_proba", n_jobs=PARALLEL_FOLDS,
    )
    # cross_val_predict orders the probability columns by sorted category name.
    classes = pd.Index(sorted(dataset["category"].unique())).to_numpy()
    flagged = suspected_mislabels(dataset, probabilities, classes)

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / "suspected_mislabels.csv"
    flagged.to_csv(path, index=False)
    print(f"{len(flagged)} of {len(dataset)} tenders ({len(flagged) / len(dataset):.1%}) flagged. Saved to {path}")


if __name__ == "__main__":
    main()
