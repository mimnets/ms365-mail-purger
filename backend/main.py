import uuid
import traceback
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from database import engine, get_db, Base
from models import PurgeJob, JobStatus
from schemas import (
    PurgeJobCreate, PurgeJobResponse,
    SearchPreviewRequest, SearchPreviewResponse
)
import graph
import auth
from purge_engine import purge_loop

Base.metadata.create_all(bind=engine)

app = FastAPI(title="M365 Mail Purger API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def login():
    url = auth.get_auth_url()
    return {"auth_url": url}

@app.get("/api/auth/callback")
def auth_callback(code: str = Query(...), state: str = Query(None)):
    try:
        auth.exchange_code_for_token(code)
        return RedirectResponse(url=f"{auth.FRONTEND_URL}/?auth=success")
    except Exception as e:
        return RedirectResponse(url=f"{auth.FRONTEND_URL}/?auth=error&msg={str(e)}")

@app.get("/api/debug/token")
def debug_token():
    try:
        token = auth.get_app_token()
        return {"status": "ok", "token_preview": token[:20] + "..."}
    except Exception as e:
        return {"status": "error", "detail": str(e), "trace": traceback.format_exc()}

@app.get("/api/auth/me")
def get_me():
    return {"email": auth.ADMIN_EMAIL, "authenticated": True}

# ── Users ─────────────────────────────────────────────────────────────────────

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

# ── Search Preview ────────────────────────────────────────────────────────────

@app.post("/api/search/preview", response_model=SearchPreviewResponse)
async def search_preview(req: SearchPreviewRequest):
    try:
        count = await graph.count_messages(req.user_email, req.date_from, req.date_to)
        return SearchPreviewResponse(
            user_email=req.user_email,
            date_from=req.date_from,
            date_to=req.date_to,
            estimated_count=count
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Purge Jobs ────────────────────────────────────────────────────────────────

@app.post("/api/purge/start", response_model=PurgeJobResponse)
def start_purge(req: PurgeJobCreate, db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())
    job = PurgeJob(
        id=job_id,
        user_email=req.user_email,
        date_from=req.date_from,
        date_to=req.date_to,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = purge_loop.delay(job_id, req.user_email, req.date_from, req.date_to)

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
        eta = int(batches_remaining * 1.1)

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

# ── Job History ───────────────────────────────────────────────────────────────

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
