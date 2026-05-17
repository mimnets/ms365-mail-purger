import httpx
import asyncio
from typing import List, Dict
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
    top: int = 10
) -> List[str]:
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
    date_to: str
) -> int:
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
    url = f"{GRAPH_BASE}/users/{user_email}/messages/{message_id}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(url, headers=_headers())
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            await asyncio.sleep(retry_after)
            return await delete_message(user_email, message_id)
        return resp.status_code == 204
