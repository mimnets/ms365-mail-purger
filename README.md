# M365 Mail Purger

Web app for M365 admins to bulk-delete emails from any user's mailbox
**including in-place archive**. Uses Microsoft Purview compliance search
via Connect-IPPSSession (PowerShell on Linux) with a live progress dashboard.

---

## Architecture

```
Browser (React)
    │  polls every 3s
    ▼
FastAPI (port 8000)
    │  dispatches task
    ▼
Celery Worker ──── Redis (queue)
    │  spawns pwsh subprocess
    ▼
PowerShell Core (on Linux)
    │  Connect-IPPSSession
    │  New-ComplianceSearch
    │  New-ComplianceSearchAction -Purge
    ▼
M365 Tenant (primary mailbox + in-place archive)
```

**Key difference from v1:** This version uses **Connect-IPPSSession** (Purview compliance
PowerShell) instead of plain Graph API. This allows purging emails from the
**in-place archive**, which Graph API cannot do.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Microsoft 365 tenant with Global Admin access
- Azure App Registration (see Setup Guide in-app or steps below)

---

## Quick Start

### 1. Configure Environment

Copy `.env.example` to `.env` and set the encryption key:

```bash
cp .env.example .env

# Generate a strong encryption key
python3 -c "import secrets; print(secrets.token_hex(32))"
# Copy the output into .env as ENCRYPTION_KEY
```

Your `.env` should look like:

```env
ENCRYPTION_KEY=your-64-char-hex-string-here
ADMIN_EMAIL=your-admin@yourorg.com
REDIS_URL=redis://redis:6379/0
DATABASE_URL=sqlite:///./data/purger.db
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

### 2. Build and Run

```bash
docker-compose up --build
```

This starts 4 services:

| Service | URL | Purpose |
|---|---|---|
| `frontend` | http://localhost:3000 | React UI |
| `backend` | http://localhost:8000 | FastAPI |
| `worker` | — | Celery + pwsh task runner |
| `redis` | localhost:6379 | Task queue |

First build takes **~5 minutes** (installing PowerShell Core + ExchangeOnlineManagement).

### 3. Configure an Organization via the UI

1. Open http://localhost:3000
2. Go to **Settings** → **Add Organization**
3. Enter your Azure AD details:
   - Organization name (e.g. "VCL Bangladesh")
   - Tenant ID (Directory ID from Azure)
   - Tenant domain (e.g. `vclbd.onmicrosoft.com`)
   - App (Client) ID
   - Admin UPN (your admin email)
4. Click **Generate Certificate** — downloads a `.cer` file
5. **Upload the `.cer` to Azure AD**:
   - Azure portal → App Registrations → your app → Certificates & secrets → Certificates → Upload
6. Grant API permissions & assign eDiscovery Manager role (see Setup Guide in the app)

### 4. Start Purging

1. Go to **Purge** tab
2. Select your organization
3. Select a mailbox
4. Pick a date range
5. Click **Preview Count** to see how many emails match
6. Click **Start Purge**
7. Watch the live dashboard

---

## PowerShell Purge Flow

Each purge job:

1. Reads encrypted certificate from DB → writes temp `.pfx` file
2. Spawns `pwsh` → runs `Connect-IPPSSession` with certificate auth
3. Splits date range into **weekly chunks**
4. For each chunk:
   - Creates `New-ComplianceSearch`
   - Waits for search to complete
   - Creates `New-ComplianceSearchAction -Purge` (soft delete, 10 items per action)
   - Reports progress back to Python via stdout
5. Cleans up compliance artifacts
6. Python updates DB → frontend polls for live status

**Coverage:** Searches and purges from **both primary mailbox and in-place archive**.

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

## Security Notes

- `.env` is in `.gitignore` — never commit it
- Certificates are **encrypted at rest** in SQLite using Fernet (AES-128-CBC)
- The `ENCRYPTION_KEY` in `.env` is the master key — protect it
- Temp cert files are written to `/tmp` and cleaned up after each job
- Compliance searches and actions are cleaned up after each purge
- Test with a small date range first before purging large mailboxes

---

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `AADSTS700016` | Wrong CLIENT_ID | Check App ID in Azure portal |
| `403 Forbidden` in compliance | Admin consent not granted | Azure → API Permissions → Grant consent |
| `eDiscovery Manager role required` | Role not assigned | Purview portal → Permissions → eDiscovery Manager |
| `Certificate not found` | Cert not uploaded to Azure | Upload .cer to App Registration |
| No users showing | Graph API permissions | Check Mail.ReadWrite + User.Read.All are granted |
| Purge stuck at QUEUED | Redis down | Check `docker-compose ps` |
| `pwsh: command not found` | Docker build issue | Rebuild with `docker-compose up --build` |

---

## Graph API vs Connect-IPPSSession

| Feature | Graph API (v1) | Connect-IPPSSession (v2 ✓) |
|---|---|---|
| Primary mailbox delete | ✅ | ✅ |
| In-place archive delete | ❌ | ✅ |
| Requires PowerShell | ❌ | ✅ (pwsh on Linux) |
| Delete method | `DELETE /messages/{id}` | Compliance search + purge action |
| Items per delete action | 1 per request | 10 per purge action |
| Rate limit | 10K req/10 min | Compliance: 50 searches/day, unlimited purges |
| Soft/hard delete | Soft only | Soft (and hard with appropriate licensing) |
