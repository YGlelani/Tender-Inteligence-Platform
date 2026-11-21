from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class BusinessProfileAlertOut(BaseModel):
    id: int
    user_id: int
    username: str
    business_name: str
    industry: str
    categories: list[str] = Field(default_factory=list)
    provinces: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    min_tender_value: Optional[float] = None
    max_tender_value: Optional[float] = None
    document_keywords: list[str] = Field(default_factory=list)
    document_industries: list[str] = Field(default_factory=list)
    document_provinces: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

class MatchedTender(BaseModel):
    id: int
    tender_number: str
    title: str
    province: Optional[str] = None
    category: Optional[str] = None
    organisation: Optional[str] = None
    closing_date: Optional[datetime] = None
    status: Optional[str] = None
    score: int
    level: str = "strong"
    reasons: list[str] = Field(default_factory=list)

class NotificationOut(BaseModel):
    id: int
    tender_id: int
    tender_number: str
    title: str
    score: int
    reasons: list[str] = Field(default_factory=list)
    matched_at: datetime
    read_at: Optional[datetime] = None

class UnreadCount(BaseModel):
    unread: int
