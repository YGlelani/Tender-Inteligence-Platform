import json

import numpy as np
import pandas as pd

from tender_ml.evaluation import confidence_bands, evaluate, most_confused, write_reports


def test_evaluate_scores_a_perfect_model(trained_pipeline, training_data):
    results, predicted = evaluate(
        trained_pipeline, training_data["text"], training_data["category"], baseline_category="Security"
    )

    assert list(predicted) == list(training_data["category"])
    assert results["accuracy"] == 1.0
    assert results["top_3_accuracy"] == 1.0
    assert results["baseline_accuracy"] == 0.25
    assert results["most_confused"] == []
    assert sum(band["tenders"] for band in results["calibration"]) == len(training_data)


def test_confidence_bands_report_accuracy_per_band():
    confidence = np.array([0.1, 0.3, 0.35, 0.9, 1.0])
    correct = np.array([False, True, False, True, True])

    assert confidence_bands(confidence, correct) == [
        {"band": "0%-20%", "tenders": 1, "average_confidence": 0.1, "accuracy": 0.0},
        {"band": "20%-40%", "tenders": 2, "average_confidence": 0.325, "accuracy": 0.5},
        {"band": "80%-100%", "tenders": 2, "average_confidence": 0.95, "accuracy": 1.0},
    ]


def test_most_confused_counts_each_wrong_pair():
    actual = pd.Series(["Construction", "Construction", "Construction", "Education"])
    predicted = ["Civil engineering", "Civil engineering", "Construction", "Construction"]

    assert most_confused(actual, predicted) == [
        {"actual": "Construction", "predicted": "Civil engineering", "count": 2},
        {"actual": "Education", "predicted": "Construction", "count": 1},
    ]


def test_write_reports_creates_all_report_files(tmp_path):
    actual = pd.Series(["Security", "Cleaning"])
    results = {
        "accuracy": 0.5,
        "calibration": [{"band": "40%-60%", "tenders": 2, "average_confidence": 0.5, "accuracy": 0.5}],
    }

    write_reports(actual, ["Security", "Security"], results, tmp_path / "reports")

    assert json.loads((tmp_path / "reports" / "metrics.json").read_text(encoding="utf-8")) == results
    for name in ("classification_report.txt", "confusion_matrix.png", "calibration.png"):
        assert (tmp_path / "reports" / name).exists()
