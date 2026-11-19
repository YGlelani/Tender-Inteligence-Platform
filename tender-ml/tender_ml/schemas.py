"""Request and response shapes for the tender-ml API.

Size limits protect the service from huge requests while staying well above
real data (the longest stored tender description is about 5,600 characters).
"""
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Phrases = Annotated[list[ShortText], Field(max_length=200)]


class TenderIn(BaseModel):
    title: Title
    description: LongText = ""
    organisation: ShortText = ""


class CompanyIn(BaseModel):
    industries: Phrases = []
    services: Phrases = []
    keywords: Phrases = []
    description: LongText = ""


class TenderToMatch(BaseModel):
    id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    title: ShortText = ""
    description: LongText = ""
    organisation: ShortText = ""
    category: Annotated[str, StringConstraints(max_length=10_000)] | None = None


class MatchRequest(BaseModel):
    company: CompanyIn
    tenders: Annotated[list[TenderToMatch], Field(max_length=5000)]


class Suggestion(BaseModel):
    category: str
    probability: float


class Prediction(BaseModel):
    category: str | None
    min_confidence: float
    suggestions: list[Suggestion]
    explanation: list[str]


class CompanyCategories(BaseModel):
    categories: list[str]
    suggestions: list[Suggestion]
    explanation: list[str]


class MatchResult(BaseModel):
    company_categories: list[str]
    matches: dict[str, str]
