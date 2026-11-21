import joblib
import pytest
import sklearn

from tender_ml.classifier import top_categories
from tender_ml.model_file import load_model, save_model

METRICS = {
    "test_tenders": 10, "baseline_accuracy": 0.25, "accuracy": 0.9, "top_3_accuracy": 1.0,
    "macro_f1": 0.9, "confident_share": 0.8, "confident_accuracy": 0.95, "calibration": [],
}


def test_saved_model_gives_the_same_predictions_and_keeps_its_metadata(trained_pipeline, tmp_path):
    path = tmp_path / "models" / "category_model.joblib"
    saved = save_model(trained_pipeline, path, METRICS)

    pipeline, metadata = load_model(path)
    text = "cleaning and hygiene services for the school"
    assert top_categories(pipeline, text) == top_categories(trained_pipeline, text)
    assert metadata == saved
    assert metadata["sklearn_version"] == sklearn.__version__
    assert metadata["metrics"]["top_3_accuracy"] == 1.0
    assert "calibration" not in metadata["metrics"]


def test_load_model_refuses_a_different_scikit_learn_version(trained_pipeline, tmp_path):
    path = tmp_path / "category_model.joblib"
    save_model(trained_pipeline, path, METRICS)
    bundle = joblib.load(path)
    bundle["metadata"]["sklearn_version"] = "0.0.1"
    joblib.dump(bundle, path)

    with pytest.raises(RuntimeError, match="scikit-learn 0.0.1"):
        load_model(path)


def test_load_model_refuses_a_file_from_an_older_train_py(trained_pipeline, tmp_path):
    path = tmp_path / "category_model.joblib"
    joblib.dump(trained_pipeline, path)

    with pytest.raises(RuntimeError, match="python train.py"):
        load_model(path)


def test_load_model_refuses_a_model_in_another_format(trained_pipeline, tmp_path):
    path = tmp_path / "category_model.joblib"
    save_model(trained_pipeline, path, METRICS)
    bundle = joblib.load(path)
    bundle["metadata"]["format"] = 1
    joblib.dump(bundle, path)

    with pytest.raises(RuntimeError, match="another version of train.py"):
        load_model(path)
