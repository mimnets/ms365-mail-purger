# M365 Mail Purger

Web app for M365 admins to bulk-delete emails from any tenant mailbox by date range. Uses Microsoft Graph API with Celery background workers and a live progress dashboard.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Microsoft 365 tenant with Global Admin access
- Azure App Registration (see below)

---

## Step 1 — Get Azure Credentials

### 1.1 Create the App Registration

1. Go to [portal.azure.com](https://portal.azure.com) and sign in as **Global Admin**
2. Search for **"App registrations"** in the top search bar → click it
3. Click **New registration**
4. Fill in:
   - **Name:** `M365 Mail Purger`
   - **Supported account types:** `Accounts in this organizational directory only`
   - **Redirect URI:** Platform = `Web`, URL = `http://localhost:8000/api/auth/callback`
5. Click **Register**

### 1.2 Copy CLIENT_ID and TENANT_ID

On the app's **Overview** page:

| Value | Where |
|---|---|
| `CLIENT_ID` | "Application (client) ID" field |
| `TENANT_ID` | "Directory (tenant) ID" field |

Copy both — you'll need them in `.env`.

### 1.3 Create a Client Secret

1. Left sidebar → **Certificates & secrets**
2. Click **New client secret**
3. Description: `mail-purger-secret`, Expiry: `24 months`
4. Click **Add**
5. **Copy the `Value` immediately** — it's hidden after you leave this page
   - This is your `CLIENT_SECRET`

### 1.4 Add API Permissions

1. Left sidebar → **API permissions**
2. Click **Add a permission → Microsoft Graph → Application permissions**
3. Search and add each of these:

   | Permission | Purpose |
   |---|---|
   | `Mail.ReadWrite` | Read and delete emails |
   | `Mail.ReadWrite.Shared` | Shared mailbox access |
   | `User.Read.All` | List all users/mailboxes |
   | `MailboxSettings.Read` | Read mailbox metadata |
   | `Reports.Read.All` | Mailbox usage stats |

4. After adding all 5, click **Grant admin consent for [your tenant]**
5. Confirm — all permissions must show a **green checkmark** under Status

> **Important:** Without admin consent, all Graph API calls will return `403 Forbidden`.

---

## Step 2 — Configure Environment

Edit the `.env` file in the project root:

```env
# Azure App Registration
CLIENT_ID=paste-your-client-id-here
CLIENT_SECRET=paste-your-client-secret-here
TENANT_ID=paste-your-tenant-id-here

# Auth
REDIRECT_URI=http://localhost:8000/api/auth/callback
FRONTEND_URL=http://localhost:3000
SESSION_SECRET=generate-a-random-32-char-string

# Redis (leave as-is for Docker)
REDIS_URL=redis://redis:6379/0

# Database
DATABASE_URL=sqlite:///./purger.db

# Admin email
ADMIN_EMAIL=your-admin@yourtenant.com
```

Generate a random `SESSION_SECRET`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Step 3 — Build and Run

```bash
# From project root
cd /path/to/ms365-mail-purger

# Build and start all services (first run takes ~2 minutes to download images)
docker-compose up --build
```

This starts 4 services:

| Service | URL | Purpose |
|---|---|---|
| `frontend` | http://localhost:3000 | React UI |
| `backend` | http://localhost:8000 | FastAPI |
| `worker` | — | Celery background task runner |
| `redis` | localhost:6379 | Task queue + result backend |

### Verify everything is up

```bash
# Check all containers running
docker-compose ps

# Backend API docs (Swagger UI)
open http://localhost:8000/docs

# Frontend
open http://localhost:3000
```

---

## Step 4 — Using the App

1. Open `http://localhost:3000`
2. Go to **Purge** tab
3. Select a mailbox from the dropdown
4. Set **Date From** and **Date To**
5. Click **Preview Count** — shows how many emails match
6. Click **Start Purge** — redirects to live dashboard
7. Dashboard auto-refreshes every 3 seconds showing:
   - Total found / deleted / remaining
   - Progress bar
   - ETA
   - Stop button (halts the job mid-run)

---

## Common Commands

```bash
# Start (background)
docker-compose up -d --build

# Stop
docker-compose down

# View logs
docker-compose logs -f backend
docker-compose logs -f worker

# Restart a single service
docker-compose restart worker

# Wipe everything (including DB volume)
docker-compose down -v
```

---

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `AADSTS700016` | Wrong `CLIENT_ID` or wrong tenant | Double-check both IDs in `.env` |
| `403 Forbidden` from Graph | Admin consent not granted | Azure portal → API Permissions → Grant admin consent |
| `401 Unauthorized` | Wrong scope or wrong permission type | Ensure Application permissions (not Delegated) are used |
| `400 Bad Request` on filter | Bad date format | Use `YYYY-MM-DD` in the UI date pickers |
| `429 Too Many Requests` | Graph rate limit hit | App handles this automatically with `Retry-After` backoff |
| Celery tasks stuck in QUEUED | Redis not reachable | Check `docker-compose ps` — redis container must be running |
| Frontend can't reach backend | CORS or backend down | Confirm backend is on port 8000; check `docker-compose logs backend` |

---

## Architecture

```
Browser (React)
    │  polls every 3s
    ▼
FastAPI (port 8000)
    │  dispatches task
    ▼
Celery Worker ──── Redis (queue + results)
    │
    ▼
Microsoft Graph API
    │
    ▼
M365 Tenant Mailboxes
```

**Delete behavior:** Graph API `DELETE /messages/{id}` is a **soft delete** — moves email to Recoverable Items. Permanently purged after 14–30 days per tenant retention policy.

---

## Security Notes

- `.env` is in `.gitignore` — never commit it
- `CLIENT_SECRET` expires in 24 months — rotate before expiry in Azure portal
- App uses **Application permissions** (no per-user login needed for Graph calls)
- Admin OAuth login is for UI authentication only
