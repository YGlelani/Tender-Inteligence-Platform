"""Saving and loading the trained model, with the facts needed to trust it later."""
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn
from sklearn.pipeline import Pipeline

from .classifier import MIN_CONFIDENCE

# Increase whenever build_pipeline changes shape: models saved in another format are then
# refused and replaced, because this code cannot use them.
MODEL_FORMAT = 2
# Results stored with the model, so anyone using it can see how good it is.
HEADLINE_METRICS = (
    "test_tenders", "baseline_accuracy", "accuracy", "top_3_accuracy",
    "macro_f1", "confident_share", "confident_accuracy",
)


def save_model(pipeline: Pipeline, path: Path, metrics: dict) -> dict:
    """Save the model with its format, training date, library version and results."""
    trained_at = datetime.now(timezone.utc)
    metadata = {
        "format": MODEL_FORMAT,
        "version": trained_at.strftime("%Y%m%d-%H%M%S"),
        "trained_at": trained_at.isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "categories": len(pipeline.classes_),
        "min_confidence": MIN_CONFIDENCE,
        "metrics": {name: metrics[name] for name in HEADLINE_METRICS},
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipeline, "metadata": metadata}, path)
    return metadata


def read_model(path: Path) -> dict:
    """Read a saved model file as {"pipeline": ..., "metadata": ...}.

    joblib files can run code when loaded, so only load model files you trained yourself.
    """
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or bundle.get("metadata", {}).get("format") != MODEL_FORMAT:
        raise RuntimeError(f"{path} was saved by another version of train.py. Run 'python train.py'.")
    return bundle


def load_model(path: Path) -> tuple[Pipeline, dict]:
    """Load a model, refusing one trained with a different scikit-learn version.

    A model saved by another version can fail or quietly give different answers.
    """
    bundle = read_model(path)
    trained_with = bundle["metadata"]["sklearn_version"]
    if trained_with != sklearn.__version__:
        raise RuntimeError(
            f"The model was trained with scikit-learn {trained_with}, but {sklearn.__version__} "
            "is installed. Retrain it with 'python train.py'."
        )
    return bundle["pipeline"], bundle["metadata"]
