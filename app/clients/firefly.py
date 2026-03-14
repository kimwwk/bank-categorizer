import httpx

from app.config import settings

_TIMEOUT = 30.0


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.firefly_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get(
            f"{settings.firefly_url}/api/v1{path}",
            headers=_headers(),
            params=params,
        )
        r.raise_for_status()
        return r.json()


async def post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(
            f"{settings.firefly_url}/api/v1{path}",
            headers=_headers(),
            json=body,
        )
        r.raise_for_status()
        if r.status_code == 204:
            return {}
        return r.json()


async def put(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.put(
            f"{settings.firefly_url}/api/v1{path}",
            headers=_headers(),
            json=body,
        )
        r.raise_for_status()
        if r.status_code == 204:
            return {}
        return r.json()


async def delete(path: str) -> bool:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.delete(
            f"{settings.firefly_url}/api/v1{path}",
            headers=_headers(),
        )
        r.raise_for_status()
        return True


async def get_all_pages(path: str, params: dict | None = None) -> list[dict]:
    """Paginate through all results, returning combined data list."""
    items = []
    page = 1
    while True:
        p = {**(params or {}), "page": page}
        resp = await get(path, p)
        data = resp.get("data", [])
        if not data:
            break
        items.extend(data)
        meta = resp.get("meta", {}).get("pagination", {})
        if page >= meta.get("total_pages", 1):
            break
        page += 1
    return items


async def search_transactions(query: str) -> list[dict]:
    return await get_all_pages("/search/transactions", {"query": query})


async def get_all_rules() -> list[dict]:
    return await get_all_pages("/rules")


async def get_all_categories() -> list[str]:
    items = await get_all_pages("/categories")
    return [c["attributes"]["name"] for c in items]


def _account_ids() -> list[str]:
    """Get all mapped Firefly account IDs, or ["1"] as fallback."""
    mapping = settings.account_mapping
    if mapping:
        return list(set(mapping.values()))
    return ["1"]


async def trigger_rule_group(group_id: int = 1):
    params = [("accounts[]", aid) for aid in _account_ids()]
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            f"{settings.firefly_url}/api/v1/rule-groups/{group_id}/trigger",
            headers=_headers(),
            params=params,
        )
        r.raise_for_status()


async def trigger_rule(rule_id: int):
    params = [("accounts[]", aid) for aid in _account_ids()]
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            f"{settings.firefly_url}/api/v1/rules/{rule_id}/trigger",
            headers=_headers(),
            params=params,
        )
        r.raise_for_status()
