"""Suggest categories for one tender using the trained model.

Usage:
    python predict.py "Supply and delivery of office furniture" --organisation "Department of Health"
"""
import argparse
import sys

from tender_ml import config
from tender_ml.classifier import MIN_CONFIDENCE, explain, predict_category, top_categories
from tender_ml.dataset import tender_text
from tender_ml.model_file import load_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suggest categories for a tender.")
    parser.add_argument("title", help="tender title")
    parser.add_argument("--description", default="", help="tender description")
    parser.add_argument("--organisation", default="", help="name of the organisation that published the tender")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not config.MODEL_PATH.exists():
        print(f"No model found at {config.MODEL_PATH}. Run 'python train.py' first.", file=sys.stderr)
        return 1

    pipeline, _ = load_model(config.MODEL_PATH)
    text = tender_text(args.title, args.description, args.organisation)
    suggestions = top_categories(pipeline, text)
    for category, probability in suggestions:
        print(f"{probability:6.1%}  {category}")

    reasons = explain(pipeline, text, suggestions[0][0])
    if reasons:
        print(f"\nWords behind the top guess: {', '.join(reasons)}")
    if predict_category(pipeline, text) is None:
        print(f"\nNot confident enough to fill in a category (needs {MIN_CONFIDENCE:.0%}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
