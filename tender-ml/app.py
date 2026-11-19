"""The tender-ml web page and API.

Usage:
    python -m uvicorn app:app --reload --port 9004
Then open http://localhost:9004
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sklearn.pipeline import Pipeline

from tender_ml import config
from tender_ml.classifier import MIN_CONFIDENCE, explain, predict_category, top_categories
from tender_ml.dataset import company_text, tender_text
from tender_ml.matching import CategoryMatcher, shared_category
from tender_ml.model_file import load_model
from tender_ml.schemas import (
    CompanyCategories,
    CompanyIn,
    MatchRequest,
    MatchResult,
    Prediction,
    Suggestion,
    TenderIn,
)

PAGE = Path(__file__).parent / "static" / "index.html"


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Start before the first training run; load the model when it becomes available."""
    application.state.pipeline = None
    application.state.metadata = None
    application.state.matcher = None
    _load_model_if_available(application)
    yield


app = FastAPI(title="Tender Category Classifier", lifespan=lifespan)


def get_pipeline(request: Request) -> Pipeline:
    if not _load_model_if_available(request.app):
        raise HTTPException(status_code=503, detail="The category model has not been trained yet")
    return request.app.state.pipeline


def get_matcher(request: Request) -> CategoryMatcher:
    get_pipeline(request)
    return request.app.state.matcher


def get_metadata(request: Request) -> dict | None:
    if not _load_model_if_available(request.app):
        return None
    return request.app.state.metadata


def _load_model_if_available(application: FastAPI) -> bool:
    """Load a newly trained model once, including when training finishes after startup."""
    if application.state.metadata is not None:
        return True
    if not config.MODEL_PATH.exists():
        return False
    pipeline, metadata = load_model(config.MODEL_PATH)
    application.state.pipeline = pipeline
    application.state.metadata = metadata
    application.state.matcher = CategoryMatcher(pipeline)
    return True


Model = Annotated[Pipeline, Depends(get_pipeline)]
Matcher = Annotated[CategoryMatcher, Depends(get_matcher)]


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(PAGE)


@app.get("/health")
def health(metadata: dict | None = Depends(get_metadata)) -> dict:
    if metadata is None:
        return {"status": "degraded", "reason": "model_not_trained"}
    return {"status": "ok", "model_version": metadata["version"]}


@app.get("/model")
def model_info(metadata: dict | None = Depends(get_metadata)) -> dict:
    """When the model was trained, with which library version, and how well it scored."""
    if metadata is None:
        raise HTTPException(status_code=503, detail="The category model has not been trained yet")
    return metadata


@app.post("/predict")
def predict(tender: TenderIn, model: Model) -> Prediction:
    """Predict a tender's category, with the top three guesses and the words behind the best one."""
    text = tender_text(tender.title, tender.description, tender.organisation)
    suggestions = top_categories(model, text)
    return Prediction(
        category=predict_category(model, text),
        min_confidence=MIN_CONFIDENCE,
        suggestions=[Suggestion(category=name, probability=round(share, 4)) for name, share in suggestions],
        explanation=explain(model, text, suggestions[0][0]),
    )


@app.post("/categorise-company")
def categorise_company(company: CompanyIn, model: Model, matcher: Matcher) -> CompanyCategories:
    """The categories a company most likely works in, judged from what it says it does."""
    text = company_text(company.industries, company.services, company.keywords, company.description)
    categories = matcher.company_categories(text)
    if not categories:
        return CompanyCategories(categories=[], suggestions=[], explanation=[])
    return CompanyCategories(
        categories=categories,
        suggestions=[
            Suggestion(category=name, probability=round(share, 4)) for name, share in top_categories(model, text)
        ],
        explanation=explain(model, text, categories[0]),
    )


@app.post("/match-categories")
def match_categories(request: MatchRequest, matcher: Matcher) -> MatchResult:
    """Which tenders share a likely category with the company, keyed by tender id."""
    company = request.company
    wanted = matcher.company_categories(
        company_text(company.industries, company.services, company.keywords, company.description)
    )
    if not wanted:
        return MatchResult(company_categories=[], matches={})
    texts = [tender_text(tender.title, tender.description, tender.organisation) for tender in request.tenders]
    matches = {}
    for tender, predicted in zip(request.tenders, matcher.tender_categories(texts)):
        category = shared_category(wanted, tender.category, predicted)
        if category:
            matches[tender.id] = category
    return MatchResult(company_categories=wanted, matches=matches)
