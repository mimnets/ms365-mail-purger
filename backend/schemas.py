from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class PurgeJobCreate(BaseModel):
    user_email: str
    date_from: str
    date_to: str

class SearchPreviewRequest(BaseModel):
    user_email: str
    date_from: str
    date_to: str

class SearchPreviewResponse(BaseModel):
    user_email: str
    date_from: str
    date_to: str
    estimated_count: int

class PurgeJobResponse(BaseModel):
    id: str
    user_email: str
    date_from: str
    date_to: str
    status: str
    total_found: int
    total_deleted: int
    total_remaining: int
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    eta_seconds: Optional[int] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True
