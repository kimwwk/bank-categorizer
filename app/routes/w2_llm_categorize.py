from fastapi import APIRouter

from app.clients import firefly, openai_llm
from app.config import settings

router = APIRouter(prefix="/w2", tags=["W2 LLM Categorize"])


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
    """Extract the merchant name from a rule's description_contains trigger."""
    for t in rule.get("attributes", {}).get("triggers", []):
        if t.get("type") == "description_contains":
            return t.get("value")
    return None


def _extract_category_from_rule(rule: dict) -> str | None:
    for a in rule.get("attributes", {}).get("actions", []):
        if a.get("type") == "set_category":
            return a.get("value")
    return None


@router.post("/llm-categorize")
async def llm_categorize():
    # 1. Fetch valid categories
    categories = await firefly.get_all_categories()

    # 2. Fetch uncategorized transactions (exclude transfers)
    withdrawals = await firefly.search_transactions("has_no_category:true type:withdrawal")
    deposits = await firefly.search_transactions("has_no_category:true type:deposit")
    uncategorized = withdrawals + deposits
    if not uncategorized:
        return {"status": "ok", "summary": "No uncategorized transactions found"}

    # 3. Deduplicate by merchant description
    merchants = set()
    for tx in uncategorized:
        for t in tx.get("attributes", {}).get("transactions", []):
            desc = t.get("description", "").strip()
            if desc:
                merchants.add(desc)

    merchants = sorted(merchants)
    if not merchants:
        return {"status": "ok", "summary": "No merchants to categorize"}

    # 4. Ask LLM
    llm_mappings = await openai_llm.categorize(merchants, categories)

    # 5. Validate — reject hallucinated categories
    category_set = set(categories)
    valid_mappings = {}
    rejections = []
    for merchant, category in llm_mappings.items():
        if category in category_set:
            valid_mappings[merchant] = category
        else:
            rejections.append({"merchant": merchant, "hallucinated": category})

    # 6. Fetch existing rules → build lookup
    all_rules = await firefly.get_all_rules()
    rule_lookup: dict[str, dict] = {}
    for rule in all_rules:
        m = _extract_merchant_from_rule(rule)
        if m:
            rule_lookup[m] = {
                "id": rule["id"],
                "category": _extract_category_from_rule(rule),
            }

    # 7. Create/update rules
    created = 0
    updated = 0
    skipped = 0
    errors = []

    for merchant, category in valid_mappings.items():
        try:
            existing = rule_lookup.get(merchant)
            if existing:
                if existing["category"] == category:
                    skipped += 1
                    continue
                # Update existing rule
                await firefly.put(f"/rules/{existing['id']}", _build_rule(merchant, category))
                updated += 1
            else:
                await firefly.post("/rules", _build_rule(merchant, category))
                created += 1
        except Exception as e:
            errors.append(f"{merchant}: {e}")

    # 8. Trigger rule group
    trigger_status = "ok"
    try:
        await firefly.trigger_rule_group(settings.rule_group_id)
    except Exception as e:
        trigger_status = f"error: {e}"

    summary = (
        f"LLM Categorize: {len(uncategorized)} txs found, "
        f"{created} rules created, {updated} updated, {skipped} skipped, "
        f"{len(rejections)} rejected, trigger: {trigger_status}"
    )

    return {
        "status": "partial" if errors else "ok",
        "summary": summary,
        "rulesCreated": created,
        "rulesUpdated": updated,
        "rulesSkipped": skipped,
        "triggerStatus": trigger_status,
        "rejected": len(rejections),
        "rejections": rejections,
        "errors": errors[:20],
        "merchantMappings": valid_mappings,
    }
