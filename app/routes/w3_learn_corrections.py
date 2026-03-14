from fastapi import APIRouter, Request

from app.clients import firefly
from app.config import settings

router = APIRouter(prefix="/w3", tags=["W3 Learn Corrections"])


def _build_rule(merchant: str, category: str) -> dict:
    return {
        "title": f"Auto: {merchant}",
        "rule_group_id": settings.rule_group_id,
        "trigger": "store-journal",
        "active": True,
        "strict": True,
        "triggers": [
            {"type": "description_contains", "value": merchant, "active": True},
            {"type": "has_no_category", "value": "true", "active": True},
        ],
        "actions": [
            {"type": "set_category", "value": category, "active": True},
        ],
    }


def _extract_merchant_from_rule(rule: dict) -> str | None:
    for t in rule.get("attributes", {}).get("triggers", []):
        if t.get("type") == "description_contains":
            return t.get("value")
    return None


def _extract_category_from_rule(rule: dict) -> str | None:
    for a in rule.get("attributes", {}).get("actions", []):
        if a.get("type") == "set_category":
            return a.get("value")
    return None


@router.post("/learn-corrections")
async def learn_corrections(request: Request):
    body = await request.json()

    # Parse webhook payload from Firefly III
    content = body.get("content", body)
    tx_id = content.get("id")
    transactions = content.get("transactions", [])

    # If transactions not in payload, fetch from Firefly
    if not transactions and tx_id:
        try:
            resp = await firefly.get(f"/transactions/{tx_id}")
            tx_data = resp.get("data", {})
            transactions = tx_data.get("attributes", {}).get("transactions", [])
        except Exception:
            pass

    if not transactions:
        return {"status": "skipped", "message": "No transaction data found"}

    merchant = transactions[0].get("description", "").strip()
    category = transactions[0].get("category_name", "").strip()

    if not merchant or not category:
        return {"status": "skipped", "message": f"Missing merchant or category (merchant={merchant!r}, category={category!r})"}

    # Find existing rule for this merchant
    all_rules = await firefly.get_all_rules()
    existing_rule = None
    for rule in all_rules:
        m = _extract_merchant_from_rule(rule)
        if m and m == merchant:
            existing_rule = rule
            break

    # Upsert rule
    action = "none"
    rule_id = None

    if existing_rule:
        current_cat = _extract_category_from_rule(existing_rule)
        if current_cat == category:
            return {
                "status": "ok",
                "action": "none",
                "triggerStatus": "skipped",
                "message": f"Rule already correct: {merchant} → {category}",
                "merchant": merchant,
                "category": category,
            }
        # Update
        rule_id = existing_rule["id"]
        await firefly.put(f"/rules/{rule_id}", _build_rule(merchant, category))
        action = "updated"
    else:
        resp = await firefly.post("/rules", _build_rule(merchant, category))
        rule_id = resp.get("data", {}).get("id")
        action = "created"

    # Trigger the rule
    trigger_status = "ok"
    if rule_id:
        try:
            await firefly.trigger_rule(int(rule_id), 1)
        except Exception as e:
            trigger_status = f"error: {e}"

    return {
        "status": "ok",
        "action": action,
        "triggerStatus": trigger_status,
        "message": f"Rule {action}: {merchant} → {category}",
        "merchant": merchant,
        "category": category,
    }
