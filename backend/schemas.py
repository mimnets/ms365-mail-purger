from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PurgeJobCreate(BaseModel):
    org_id: str
    user_email: str
    date_from: str
    date_to: str


class SearchPreviewRequest(BaseModel):
    org_id: str
    user_email: str
    date_from: str
    date_to: str


class SearchPreviewResponse(BaseModel):
    user_email: str
    date_from: str
    date_to: str
    estimated_count: int
    estimated_primary_count: int = 0
    estimated_archive_count: int = 0


class PurgeJobResponse(BaseModel):
    id: str
    org_id: str
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
    status_message: Optional[str] = None

    class Config:
        from_attributes = True


# ── Organization Schemas ──────────────────────────────────────────────────────

class OrgCreate(BaseModel):
    name: str
    tenant_id: str
    tenant_domain: str
    app_client_id: str
    admin_upn: str


class OrgResponse(BaseModel):
    id: str
    name: str
    tenant_id: str
    tenant_domain: str
    app_client_id: str
    admin_upn: str
    certificate_thumbprint: Optional[str] = None
    has_certificate: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrgUpdate(BaseModel):
    name: Optional[str] = None
    tenant_domain: Optional[str] = None
    admin_upn: Optional[str] = None
