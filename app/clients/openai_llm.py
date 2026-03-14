import json

import httpx

from app.config import settings

_TIMEOUT = 60.0
_URL = "https://api.openai.com/v1/chat/completions"


async def categorize(merchants: list[str], categories: list[str]) -> dict[str, str]:
    """Ask LLM to map merchant names to categories.

    Returns dict of {merchant: category}.
    """
    prompt = (
        "You are a financial transaction categorizer.\n"
        "Given these valid categories:\n"
        f"{', '.join(categories)}\n\n"
        "Categorize each merchant below into exactly one category from the list above.\n"
        "Return JSON: {\"merchant_name\": \"category_name\", ...}\n"
        "Do NOT invent new categories. If unsure, use the closest match.\n\n"
        "Merchants:\n"
        + "\n".join(f"- {m}" for m in merchants)
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.post(
            _URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        data = r.json()

    return json.loads(data["choices"][0]["message"]["content"])
