"""Train the tender category model, test it on held-out tenders and save it.

The new model only replaces the saved one when it is not worse (see `should_replace`),
so a scheduled retrain can never quietly make the platform's predictions worse.

Usage:
    python train.py            # replace the saved model only if the new one is as good
    python train.py --force    # replace it regardless

Exit codes: 0 = new model saved, 1 = could not train, 2 = kept the saved model because it is better.
"""
import argparse
import sqlite3
import sys

from tender_ml import config
from tender_ml.classifier import build_pipeline
from tender_ml.dataset import load_tenders, prepare_dataset, split_dataset
from tender_ml.evaluation import evaluate, write_reports
from tender_ml.model_file import HEADLINE_METRICS, read_model, save_model

# The new model may score at most this much lower in top-3 accuracy than the saved one.
# Small drops are normal, because each retrain is tested on a slightly different set of tenders.
ALLOWED_DROP = 0.01
# Fewer usable tenders than this means the database is broken or empty, not that data is scarce.
MIN_TRAINING_TENDERS = 1000
KEPT_SAVED_MODEL = 2


def should_replace(previous: dict | None, new: dict, force: bool = False) -> bool:
    """True when the new model's results are good enough to replace the saved model."""
    if force or previous is None:
        return True
    return new["top_3_accuracy"] >= previous["top_3_accuracy"] - ALLOWED_DROP


def saved_metrics() -> dict | None:
    """Results of the currently saved model, or None if there is no usable saved model."""
    if not config.MODEL_PATH.exists():
        return None
    try:
        return read_model(config.MODEL_PATH)["metadata"]["metrics"]
    except RuntimeError:
        return None


def _print_table(values: dict) -> None:
    for name, value in values.items():
        print(f"{name.replace('_', ' '):>28}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Train, test and save the tender category model.")
    parser.add_argument("--force", action="store_true", help="save the new model even if it scores lower")
    force = parser.parse_args().force

    try:
        dataset, summary = prepare_dataset(load_tenders(config.DATABASE_PATH))
    except sqlite3.Error as error:
        print(f"Cannot read the database at {config.DATABASE_PATH}: {error}", file=sys.stderr)
        return 1
    _print_table(summary)
    if summary["tenders_used"] < MIN_TRAINING_TENDERS:
        print(f"Only {summary['tenders_used']} usable tenders: refusing to train.", file=sys.stderr)
        return 1

    train, test = split_dataset(dataset)
    pipeline = build_pipeline().fit(train["text"], train["category"])
    results, predicted = evaluate(pipeline, test["text"], test["category"], train["category"].mode()[0])
    write_reports(test["category"], predicted, results, config.REPORTS_DIR)
    print()
    _print_table({name: results[name] for name in HEADLINE_METRICS})

    previous = saved_metrics()
    if not should_replace(previous, results, force):
        print(
            f"\nKept the saved model: its top-3 accuracy ({previous['top_3_accuracy']}) beats the new "
            f"model's ({results['top_3_accuracy']}). Use --force to replace it anyway.",
            file=sys.stderr,
        )
        return KEPT_SAVED_MODEL
    metadata = save_model(pipeline, config.MODEL_PATH, results)
    print(f"\nModel version {metadata['version']} saved to {config.MODEL_PATH}")
    print(f"Reports saved to {config.REPORTS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
