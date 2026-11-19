"""Measure the trained model on held-out tenders and write the results to disk."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    classification_report,
    f1_score,
    top_k_accuracy_score,
)
from sklearn.pipeline import Pipeline

from .classifier import MIN_CONFIDENCE

CONFIDENCE_BANDS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def evaluate(pipeline: Pipeline, texts: pd.Series, categories: pd.Series, baseline_category: str):
    """Score the model on tenders it never saw during training.

    `baseline_category` is the most common training category. Always guessing it
    gives the baseline accuracy that the model has to beat.
    Returns the metrics and the predicted category for each test tender.
    """
    probabilities = pipeline.predict_proba(texts)
    predicted = pipeline.classes_[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)
    correct = predicted == categories.to_numpy()
    confident = confidence >= MIN_CONFIDENCE
    results = {
        "test_tenders": len(categories),
        "baseline_accuracy": round(float((categories == baseline_category).mean()), 3),
        "accuracy": round(accuracy_score(categories, predicted), 3),
        "top_3_accuracy": round(
            top_k_accuracy_score(categories, probabilities, k=3, labels=pipeline.classes_), 3
        ),
        "macro_f1": round(f1_score(categories, predicted, average="macro"), 3),
        "min_confidence": MIN_CONFIDENCE,
        "confident_share": round(float(confident.mean()), 3),
        "confident_accuracy": round(float(correct[confident].mean()), 3) if confident.any() else None,
        "calibration": confidence_bands(confidence, correct),
        "most_confused": most_confused(categories, predicted),
    }
    return results, predicted


def confidence_bands(confidence: np.ndarray, correct: np.ndarray) -> list[dict]:
    """How often the model is right at each level of confidence.

    A well-calibrated model that says "70% sure" is right about 70% of the time,
    which is what makes a confidence threshold meaningful.
    """
    bands = []
    last_band = len(CONFIDENCE_BANDS) - 2
    for index, (low, high) in enumerate(zip(CONFIDENCE_BANDS, CONFIDENCE_BANDS[1:])):
        # The last band also includes 100%.
        in_band = (confidence >= low) & ((confidence < high) | (index == last_band))
        if in_band.any():
            bands.append({
                "band": f"{low:.0%}-{high:.0%}",
                "tenders": int(in_band.sum()),
                "average_confidence": round(float(confidence[in_band].mean()), 3),
                "accuracy": round(float(correct[in_band].mean()), 3),
            })
    return bands


def most_confused(actual: pd.Series, predicted, limit: int = 10) -> list[dict]:
    """The category pairs the model mixes up most often."""
    pairs = pd.DataFrame({"actual": actual.to_numpy(), "predicted": predicted})
    mistakes = pairs[pairs["actual"] != pairs["predicted"]].value_counts().head(limit)
    return [
        {"actual": actual_name, "predicted": predicted_name, "count": int(count)}
        for (actual_name, predicted_name), count in mistakes.items()
    ]


def write_reports(categories: pd.Series, predicted, results: dict, folder: Path) -> None:
    """Save metrics.json, a per-category report, a confusion matrix and a calibration chart."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (folder / "classification_report.txt").write_text(
        classification_report(categories, predicted, zero_division=0), encoding="utf-8"
    )
    _plot_confusion_matrix(categories, predicted, folder / "confusion_matrix.png")
    _plot_calibration(results["calibration"], folder / "calibration.png")


def _plot_confusion_matrix(categories: pd.Series, predicted, path: Path) -> None:
    figure = Figure(figsize=(22, 22))
    axes = figure.subplots()
    ConfusionMatrixDisplay.from_predictions(
        categories, predicted, normalize="true", include_values=False,
        xticks_rotation="vertical", ax=axes, colorbar=False,
    )
    axes.set_title("Confusion matrix (share of each actual category)")
    figure.tight_layout()
    figure.savefig(path, dpi=80)


def _plot_calibration(bands: list[dict], path: Path) -> None:
    figure = Figure(figsize=(6, 5))
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1], linestyle="--", color="grey", label="Perfectly calibrated")
    axes.plot(
        [band["average_confidence"] for band in bands], [band["accuracy"] for band in bands],
        marker="o", label="Model",
    )
    axes.set_xlabel("How sure the model was")
    axes.set_ylabel("How often it was right")
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    axes.set_title("Calibration on held-out tenders")
    axes.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=100)
