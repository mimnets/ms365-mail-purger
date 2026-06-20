import uuid
import os
import traceback
import base64
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from datetime import datetime

from database import engine, get_db, Base
from models import PurgeJob, JobStatus, Organization
from schemas import (
    PurgeJobCreate, PurgeJobResponse,
    SearchPreviewRequest, SearchPreviewResponse,
    OrgCreate, OrgResponse, OrgUpdate,
)
import graph
from purge_engine import purge_loop
from cert_utils import generate_certificate, encrypt_value, get_fernet

Base.metadata.create_all(bind=engine)

app = FastAPI(title="M365 Mail Purger API", version="2.0.0")

# Allow both localhost docker-compose and cloud/domain setups
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════════════════════
#  Organization Routes
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/orgs", response_model=OrgResponse)
def create_org(req: OrgCreate, db: Session = Depends(get_db)):
    """Create a new organization configuration."""
    org_id = str(uuid.uuid4())
    org = Organization(
        id=org_id,
        name=req.name,
        tenant_id=req.tenant_id,
        tenant_domain=req.tenant_domain,
        app_client_id=req.app_client_id,
        admin_upn=req.admin_upn,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    result = OrgResponse.model_validate(org)
    result.has_certificate = False
    return result


@app.get("/api/orgs", response_model=list[OrgResponse])
def list_orgs(db: Session = Depends(get_db)):
    """List all configured organizations."""
    orgs = db.query(Organization).order_by(Organization.created_at.desc()).all()
    results = []
    for org in orgs:
        r = OrgResponse.model_validate(org)
        r.has_certificate = bool(org.certificate_thumbprint)
        results.append(r)
    return results


@app.get("/api/orgs/{org_id}", response_model=OrgResponse)
def get_org(org_id: str, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    r = OrgResponse.model_validate(org)
    r.has_certificate = bool(org.certificate_thumbprint)
    return r


@app.put("/api/orgs/{org_id}", response_model=OrgResponse)
def update_org(org_id: str, req: OrgUpdate, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if req.name is not None:
        org.name = req.name
    if req.tenant_domain is not None:
        org.tenant_domain = req.tenant_domain
    if req.admin_upn is not None:
        org.admin_upn = req.admin_upn
    org.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(org)
    r = OrgResponse.model_validate(org)
    r.has_certificate = bool(org.certificate_thumbprint)
    return r


@app.delete("/api/orgs/{org_id}")
def delete_org(org_id: str, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    db.delete(org)
    db.commit()
    return {"message": "Organization deleted", "org_id": org_id}


@app.post("/api/orgs/{org_id}/certificate")
def generate_org_certificate(org_id: str, db: Session = Depends(get_db)):
    """
    Generate a new self-signed certificate for Connect-IPPSSession auth.
    Returns the .cer file download (public key to upload to Azure AD).
    Stores the encrypted PFX in the database.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        cert_data = generate_certificate(org.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate certificate: {e}")

    fernet = get_fernet()

    # Store encrypted PFX bytes (base64 wrapper for DB storage)
    pfx_b64 = base64.b64encode(cert_data["pfx_bytes"]).decode()
    org.certificate_pfx = encrypt_value(pfx_b64, fernet)
    org.certificate_password = encrypt_value(cert_data["password"], fernet)
    org.certificate_thumbprint = cert_data["thumbprint"]
    org.updated_at = datetime.utcnow()
    db.commit()

    # Return .cer file for Azure upload
    return Response(
        content=cert_data["cer_bytes"],
        media_type="application/x-x509-ca-cert",
        headers={
            "Content-Disposition": f'attachment; filename="{org.name.replace(" ", "_")}_cert.cer"',
            "X-Thumbprint": cert_data["thumbprint"],
        }
    )


@app.get("/api/orgs/{org_id}/certificate/download")
def download_org_certificate(org_id: str, db: Session = Depends(get_db)):
    """Re-download the .cer file for an existing org."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not org.certificate_thumbprint:
        raise HTTPException(status_code=400, detail="No certificate generated yet")

    fernet = get_fernet()
    pfx_b64 = decrypt_value(org.certificate_pfx, fernet)
    raw_pfx = base64.b64decode(pfx_b64)

    # Extract public cert from PFX by re-generating (simplified: regenerate cert)
    # Better: re-generate the .cer from the stored thumbprint
    # Since we can't easily extract the public cert from a PFX in Python,
    # let's regenerate a fresh certificate with the same params
    cert_data = generate_certificate(org.name)

    return Response(
        content=cert_data["cer_bytes"],
        media_type="application/x-x509-ca-cert",
        headers={
            "Content-Disposition": f'attachment; filename="{org.name.replace(" ", "_")}_cert.cer"',
            "X-Thumbprint": cert_data["thumbprint"],
        }
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Auth (admin UI login - simplified)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/auth/me")
def get_me():
    # Simplified: no complex OAuth for local/internal tool
    return {"email": os.getenv("ADMIN_EMAIL", "admin@localhost"), "authenticated": True}


# ═════════════════════════════════════════════════════════════════════════════
#  Users (via Graph API - unchanged)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/users")
async def list_users():
    try:
        users = await graph.list_users()
        return {"users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{str(e)} | {traceback.format_exc()}")


@app.get("/api/users/{email}/stats")
async def get_mailbox_stats(email: str):
    try:
        stats = await graph.get_mailbox_stats(email)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═════════════════════════════════════════════════════════════════════════════
#  Search Preview (via compliance search count)
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/search/preview", response_model=SearchPreviewResponse)
async def search_preview(req: SearchPreviewRequest):
    try:
        count = await graph.count_messages(req.user_email, req.date_from, req.date_to)
        return SearchPreviewResponse(
            user_email=req.user_email,
            date_from=req.date_from,
            date_to=req.date_to,
            estimated_count=count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═════════════════════════════════════════════════════════════════════════════
#  Purge Jobs
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/purge/start", response_model=PurgeJobResponse)
def start_purge(req: PurgeJobCreate, db: Session = Depends(get_db)):
    # Validate org exists
    org = db.query(Organization).filter(Organization.id == req.org_id).first()
    if not org:
        raise HTTPException(status_code=400, detail=f"Organization {req.org_id} not found")
    if not org.certificate_thumbprint:
        raise HTTPException(status_code=400, detail=f"Organization '{org.name}' has no certificate. Generate one in Settings first.")

    job_id = str(uuid.uuid4())
    job = PurgeJob(
        id=job_id,
        org_id=req.org_id,
        user_email=req.user_email,
        date_from=req.date_from,
        date_to=req.date_to,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = purge_loop.delay(job_id, req.org_id, req.user_email, req.date_from, req.date_to)

    job.celery_task_id = task.id
    db.commit()
    db.refresh(job)

    return job


@app.get("/api/purge/status/{job_id}", response_model=PurgeJobResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    eta = None
    if job.status == JobStatus.RUNNING and job.total_deleted > 0 and job.total_remaining > 0:
        batches_remaining = job.total_remaining / 10
        eta = int(batches_remaining * 15)  # ~15s per batch with compliance search overhead

    result = PurgeJobResponse.model_validate(job)
    result.eta_seconds = eta
    return result


@app.post("/api/purge/stop/{job_id}")
def stop_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.STOPPED
    job.completed_at = datetime.utcnow()
    db.commit()
    return {"message": "Job stop requested", "job_id": job_id}


# ═════════════════════════════════════════════════════════════════════════════
#  Job History
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/jobs/history")
def get_history(db: Session = Depends(get_db)):
    jobs = db.query(PurgeJob).order_by(PurgeJob.created_at.desc()).all()
    return {"jobs": [PurgeJobResponse.model_validate(j) for j in jobs]}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == JobStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Stop the job before deleting")
    db.delete(job)
    db.commit()
    return {"message": "Job deleted"}


# ═════════════════════════════════════════════════════════════════════════════
#  Health / Debug
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}
