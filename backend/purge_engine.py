"""
Purge engine for M365 Mail Purger v3.

Replaces the old pwsh-based compliance search approach with direct
Microsoft Graph REST API calls using httpx.

The purge loop:
1. Acquires a token using MSAL + the org's stored certificate private key
2. Phase 1: Primary mailbox — search and delete messages in batches of 10
3. Phase 2: Archive mailbox — find archive folder, iterate child folders,
   search and delete messages in batches of 10
4. Reports progress to the database after each batch
"""

import asyncio
import time
import os
import traceback
import base64
import httpx
import msal
from datetime import datetime
from typing import Dict, List, Optional

from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption

from celery_app import celery_app
from database import SessionLocal
from models import PurgeJob, JobStatus, Organization
from cert_utils import decrypt_value, get_fernet

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
BATCH_SIZE = 10


# ═════════════════════════════════════════════════════════════════════════════
#  Database Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _update_job(db, job_id: str, **kwargs):
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if job:
        for k, v in kwargs.items():
            setattr(job, k, v)
        db.commit()
    return job


def _get_job_or_stopped(db, job_id: str) -> Optional[PurgeJob]:
    """Fetch the job. Returns None if the job has been stopped."""
    db.expire_all()
    job = db.query(PurgeJob).filter(PurgeJob.id == job_id).first()
    if job and job.status == JobStatus.STOPPED:
        return None
    return job


# ═════════════════════════════════════════════════════════════════════════════
#  Token Acquisition (MSAL + certificate)
# ═════════════════════════════════════════════════════════════════════════════

def _extract_private_key_pem(raw_pfx: bytes, password: str) -> str:
    """Extract the private key from a PFX blob as PEM string."""
    private_key, _cert, _additional = pkcs12.load_key_and_certificates(raw_pfx, password.encode())
    if private_key is None:
        raise RuntimeError("No private key found in PFX certificate")
    return private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode()


def acquire_graph_token(
    client_id: str,
    tenant_id: str,
    private_key_pem: str,
    thumbprint: str,
) -> str:
    """
    Acquire an OAuth2 access token for Microsoft Graph using a client
    certificate (private key) via MSAL client credentials flow.
    """
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scope = ["https://graph.microsoft.com/.default"]

    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential={
            "private_key": private_key_pem,
            "thumbprint": thumbprint,
        },
    )

    result = app.acquire_token_for_client(scopes=scope)

    if "access_token" not in result:
        error_desc = result.get("error_description", str(result))
        raise RuntimeError(f"MSAL token acquisition failed: {error_desc}")

    return result["access_token"]


# ═════════════════════════════════════════════════════════════════════════════
#  Graph API HTTP Helpers (async, token-aware)
# ═════════════════════════════════════════════════════════════════════════════

def _auth_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


async def _graph_get(url: str, access_token: str, params: Optional[Dict] = None) -> Dict:
    """Perform a GET request to Graph API with retry on 429."""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(5):
            resp = await client.get(url, headers=_auth_headers(access_token), params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                await asyncio.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp.json()
    raise RuntimeError(f"GET {url} failed after 5 retries (rate limited)")


async def _graph_delete(url: str, access_token: str) -> bool:
    """Perform a DELETE request to Graph API with retry on 429."""
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(5):
            resp = await client.delete(url, headers=_auth_headers(access_token))
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                await asyncio.sleep(retry_after)
                continue
            return resp.status_code == 204
    return False


# ═════════════════════════════════════════════════════════════════════════════
#  Primary Mailbox Operations
# ═════════════════════════════════════════════════════════════════════════════

async def search_primary_messages(
    user_email: str,
    date_from: str,
    date_to: str,
    access_token: str,
    top: int = BATCH_SIZE,
) -> List[str]:
    """Search messages in the primary mailbox. Returns list of message IDs."""
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
    data = await _graph_get(url, access_token, params)
    return [m["id"] for m in data.get("value", [])]


async def delete_primary_message(user_email: str, message_id: str, access_token: str) -> bool:
    """Delete a single message from the primary mailbox."""
    url = f"{GRAPH_BASE}/users/{user_email}/messages/{message_id}"
    return await _graph_delete(url, access_token)


async def count_primary_messages(
    user_email: str,
    date_from: str,
    date_to: str,
    access_token: str,
) -> int:
    """Count messages in the primary mailbox matching the date range."""
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
    headers = {**_auth_headers(access_token), "ConsistencyLevel": "eventual"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await count_primary_messages(user_email, date_from, date_to, access_token)
        resp.raise_for_status()
        return resp.json().get("@odata.count", 0)


# ═════════════════════════════════════════════════════════════════════════════
#  Archive Mailbox Operations
# ═════════════════════════════════════════════════════════════════════════════

async def find_archive_folder_id(
    user_email: str,
    access_token: str,
) -> Optional[str]:
    """Find the in-place archive folder ID for a user. Returns None if not available."""
    url = f"{GRAPH_BASE}/users/{user_email}/mailFolders"
    params = {
        "$filter": "wellKnownName eq 'archive'",
        "$select": "id,displayName,wellKnownName",
        "$top": 1,
    }
    data = await _graph_get(url, access_token, params)
    folders = data.get("value", [])
    if folders:
        return folders[0]["id"]
    return None


async def get_archive_child_folders(
    user_email: str,
    archive_folder_id: str,
    access_token: str,
) -> List[Dict]:
    """Get child folders under the archive folder (Inbox, Sent Items, etc.)."""
    url = (
        f"{GRAPH_BASE}/users/{user_email}"
        f"/mailFolders/{archive_folder_id}/childFolders"
    )
    params = {"$select": "id,displayName,wellKnownName,totalItemCount"}
    data = await _graph_get(url, access_token, params)
    return data.get("value", [])


async def search_archive_child_messages(
    user_email: str,
    archive_folder_id: str,
    child_folder_id: str,
    date_from: str,
    date_to: str,
    access_token: str,
    top: int = BATCH_SIZE,
) -> List[str]:
    """Search messages in a specific child folder of the archive. Returns message IDs."""
    url = (
        f"{GRAPH_BASE}/users/{user_email}"
        f"/mailFolders/{archive_folder_id}"
        f"/childFolders/{child_folder_id}"
        f"/messages"
    )
    params = {
        "$filter": (
            f"receivedDateTime ge {date_from}T00:00:00Z "
            f"and receivedDateTime le {date_to}T23:59:59Z"
        ),
        "$select": "id,subject,receivedDateTime",
        "$top": top,
        "$orderby": "receivedDateTime asc",
    }
    data = await _graph_get(url, access_token, params)
    return [m["id"] for m in data.get("value", [])]


async def delete_archive_child_message(
    user_email: str,
    archive_folder_id: str,
    child_folder_id: str,
    message_id: str,
    access_token: str,
) -> bool:
    """Delete a single message from a child folder of the archive."""
    url = (
        f"{GRAPH_BASE}/users/{user_email}"
        f"/mailFolders/{archive_folder_id}"
        f"/childFolders/{child_folder_id}"
        f"/messages/{message_id}"
    )
    return await _graph_delete(url, access_token)


# ═════════════════════════════════════════════════════════════════════════════
#  Purge Loop (Celery task)
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
#  Sync wrappers (bridge between async Graph API and sync Celery task)
# ═════════════════════════════════════════════════════════════════════════════

def _count_archive_messages_sync(
    user_email: str,
    archive_folder_id: str,
    date_from: str,
    date_to: str,
    access_token: str,
    child_folders: List[Dict],
) -> int:
    """Sync wrapper to count archive messages across child folders."""
    async def _count():
        total = 0
        for folder in child_folders:
            folder_id = folder["id"]
            url = (
                f"{GRAPH_BASE}/users/{user_email}"
                f"/mailFolders/{archive_folder_id}"
                f"/childFolders/{folder_id}"
                f"/messages"
            )
            params = {
                "$filter": (
                    f"receivedDateTime ge {date_from}T00:00:00Z "
                    f"and receivedDateTime le {date_to}T23:59:59Z"
                ),
                "$count": "true",
                "$top": 1,
                "$select": "id",
            }
            headers = {**_auth_headers(access_token), "ConsistencyLevel": "eventual"}
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    total += resp.json().get("@odata.count", 0)
        return total
    return asyncio.run(_count())


@celery_app.task(bind=True, name="purge_engine.purge_loop")
def purge_loop(self, job_id: str, org_id: str, user_email: str, date_from: str, date_to: str):
    """
    Purge emails from a user's mailbox (primary + in-place archive)
    using the Microsoft Graph REST API directly.

    Flow:
      1. Acquire MSAL token using the org's stored certificate
      2. Phase 1: Iterate primary mailbox messages in batches, delete each
      3. Phase 2: Find archive folder, iterate child folders, delete each message
      4. Update DB progress after each batch
    """
    db = SessionLocal()
    total_primary_found = 0
    total_archive_found = 0
    total_deleted = 0
    access_token = None
    archive_folder_id = None
    archive_child_folders = []

    try:
        _update_job(db, job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
            celery_task_id=self.request.id,
            total_found=0,
            total_deleted=0,
            total_remaining=0,
        )

        # ── Load org & decrypt certificate ──────────────────────────────────
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            raise ValueError(f"Organization {org_id} not found")

        fernet = get_fernet()

        if not org.certificate_pfx or not org.certificate_password:
            raise ValueError(
                f"Organization '{org.name}' has no certificate configured. "
                "Generate one in Settings first."
            )

        cert_pfx_b64 = decrypt_value(org.certificate_pfx, fernet)
        cert_pass_plain = decrypt_value(org.certificate_password, fernet)

        try:
            raw_pfx = base64.b64decode(cert_pfx_b64)
        except Exception:
            raw_pfx = cert_pfx_b64.encode("latin-1")

        # Extract private key from PFX
        private_key_pem = _extract_private_key_pem(raw_pfx, cert_pass_plain)

        # Acquire Graph API token
        access_token = acquire_graph_token(
            client_id=org.app_client_id,
            tenant_id=org.tenant_id,
            private_key_pem=private_key_pem,
            thumbprint=org.certificate_thumbprint,
        )

        _update_job(db, job_id, status_message="Token acquired, starting purge")

        # ── Phase 1: Primary Mailbox ───────────────────────────────────────
        _update_job(db, job_id, status_message="Phase 1/2: Purging primary mailbox")

        # Get initial count for progress tracking
        total_primary_found = asyncio.run(
            count_primary_messages(user_email, date_from, date_to, access_token)
        )
        _update_job(db, job_id, total_found=total_primary_found, total_remaining=total_primary_found)

        while True:
            job = _get_job_or_stopped(db, job_id)
            if job is None:
                return  # Stopped by user

            message_ids = asyncio.run(
                search_primary_messages(user_email, date_from, date_to, access_token, BATCH_SIZE)
            )

            if not message_ids:
                break  # No more primary messages in range

            for msg_id in message_ids:
                job = _get_job_or_stopped(db, job_id)
                if job is None:
                    return

                success = asyncio.run(
                    delete_primary_message(user_email, msg_id, access_token)
                )
                if success:
                    total_deleted += 1

                remaining = max(0, (total_primary_found + total_archive_found) - total_deleted)
                _update_job(db, job_id,
                    total_deleted=total_deleted,
                    total_remaining=remaining,
                    status_message=f"Primary: deleted {total_deleted} of {total_primary_found + total_archive_found}",
                )

            # Small delay between batches to avoid rate limits
            asyncio.run(asyncio.sleep(1))

        # ── Phase 2: Archive Mailbox ───────────────────────────────────────
        _update_job(db, job_id, status_message="Phase 2/2: Checking archive mailbox")

        archive_folder_id = asyncio.run(
            find_archive_folder_id(user_email, access_token)
        )

        if archive_folder_id:
            _update_job(db, job_id, status_message="Phase 2/2: Purging archive mailbox")

            archive_child_folders = asyncio.run(
                get_archive_child_folders(user_email, archive_folder_id, access_token)
            )

            # Count archive messages first
            archive_count = _count_archive_messages_sync(
                user_email, archive_folder_id, date_from, date_to,
                access_token, archive_child_folders,
            )

            total_archive_found = archive_count
            total_found = total_primary_found + total_archive_found
            remaining = max(0, total_found - total_deleted)
            _update_job(db, job_id,
                total_found=total_found,
                total_remaining=remaining,
            )

            # Process each archive child folder
            for folder in archive_child_folders:
                child_folder_id = folder["id"]
                child_folder_name = folder.get("displayName", child_folder_id)

                while True:
                    job = _get_job_or_stopped(db, job_id)
                    if job is None:
                        return

                    message_ids = asyncio.run(
                        search_archive_child_messages(
                            user_email, archive_folder_id, child_folder_id,
                            date_from, date_to, access_token, BATCH_SIZE,
                        )
                    )

                    if not message_ids:
                        break  # No more messages in this child folder

                    for msg_id in message_ids:
                        job = _get_job_or_stopped(db, job_id)
                        if job is None:
                            return

                        success = asyncio.run(
                            delete_archive_child_message(
                                user_email, archive_folder_id, child_folder_id,
                                msg_id, access_token,
                            )
                        )
                        if success:
                            total_deleted += 1

                        remaining = max(0, total_found - total_deleted)
                        _update_job(db, job_id,
                            total_deleted=total_deleted,
                            total_remaining=remaining,
                            status_message=(
                                f"Archive [{child_folder_name}]: "
                                f"deleted {total_deleted} of {total_found}"
                            ),
                        )

                    # Small delay between batches
                    asyncio.run(asyncio.sleep(1))

        else:
            _update_job(db, job_id, status_message="No archive mailbox found")

        # ── Final status ───────────────────────────────────────────────────
        total_found = total_primary_found + total_archive_found
        _update_job(db, job_id,
            status=JobStatus.COMPLETE,
            total_found=total_found,
            total_deleted=total_deleted,
            total_remaining=max(0, total_found - total_deleted),
            completed_at=datetime.utcnow(),
            status_message="Purge complete",
        )

    except Exception as e:
        _update_job(db, job_id,
            status=JobStatus.FAILED,
            error_message=f"{e}\n{traceback.format_exc()}",
            total_deleted=total_deleted,
            total_remaining=max(
                0,
                (total_primary_found + total_archive_found) - total_deleted,
            ),
            completed_at=datetime.utcnow(),
            status_message="Failed",
        )
        raise

    finally:
        db.close()
