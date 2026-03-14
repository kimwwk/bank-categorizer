import httpx

from app.config import settings

_TIMEOUT = 30.0


def _auth() -> dict:
    return {
        "client_id": settings.plaid_client_id,
        "secret": settings.plaid_secret,
    }


async def item_get() -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(
            f"{settings.plaid_base_url}/item/get",
            json={**_auth(), "access_token": settings.plaid_access_token},
        )
        r.raise_for_status()
        return r.json()


async def transactions_sync(cursor: str | None = None) -> dict:
    """Call /transactions/sync and paginate until has_more is false.

    Returns combined added/modified/removed lists and the final cursor.
    """
    added, modified, removed = [], [], []
    current_cursor = cursor or ""

    while True:
        body = {
            **_auth(),
            "access_token": settings.plaid_access_token,
            "cursor": current_cursor,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{settings.plaid_base_url}/transactions/sync",
                json=body,
            )
            r.raise_for_status()
            data = r.json()

        added.extend(data.get("added", []))
        modified.extend(data.get("modified", []))
        removed.extend(data.get("removed", []))
        current_cursor = data.get("next_cursor", current_cursor)

        if not data.get("has_more", False):
            break

    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "cursor": current_cursor,
    }
