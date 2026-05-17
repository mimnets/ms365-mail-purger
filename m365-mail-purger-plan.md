# M365 Mail Purger — Complete Build Plan

## Project Goal

Web app for M365 admins to:
- Login via Microsoft OAuth (admin account: monir.it@vclbd.net)
- Select any user mailbox in the tenant
- Search emails by date range
- Delete emails in batches (10 per API call, looped automatically)
- See live dashboard: total found / deleted / remaining / ETA
- Manage multiple users/jobs concurrently
- Cleanup content searches after done

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Auth | MSAL (Microsoft Authentication Library for Python) |
| M365 API | Microsoft Graph REST API (no PowerShell) |
| Task Queue | Celery + Redis |
| Database | SQLite via SQLAlchemy |
| Frontend | React 18 + TailwindCSS + shadcn/ui |
| Real-time | WebSocket or polling every 3s |
| Containerization | Docker + docker-compose |

---

## Azure App Registration (One-Time Setup)

Do this once before writing any code.

1. Go to [portal.azure.com](https://portal.azure.com)
2. Navigate to: **Azure Active Directory → App Registrations → New Registration**
3. Name: `M365 Mail Purger`
4. Supported account types: **Accounts in this organizational directory only**
5. Redirect URI: `http://localhost:8000/api/auth/callback` (Web platform)
6. Click **Register**
7. Copy the **Application (client) ID** → this is `CLIENT_ID`
8. Copy the **Directory (tenant) ID** → this is `TENANT_ID`
9. Go to **Certificates & Secrets → New client secret**
   - Description: `mail-purger-secret`
   - Expiry: 24 months
   - Copy the **Value** immediately → this is `CLIENT_SECRET`
10. Go to **API Permissions → Add a permission → Microsoft Graph → Application permissions**
    Add ALL of these:
    - `Mail.ReadWrite`
    - `Mail.ReadWrite.Shared`
    - `User.Read.All`
    - `MailboxSettings.Read`
    - `Reports.Read.All`
11. Click **Grant admin consent for [your tenant]** — must be done by a Global Admin
12. Verify all permissions show green checkmark under "Status"

> **Important:** Application permissions (not delegated) are required so the app can act on behalf of any user without individual user login.

---

## Complete Folder Structure

```
m365-mail-purger/
├── docker-compose.yml
├── .env
├── .env.example
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── auth.py
│   ├── graph.py
│   ├── purge_engine.py
│   ├── models.py
│   ├── database.py
│   ├── celery_app.py
│   └── schemas.py
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── api/
        │   └── client.js
        ├── pages/
        │   ├── LoginPage.jsx
        │   ├── UsersPage.jsx
        │   ├── PurgePage.jsx
        │   ├── DashboardPage.jsx
        │   └── HistoryPage.jsx
        ├── components/
        │   ├── Navbar.jsx
        │   ├── JobCard.jsx
        │   ├── ProgressBar.jsx
        │   ├── StatusBadge.jsx
        │   └── DateRangePicker.jsx
        └── hooks/
            └── useJobPolling.js
```

---

## Environment Variables (.env)

Create `.env` in project root:

```env
# Azure App Registration
CLIENT_ID=your-client-id-here
CLIENT_SECRET=your-client-secret-here
TENANT_ID=your-tenant-id-here

# Auth
REDIRECT_URI=http://localhost:8000/api/auth/callback
FRONTEND_URL=http://localhost:3000
SESSION_SECRET=change-this-to-a-random-string-32chars

# Redis
REDIS_URL=redis://redis:6379/0

# Database
DATABASE_URL=sqlite:///./purger.db

# App
ADMIN_EMAIL=monir.it@vclbd.net
```

Create `.env.example` as a copy with placeholder values only.

---

## Backend Implementation

### `backend/requirements.txt`

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
msal==1.28.0
httpx==0.27.0
celery==5.4.0
redis==5.0.4
sqlalchemy==2.0.30
aiosqlite==0.20.0
python-dotenv==1.0.1
pydantic==2.7.1
python-multipart==0.0.9
itsdangerous==2.2.0
starlette==0.37.2
```

---

### `backend/database.py`

```python
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./purger.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # SQLite only
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

### `backend/models.py`

```python
from sqlalchemy import Column, String, Integer, DateTime, Enum
from sqlalchemy.sql import func
from database import Base
import enum

class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    STOPPED = "STOPPED"

class PurgeJob(Base):
    __tablename__ = "purge_jobs"

    id = Column(String, primary_key=True)  # UUID
    user_email = Column(String, nullable=False, index=True)
    date_from = Column(String, nullable=False)   # ISO format: 2024-01-01
    date_to = Column(String, nullable=False)     # ISO format: 2024-12-31
    status = Column(String, default=JobStatus.QUEUED)
    total_found = Column(Integer, default=0)
    total_deleted = Column(Integer, default=0)
    total_remaining = Column(Integer, default=0)
    batch_size = Column(Integer, default=10)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)
    celery_task_id = Column(String, nullable=True)
```

---

### `backend/schemas.py`

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class PurgeJobCreate(BaseModel):
    user_email: str
    date_from: str   # YYYY-MM-DD
    date_to: str     # YYYY-MM-DD

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
    created_at: Optional[datetime]
    completed_at: Optional[datetime]
    eta_seconds: Optional[int]
    error_message: Optional[str]

    class Config:
        from_attributes = True
```

---

### `backend/celery_app.py`

```python
from celery import Celery
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "purger",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["purge_engine"]
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
```

---

### `backend/auth.py`

Full MSAL client credentials flow (application permissions — no user login required for Graph calls):

```python
import msal
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
REDIRECT_URI = os.getenv("REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

# In-memory token cache (upgrade to Redis for multi-instance)
_token_cache = {}

def get_confidential_client():
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
    )

def get_app_token() -> str:
    """
    Acquire token using client credentials (application permissions).
    MSAL caches this automatically within the app instance.
    """
    app = get_confidential_client()
    result = app.acquire_token_silent(GRAPH_SCOPE, account=None)

    if not result:
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    if "access_token" not in result:
        raise RuntimeError(
            f"Failed to acquire token: {result.get('error_description', 'Unknown error')}"
        )

    return result["access_token"]

def get_auth_url() -> str:
    """
    Generate OAuth login URL for admin web login (delegated — for UI auth only).
    """
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    return app.get_authorization_request_url(
        scopes=["openid", "profile", "email"],
        redirect_uri=REDIRECT_URI,
        state="login"
    )

def exchange_code_for_token(code: str) -> dict:
    """
    Exchange auth code for user session token (admin login only).
    """
    app = get_confidential_client()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=["openid", "profile", "email"],
        redirect_uri=REDIRECT_URI,
    )
    return result
```

---

### `backend/graph.py`

All Microsoft Graph API calls:

```python
import httpx
import asyncio
from typing import List, Dict, Optional
from auth import get_app_token

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

def _headers() -> dict:
    token = get_app_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

async def list_users() -> List[Dict]:
    """
    GET /users — returns all mailbox-enabled users with display info.
    """
    url = f"{GRAPH_BASE}/users"
    params = {
        "$select": "id,displayName,mail,userPrincipalName,assignedLicenses",
        "$filter": "assignedLicenses/$count ne 0",
        "$count": "true",
        "$top": 999,
    }
    headers = {**_headers(), "ConsistencyLevel": "eventual"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("value", [])

async def get_mailbox_stats(user_email: str) -> Dict:
    """
    GET /users/{email}/mailboxSettings + mailbox usage
    Returns total item count and size.
    """
    url = f"{GRAPH_BASE}/users/{user_email}/mailFolders/inbox"
    params = {"$select": "totalItemCount,sizeInBytes"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code == 200:
            return resp.json()
        return {"totalItemCount": 0, "sizeInBytes": 0}

async def search_messages(
    user_email: str,
    date_from: str,
    date_to: str,
    top: int = 10
) -> List[str]:
    """
    GET /users/{email}/messages — filtered by receivedDateTime range.
    Returns list of message IDs only.

    Graph filter format: receivedDateTime ge 2024-01-01T00:00:00Z and receivedDateTime le 2024-12-31T23:59:59Z
    """
    url = f"{GRAPH_BASE}/users/{user_email}/messages"
    params = {
        "$filter": (
            f"receivedDateTime ge {date_from}T00:00:00Z "
            f"and receivedDateTime le {date_to}T23:59:59Z"
        ),
        "$select": "id,subject,receivedDateTime",
        "$top": top,
        "$orderby": "receivedDateTime asc",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code == 429:
            # Rate limited — back off
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await search_messages(user_email, date_from, date_to, top)
        resp.raise_for_status()
        messages = resp.json().get("value", [])
        return [m["id"] for m in messages]

async def count_messages(
    user_email: str,
    date_from: str,
    date_to: str
) -> int:
    """
    GET /users/{email}/messages/$count — approximate count for preview.
    Uses $count=true with filter.
    """
    url = f"{GRAPH_BASE}/users/{user_email}/messages"
    params = {
        "$filter": (
            f"receivedDateTime ge {date_from}T00:00:00Z "
            f"and receivedDateTime le {date_to}T23:59:59Z"
        ),
        "$count": "true",
        "$top": 1,
        "$select": "id",
    }
    headers = {**_headers(), "ConsistencyLevel": "eventual"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("@odata.count", 0)

async def delete_message(user_email: str, message_id: str) -> bool:
    """
    DELETE /users/{email}/messages/{id}
    Moves message to Recoverable Items (soft delete).
    Returns True on success.
    """
    url = f"{GRAPH_BASE}/users/{user_email}/messages/{message_id}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(url, headers=_headers())
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await delete_message(user_email, message_id)
        return resp.status_code == 204
```

---

### `backend/purge_engine.py`

Celery background task that loops search → delete → update → repeat:

```python
import asyncio
import time
import uuid
from datetime import datetime
from celery_app import celery_app
from database import SessionLocal
from models import PurgeJob, JobStatus
import graph

BATCH_SIZE = 10
SLEEP_BETWEEN_BATCHES = 1.0  # seconds — stay under Graph rate limits

def _update_job(db, job_id: str, **kwargs):
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if job:
        for k, v in kwargs.items():
            setattr(job, k, v)
        db.commit()
    return job

@celery_app.task(bind=True, name="purge_engine.purge_loop")
def purge_loop(self, job_id: str, user_email: str, date_from: str, date_to: str):
    """
    Main purge task. Runs synchronously inside Celery worker.
    Loops: search 10 messages → delete each → update DB → repeat until 0 found.
    """
    db = SessionLocal()

    try:
        # Mark job as running
        _update_job(db, job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
            celery_task_id=self.request.id
        )

        # Get initial count for ETA calculation
        initial_count = asyncio.run(
            graph.count_messages(user_email, date_from, date_to)
        )
        _update_job(db, job_id,
            total_found=initial_count,
            total_remaining=initial_count
        )

        total_deleted = 0
        batch_start_time = time.time()

        while True:
            # Check if job was stopped externally
            db.expire_all()
            job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
            if not job or job.status in [JobStatus.STOPPED, JobStatus.FAILED]:
                break

            # Search next batch of 10
            message_ids = asyncio.run(
                graph.search_messages(user_email, date_from, date_to, top=BATCH_SIZE)
            )

            if not message_ids:
                # No more messages — done
                _update_job(db, job_id,
                    status=JobStatus.COMPLETE,
                    total_deleted=total_deleted,
                    total_remaining=0,
                    completed_at=datetime.utcnow()
                )
                break

            # Delete each message in the batch
            batch_deleted = 0
            for msg_id in message_ids:
                success = asyncio.run(graph.delete_message(user_email, msg_id))
                if success:
                    batch_deleted += 1
                    total_deleted += 1
                time.sleep(0.1)  # small delay between individual deletes

            # Update DB after each batch
            remaining = max(0, initial_count - total_deleted)
            _update_job(db, job_id,
                total_deleted=total_deleted,
                total_remaining=remaining
            )

            # Respect Graph API rate limit: sleep between batches
            time.sleep(SLEEP_BETWEEN_BATCHES)

    except Exception as e:
        _update_job(db, job_id,
            status=JobStatus.FAILED,
            error_message=str(e),
            completed_at=datetime.utcnow()
        )
        raise

    finally:
        db.close()
```

---

### `backend/main.py`

Full FastAPI app with all routes:

```python
import uuid
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime
import asyncio

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
        token_result = auth.exchange_code_for_token(code)
        # In production: set httpOnly session cookie here
        return RedirectResponse(url=f"{auth.FRONTEND_URL}/?auth=success")
    except Exception as e:
        return RedirectResponse(url=f"{auth.FRONTEND_URL}/?auth=error&msg={str(e)}")

@app.get("/api/auth/me")
def get_me():
    # Placeholder — validate session token/cookie
    return {"email": auth.ADMIN_EMAIL, "authenticated": True}

# ── Users ─────────────────────────────────────────────────────────────────────

@app.get("/api/users")
async def list_users():
    try:
        users = await graph.list_users()
        return {"users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

    # Dispatch Celery task
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

    # Calculate ETA
    eta = None
    if job.status == JobStatus.RUNNING and job.total_deleted > 0 and job.total_remaining > 0:
        # Assume ~1 batch/second (10 items + 1s sleep)
        batches_remaining = job.total_remaining / 10
        eta = int(batches_remaining * 1.1)  # seconds

    result = PurgeJobResponse.from_orm(job)
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
    return {"jobs": jobs}

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
```

---

## API Endpoints Reference

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/auth/login` | none | `{ auth_url }` |
| GET | `/api/auth/callback` | query: `code`, `state` | redirect to frontend |
| GET | `/api/auth/me` | none | `{ email, authenticated }` |
| GET | `/api/users` | none | `{ users: [...] }` |
| GET | `/api/users/{email}/stats` | none | `{ totalItemCount, sizeInBytes }` |
| POST | `/api/search/preview` | `{ user_email, date_from, date_to }` | `{ estimated_count }` |
| POST | `/api/purge/start` | `{ user_email, date_from, date_to }` | job object |
| GET | `/api/purge/status/{job_id}` | none | job object + eta_seconds |
| POST | `/api/purge/stop/{job_id}` | none | `{ message }` |
| GET | `/api/jobs/history` | none | `{ jobs: [...] }` |
| DELETE | `/api/jobs/{job_id}` | none | `{ message }` |

---

## Frontend Implementation

### `frontend/package.json`

```json
{
  "name": "m365-mail-purger",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.23.1",
    "axios": "^1.7.2",
    "@radix-ui/react-dialog": "^1.0.5",
    "@radix-ui/react-select": "^2.0.0",
    "@radix-ui/react-progress": "^1.0.3",
    "lucide-react": "^0.383.0",
    "date-fns": "^3.6.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.3.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.38",
    "tailwindcss": "^3.4.4",
    "vite": "^5.2.11"
  }
}
```

---

### `frontend/src/api/client.js`

```javascript
import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8000",
  withCredentials: true,
});

export const authLogin = () => api.post("/api/auth/login");
export const getMe = () => api.get("/api/auth/me");

export const listUsers = () => api.get("/api/users");
export const getMailboxStats = (email) => api.get(`/api/users/${encodeURIComponent(email)}/stats`);

export const searchPreview = (data) => api.post("/api/search/preview", data);
export const startPurge = (data) => api.post("/api/purge/start", data);
export const getJobStatus = (jobId) => api.get(`/api/purge/status/${jobId}`);
export const stopJob = (jobId) => api.post(`/api/purge/stop/${jobId}`);

export const getHistory = () => api.get("/api/jobs/history");
export const deleteJob = (jobId) => api.delete(`/api/jobs/${jobId}`);

export default api;
```

---

### `frontend/src/hooks/useJobPolling.js`

```javascript
import { useState, useEffect, useRef } from "react";
import { getJobStatus } from "../api/client";

export function useJobPolling(jobId, intervalMs = 3000) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const res = await getJobStatus(jobId);
        setJob(res.data);
        // Stop polling when terminal state reached
        if (["COMPLETE", "FAILED", "STOPPED"].includes(res.data.status)) {
          clearInterval(intervalRef.current);
        }
      } catch (err) {
        setError(err.message);
      }
    };

    poll(); // immediate first call
    intervalRef.current = setInterval(poll, intervalMs);

    return () => clearInterval(intervalRef.current);
  }, [jobId, intervalMs]);

  return { job, error };
}
```

---

### `frontend/src/App.jsx`

```jsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Navbar from "./components/Navbar";
import LoginPage from "./pages/LoginPage";
import UsersPage from "./pages/UsersPage";
import PurgePage from "./pages/PurgePage";
import DashboardPage from "./pages/DashboardPage";
import HistoryPage from "./pages/HistoryPage";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 py-8">
          <Routes>
            <Route path="/" element={<Navigate to="/purge" />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/purge" element={<PurgePage />} />
            <Route path="/dashboard/:jobId" element={<DashboardPage />} />
            <Route path="/history" element={<HistoryPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
```

---

### `frontend/src/pages/LoginPage.jsx`

```jsx
import { authLogin } from "../api/client";

export default function LoginPage() {
  const handleLogin = async () => {
    const res = await authLogin();
    window.location.href = res.data.auth_url;
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] gap-6">
      <h1 className="text-3xl font-bold text-white">M365 Mail Purger</h1>
      <p className="text-gray-400">Sign in with your Microsoft admin account</p>
      <button
        onClick={handleLogin}
        className="flex items-center gap-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-3 rounded-lg transition"
      >
        Sign in with Microsoft
      </button>
    </div>
  );
}
```

---

### `frontend/src/pages/UsersPage.jsx`

```jsx
import { useEffect, useState } from "react";
import { listUsers } from "../api/client";

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listUsers().then(res => {
      setUsers(res.data.users || []);
      setLoading(false);
    });
  }, []);

  const filtered = users.filter(u =>
    u.displayName?.toLowerCase().includes(search.toLowerCase()) ||
    u.mail?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Mailboxes</h2>
      <input
        className="mb-4 w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
        placeholder="Search users..."
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-700">
              <th className="pb-2">Name</th>
              <th className="pb-2">Email</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(u => (
              <tr key={u.id} className="border-b border-gray-800 hover:bg-gray-800">
                <td className="py-2">{u.displayName}</td>
                <td className="py-2 text-blue-400">{u.mail || u.userPrincipalName}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

---

### `frontend/src/pages/PurgePage.jsx`

```jsx
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { listUsers, searchPreview, startPurge } from "../api/client";

export default function PurgePage() {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [purging, setPurging] = useState(false);

  useEffect(() => {
    listUsers().then(res => setUsers(res.data.users || []));
  }, []);

  const handlePreview = async () => {
    if (!selectedEmail || !dateFrom || !dateTo) return;
    setPreviewLoading(true);
    try {
      const res = await searchPreview({ user_email: selectedEmail, date_from: dateFrom, date_to: dateTo });
      setPreview(res.data);
    } catch (e) {
      alert("Preview failed: " + e.message);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleStartPurge = async () => {
    if (!selectedEmail || !dateFrom || !dateTo) return;
    setPurging(true);
    try {
      const res = await startPurge({ user_email: selectedEmail, date_from: dateFrom, date_to: dateTo });
      navigate(`/dashboard/${res.data.id}`);
    } catch (e) {
      alert("Failed to start purge: " + e.message);
      setPurging(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-6">Search & Purge</h2>

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-400 mb-1">Select Mailbox</label>
          <select
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
            value={selectedEmail}
            onChange={e => setSelectedEmail(e.target.value)}
          >
            <option value="">-- Select user --</option>
            {users.map(u => (
              <option key={u.id} value={u.mail || u.userPrincipalName}>
                {u.displayName} ({u.mail || u.userPrincipalName})
              </option>
            ))}
          </select>
        </div>

        <div className="flex gap-4">
          <div className="flex-1">
            <label className="block text-sm text-gray-400 mb-1">Date From</label>
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white" />
          </div>
          <div className="flex-1">
            <label className="block text-sm text-gray-400 mb-1">Date To</label>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white" />
          </div>
        </div>

        <button
          onClick={handlePreview}
          disabled={previewLoading || !selectedEmail || !dateFrom || !dateTo}
          className="w-full bg-gray-700 hover:bg-gray-600 text-white py-2 rounded disabled:opacity-50"
        >
          {previewLoading ? "Counting..." : "Preview Count"}
        </button>

        {preview && (
          <div className="bg-gray-800 rounded p-4 border border-gray-700">
            <p className="text-lg">Found: <span className="text-yellow-400 font-bold">{preview.estimated_count.toLocaleString()}</span> emails</p>
            <p className="text-sm text-gray-400">in {selectedEmail} between {dateFrom} and {dateTo}</p>
          </div>
        )}

        <button
          onClick={handleStartPurge}
          disabled={purging || !selectedEmail || !dateFrom || !dateTo}
          className="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-3 rounded disabled:opacity-50"
        >
          {purging ? "Starting..." : "Start Purge"}
        </button>
      </div>
    </div>
  );
}
```

---

### `frontend/src/pages/DashboardPage.jsx`

```jsx
import { useParams, useNavigate } from "react-router-dom";
import { useJobPolling } from "../hooks/useJobPolling";
import { stopJob } from "../api/client";

const STATUS_COLORS = {
  QUEUED: "bg-yellow-500",
  RUNNING: "bg-blue-500",
  PAUSED: "bg-orange-500",
  COMPLETE: "bg-green-500",
  FAILED: "bg-red-500",
  STOPPED: "bg-gray-500",
};

function formatEta(seconds) {
  if (!seconds) return "--";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}h ${m}m ${s}s`;
}

export default function DashboardPage() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const { job, error } = useJobPolling(jobId, 3000);

  const handleStop = async () => {
    await stopJob(jobId);
  };

  if (error) return <p className="text-red-400">Error: {error}</p>;
  if (!job) return <p className="text-gray-400">Loading job...</p>;

  const progress = job.total_found > 0
    ? Math.round((job.total_deleted / job.total_found) * 100)
    : 0;

  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Live Dashboard</h2>
        <span className={`text-xs font-bold px-3 py-1 rounded-full text-white ${STATUS_COLORS[job.status]}`}>
          {job.status}
        </span>
      </div>

      <div className="bg-gray-800 rounded-lg p-6 space-y-4">
        <div>
          <p className="text-gray-400 text-sm">Mailbox</p>
          <p className="font-medium">{job.user_email}</p>
        </div>
        <div>
          <p className="text-gray-400 text-sm">Date Range</p>
          <p className="font-medium">{job.date_from} → {job.date_to}</p>
        </div>

        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-gray-400">Progress</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-3">
            <div
              className="bg-blue-500 h-3 rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4 text-center">
          <div className="bg-gray-900 rounded p-3">
            <p className="text-2xl font-bold text-white">{job.total_found.toLocaleString()}</p>
            <p className="text-xs text-gray-400">Total Found</p>
          </div>
          <div className="bg-gray-900 rounded p-3">
            <p className="text-2xl font-bold text-green-400">{job.total_deleted.toLocaleString()}</p>
            <p className="text-xs text-gray-400">Deleted</p>
          </div>
          <div className="bg-gray-900 rounded p-3">
            <p className="text-2xl font-bold text-yellow-400">{job.total_remaining.toLocaleString()}</p>
            <p className="text-xs text-gray-400">Remaining</p>
          </div>
        </div>

        <div className="text-center">
          <p className="text-gray-400 text-sm">ETA</p>
          <p className="text-xl font-mono">{formatEta(job.eta_seconds)}</p>
        </div>

        {job.status === "RUNNING" && (
          <button
            onClick={handleStop}
            className="w-full bg-red-700 hover:bg-red-600 text-white py-2 rounded font-semibold"
          >
            Stop Job
          </button>
        )}
        {["COMPLETE", "FAILED", "STOPPED"].includes(job.status) && (
          <button
            onClick={() => navigate("/history")}
            className="w-full bg-gray-700 hover:bg-gray-600 text-white py-2 rounded"
          >
            View History
          </button>
        )}
      </div>
    </div>
  );
}
```

---

### `frontend/src/pages/HistoryPage.jsx`

```jsx
import { useEffect, useState } from "react";
import { getHistory, deleteJob } from "../api/client";
import { useNavigate } from "react-router-dom";

export default function HistoryPage() {
  const [jobs, setJobs] = useState([]);
  const navigate = useNavigate();

  const load = () => getHistory().then(res => setJobs(res.data.jobs || []));
  useEffect(() => { load(); }, []);

  const handleDelete = async (jobId) => {
    if (!confirm("Delete this job record?")) return;
    await deleteJob(jobId);
    load();
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Job History</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-700">
            <th className="pb-2">User</th>
            <th className="pb-2">Date Range</th>
            <th className="pb-2">Deleted</th>
            <th className="pb-2">Status</th>
            <th className="pb-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map(j => (
            <tr key={j.id} className="border-b border-gray-800 hover:bg-gray-800">
              <td className="py-2">{j.user_email}</td>
              <td className="py-2">{j.date_from} → {j.date_to}</td>
              <td className="py-2">{j.total_deleted?.toLocaleString()}</td>
              <td className="py-2">
                <span className="text-xs font-bold px-2 py-1 rounded bg-gray-700">{j.status}</span>
              </td>
              <td className="py-2 flex gap-2">
                <button onClick={() => navigate(`/dashboard/${j.id}`)}
                  className="text-blue-400 hover:underline text-xs">View</button>
                <button onClick={() => handleDelete(j.id)}
                  className="text-red-400 hover:underline text-xs">Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

---

### `frontend/src/components/Navbar.jsx`

```jsx
import { Link, useLocation } from "react-router-dom";

const links = [
  { to: "/purge", label: "Purge" },
  { to: "/users", label: "Users" },
  { to: "/history", label: "History" },
];

export default function Navbar() {
  const { pathname } = useLocation();
  return (
    <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-white text-lg">M365 Purger</span>
      {links.map(l => (
        <Link key={l.to} to={l.to}
          className={`text-sm ${pathname.startsWith(l.to) ? "text-white font-semibold" : "text-gray-400 hover:text-white"}`}>
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
```

---

## Docker & Infrastructure

### `docker-compose.yml`

```yaml
version: "3.9"

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - ./backend:/app
      - purger_db:/app/data
    depends_on:
      - redis
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
    restart: unless-stopped

  worker:
    build: ./backend
    env_file: .env
    volumes:
      - ./backend:/app
      - purger_db:/app/data
    depends_on:
      - redis
    command: celery -A celery_app worker --loglevel=info --concurrency=4
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    command: npm run dev -- --host 0.0.0.0 --port 3000
    restart: unless-stopped

volumes:
  purger_db:
```

### `backend/Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
```

### `frontend/Dockerfile`

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
EXPOSE 3000
```

---

## Microsoft Graph API Reference

### List messages with date filter

```
GET https://graph.microsoft.com/v1.0/users/{email}/messages
    ?$filter=receivedDateTime ge 2024-01-01T00:00:00Z and receivedDateTime le 2024-12-31T23:59:59Z
    &$select=id,subject,receivedDateTime
    &$top=10
    &$orderby=receivedDateTime asc

Headers:
  Authorization: Bearer {app_token}
  Content-Type: application/json
```

### Get message count

```
GET https://graph.microsoft.com/v1.0/users/{email}/messages
    ?$filter=receivedDateTime ge 2024-01-01T00:00:00Z and receivedDateTime le 2024-12-31T23:59:59Z
    &$count=true
    &$top=1
    &$select=id

Headers:
  Authorization: Bearer {app_token}
  ConsistencyLevel: eventual
```

### Delete a message (soft delete)

```
DELETE https://graph.microsoft.com/v1.0/users/{email}/messages/{message-id}

Headers:
  Authorization: Bearer {app_token}

Response: 204 No Content
```

### Get mailbox folder stats

```
GET https://graph.microsoft.com/v1.0/users/{email}/mailFolders/inbox
    ?$select=totalItemCount,sizeInBytes

Headers:
  Authorization: Bearer {app_token}
```

### List licensed users (mailboxes)

```
GET https://graph.microsoft.com/v1.0/users
    ?$select=id,displayName,mail,userPrincipalName,assignedLicenses
    &$filter=assignedLicenses/$count ne 0
    &$count=true
    &$top=999

Headers:
  Authorization: Bearer {app_token}
  ConsistencyLevel: eventual
```

---

## Key Implementation Notes

### Soft vs Hard Delete
Graph API `DELETE /messages/{id}` performs a **soft delete** — moves email to the user's **Recoverable Items** folder. Emails are permanently removed after 14–30 days depending on retention policy, or an admin can purge them immediately via the Microsoft Purview compliance portal. To hard-delete programmatically requires the **eDiscovery/compliance APIs** which need additional licensing (E3/E5).

### Rate Limits
- Graph API allows **10,000 requests per 10 minutes per app**
- With `sleep(1)` between batches of 10, you make ~60 requests/minute = well within limits
- Always handle `429 Too Many Requests` responses — read `Retry-After` header and sleep that many seconds
- The purge_engine already implements this

### Time Estimates
- Per batch: ~10 deletes + 1s sleep = ~2s per batch
- 12,000 emails = 1,200 batches = ~2,400 seconds = ~40 minutes (not 3–4 hours)
- For a 32 GB mailbox with hundreds of thousands of items: realistic estimate 3–6 hours continuous

### Token Refresh
MSAL `acquire_token_for_client()` automatically caches and refreshes the app token. The token is valid for 1 hour. No manual refresh logic is needed for app-only flows.

### Multiple Concurrent Jobs
Celery with `--concurrency=4` allows 4 simultaneous purge jobs. Each job is independent. Redis tracks task state.

### SQLite Concurrency Warning
SQLite is fine for single-server deployments. If you run multiple backend instances behind a load balancer, switch `DATABASE_URL` to PostgreSQL.

---

## Step-by-Step Build Order for Claude Code

Follow this exact order. Each step should be buildable and testable before moving to the next.

### Phase 1: Foundation

**Step 1 — Project scaffold**
- Create folder structure as defined above
- Create `.env` from `.env.example`
- Create `docker-compose.yml`, both `Dockerfile`s

**Step 2 — Backend dependencies**
- Create `requirements.txt`
- Create `database.py`
- Create `models.py`
- Create `schemas.py`
- Create `celery_app.py`
- Run `alembic init` or let SQLAlchemy create tables on first run

**Step 3 — Auth module**
- Create `auth.py` with `get_app_token()`, `get_auth_url()`, `exchange_code_for_token()`
- Test: run `python -c "from auth import get_app_token; print(get_app_token())"` — should print a JWT

**Step 4 — Graph API module**
- Create `graph.py` with all functions
- Test each function individually with a known mailbox email

### Phase 2: Backend API

**Step 5 — FastAPI app skeleton**
- Create `main.py` with all routes stubbed
- `docker-compose up redis backend`
- Test: `curl http://localhost:8000/docs` should show Swagger UI

**Step 6 — Auth endpoints working**
- `POST /api/auth/login` returns auth_url
- `GET /api/auth/callback` exchanges code and redirects
- Test with a browser — complete the OAuth flow

**Step 7 — Users and search endpoints**
- `GET /api/users` returns mailbox list
- `POST /api/search/preview` returns count
- Test both with curl or Swagger UI

**Step 8 — Purge engine**
- Create `purge_engine.py` with `purge_loop` Celery task
- `docker-compose up worker`
- Test: manually dispatch a task from Python shell and watch logs

**Step 9 — Purge endpoints**
- `POST /api/purge/start` dispatches task, returns job
- `GET /api/purge/status/{job_id}` returns live stats
- `POST /api/purge/stop/{job_id}` sets STOPPED status
- `GET /api/jobs/history`
- `DELETE /api/jobs/{job_id}`

### Phase 3: Frontend

**Step 10 — React scaffold**
- `npm create vite@latest frontend -- --template react`
- Install dependencies from `package.json`
- Configure Tailwind (`tailwind.config.js`, `postcss.config.js`)
- Create `main.jsx`, `App.jsx` with router

**Step 11 — API client**
- Create `src/api/client.js`
- Test each function in browser console

**Step 12 — Login page**
- Create `LoginPage.jsx`
- "Sign in with Microsoft" button triggers redirect

**Step 13 — Users page**
- Create `UsersPage.jsx`
- Searchable table of mailboxes

**Step 14 — Purge page**
- Create `PurgePage.jsx`
- User dropdown, date pickers, Preview button, Start Purge button
- On start: navigate to `/dashboard/{jobId}`

**Step 15 — Dashboard page**
- Create `DashboardPage.jsx`
- Create `useJobPolling.js` hook (polls every 3s)
- Progress bar, stats grid, ETA, Stop button

**Step 16 — History page**
- Create `HistoryPage.jsx`
- Table of all past jobs with View/Delete actions

**Step 17 — Navbar**
- Create `Navbar.jsx`
- Links to Purge / Users / History

### Phase 4: Integration & Polish

**Step 18 — End-to-end test**
- `docker-compose up` — all 4 services running
- Login via browser
- Select a test user's mailbox
- Preview count for a date range with known emails
- Start purge, watch dashboard update every 3s
- Verify emails are gone from Outlook

**Step 19 — Error handling**
- Add try/catch to all frontend API calls with user-visible error messages
- Handle `401 Unauthorized` globally in axios interceptor — redirect to login
- Backend: add proper HTTP status codes and error details

**Step 20 — Final checks**
- Confirm `.env` is in `.gitignore`
- Confirm Graph API permissions show "Granted" in Azure portal
- Test stop/resume behavior
- Test with a mailbox that has 0 matching emails (should complete immediately)

---

## Common Errors and Fixes

| Error | Cause | Fix |
|---|---|---|
| `AADSTS700016` | CLIENT_ID wrong or app not registered in tenant | Double-check CLIENT_ID and TENANT_ID in `.env` |
| `403 Forbidden` from Graph | Admin consent not granted | Go to Azure portal → API Permissions → Grant admin consent |
| `401 Unauthorized` | Token expired or wrong scope | Ensure using Application permissions not Delegated; check MSAL scope is `https://graph.microsoft.com/.default` |
| `400 Bad Request` on filter | Wrong date format | Use `T00:00:00Z` suffix — not just `YYYY-MM-DD` |
| `429 Too Many Requests` | Rate limit hit | Check Retry-After header; purge_engine already handles this |
| Celery tasks not running | Redis not reachable | Confirm `REDIS_URL` matches redis service name in docker-compose |
| SQLite locked | Multiple writers | Use `check_same_thread=False` (already in database.py); or switch to PostgreSQL |
