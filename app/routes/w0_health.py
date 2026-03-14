from datetime import datetime, timezone

from fastapi import APIRouter

from app.clients import firefly, plaid

router = APIRouter(prefix="/w0", tags=["W0 Health"])


@router.post("/health")
async def health_check():
    checks = []
    any_failed = False

    # 1. Transaction staleness
    try:
        resp = await firefly.get("/transactions", {"limit": 1, "type": "all"})
        data = resp.get("data", [])
        if data:
            date_str = data[0]["attributes"]["transactions"][0]["date"]
            tx_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - tx_date).days
            if age_days > 3:
                checks.append({"name": "Transaction Staleness", "status": "FAIL", "detail": f"Newest transaction is {age_days} days old"})
                any_failed = True
            else:
                checks.append({"name": "Transaction Staleness", "status": "PASS", "detail": f"Newest transaction is {age_days} day(s) old"})
        else:
            checks.append({"name": "Transaction Staleness", "status": "FAIL", "detail": "No transactions found"})
            any_failed = True
    except Exception as e:
        checks.append({"name": "Transaction Staleness", "status": "ERROR", "detail": str(e)})
        any_failed = True

    # 2. Uncategorized count
    try:
        # Only count withdrawals + deposits, not transfers (transfers intentionally have no category)
        withdrawals = await firefly.search_transactions("has_no_category:true type:withdrawal")
        deposits = await firefly.search_transactions("has_no_category:true type:deposit")
        count = len(withdrawals) + len(deposits)
        if count > 10:
            checks.append({"name": "Uncategorized Transactions", "status": "FAIL", "detail": f"{count} uncategorized transactions"})
            any_failed = True
        elif count > 0:
            checks.append({"name": "Uncategorized Transactions", "status": "WARN", "detail": f"{count} uncategorized transactions"})
        else:
            checks.append({"name": "Uncategorized Transactions", "status": "PASS", "detail": "All transactions categorized"})
    except Exception as e:
        checks.append({"name": "Uncategorized Transactions", "status": "ERROR", "detail": str(e)})
        any_failed = True

    # 3. Plaid connection
    try:
        item_resp = await plaid.item_get()
        item = item_resp.get("item", {})
        error = item.get("error")
        if error:
            checks.append({"name": "Plaid Connection", "status": "FAIL", "detail": f"Item error: {error.get('error_code', 'unknown')}"})
            any_failed = True
        else:
            checks.append({"name": "Plaid Connection", "status": "PASS", "detail": "Plaid item connected"})
    except Exception as e:
        checks.append({"name": "Plaid Connection", "status": "ERROR", "detail": str(e)})
        any_failed = True

    timestamp = datetime.now(timezone.utc).isoformat()
    summary = "; ".join(f"{c['name']}: {c['status']}" for c in checks)

    return {
        "timestamp": timestamp,
        "status": "ALERT — Issues detected" if any_failed else "All clear",
        "anyFailed": any_failed,
        "checks": checks,
        "summary": summary,
    }


@router.post("/plaid-reauth")
async def plaid_reauth():
    """Generate a hosted Plaid Link URL to re-authenticate the bank connection."""
    try:
        link_resp = await plaid.create_update_link_token()
        return {
            "status": "ok",
            "url": link_resp.get("hosted_link_url"),
            "expiration": link_resp.get("expiration"),
            "message": "Open the URL in a browser to re-authenticate your bank connection.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
