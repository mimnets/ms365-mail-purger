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
    top: int = 10,
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

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await search_messages(user_email, date_from, date_to, top)
        resp.raise_for_status()
        messages = resp.json().get("value", [])
        return [m["id"] for m in messages]


async def count_messages(
    user_email: str,
    date_from: str,
    date_to: str,
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
    headers = {**_headers(), "ConsistencyLevel": "eventual"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("@odata.count", 0)


async def delete_message(user_email: str, message_id: str) -> bool:
    """Delete a single message from the primary mailbox."""
    url = f"{GRAPH_BASE}/users/{user_email}/messages/{message_id}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(url, headers=_headers())
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await delete_message(user_email, message_id)
        return resp.status_code == 204


# ═════════════════════════════════════════════════════════════════════════════
#  Archive Mailbox Functions
# ═════════════════════════════════════════════════════════════════════════════


async def get_archive_folder_id(user_email: str) -> Optional[str]:
    """
    Find the in-place archive folder ID for a user.
    Returns the archive folder ID, or None if no archive is configured.
    """
    url = f"{GRAPH_BASE}/users/{user_email}/mailFolders"
    # wellKnownName is NOT filterable in Graph API, so fetch all and filter locally
    params = {"$select": "id,displayName,wellKnownName", "$top": 50}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await get_archive_folder_id(user_email)
        resp.raise_for_status()
        folders = resp.json().get("value", [])
        for folder in folders:
            if folder.get("wellKnownName") == "archive":
                return folder["id"]
        return None


async def get_archive_child_folders(user_email: str, archive_folder_id: str) -> List[Dict]:
    """
    Get child folders under the archive folder.
    Messages in the archive live in child folders (Inbox, Sent Items, etc.)
    """
    url = f"{GRAPH_BASE}/users/{user_email}/mailFolders/{archive_folder_id}/childFolders"
    params = {
        "$select": "id,displayName,wellKnownName,totalItemCount",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await get_archive_child_folders(user_email, archive_folder_id)
        resp.raise_for_status()
        return resp.json().get("value", [])


async def search_archive_messages(
    user_email: str,
    archive_folder_id: str,
    date_from: str,
    date_to: str,
    top: int = 10,
    child_folder_id: Optional[str] = None,
) -> List[str]:
    """
    Search messages in the archive mailbox folder.
    If child_folder_id is provided, searches that child folder;
    otherwise searches the archive root.
    Returns list of message IDs.
    """
    if child_folder_id:
        url = (
            f"{GRAPH_BASE}/users/{user_email}"
            f"/mailFolders/{archive_folder_id}"
            f"/childFolders/{child_folder_id}"
            f"/messages"
        )
    else:
        url = (
            f"{GRAPH_BASE}/users/{user_email}"
            f"/mailFolders/{archive_folder_id}"
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

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await search_archive_messages(
                user_email, archive_folder_id, date_from, date_to, top, child_folder_id
            )
        resp.raise_for_status()
        messages = resp.json().get("value", [])
        return [m["id"] for m in messages]


async def delete_archive_message(
    user_email: str,
    archive_folder_id: str,
    message_id: str,
    child_folder_id: Optional[str] = None,
) -> bool:
    """Delete a single message from the archive mailbox."""
    if child_folder_id:
        url = (
            f"{GRAPH_BASE}/users/{user_email}"
            f"/mailFolders/{archive_folder_id}"
            f"/childFolders/{child_folder_id}"
            f"/messages/{message_id}"
        )
    else:
        url = (
            f"{GRAPH_BASE}/users/{user_email}"
            f"/mailFolders/{archive_folder_id}"
            f"/messages/{message_id}"
        )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(url, headers=_headers())
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await delete_archive_message(
                user_email, archive_folder_id, message_id, child_folder_id
            )
        return resp.status_code == 204


async def count_archive_messages(
    user_email: str,
    archive_folder_id: str,
    date_from: str,
    date_to: str,
) -> int:
    """Count messages across all archive child folders matching the date range."""
    child_folders = await get_archive_child_folders(user_email, archive_folder_id)
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
        headers = {**_headers(), "ConsistencyLevel": "eventual"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                await asyncio.sleep(retry_after)
                return await count_archive_messages(
                    user_email, archive_folder_id, date_from, date_to
                )
            if resp.status_code == 200:
                data = resp.json()
                total += data.get("@odata.count", 0)

    return total
