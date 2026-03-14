import httpx
from fastapi import APIRouter

from app.clients import firefly, plaid
from app.state import load_state, save_state

router = APIRouter(prefix="/w1", tags=["W1 Plaid Sync"])

# Hardcoded Firefly account ID for the bank account (matches n8n workflow)
BANK_ACCOUNT_ID = "1"


def _map_transaction(tx: dict) -> dict:
    """Map a Plaid transaction to Firefly III format."""
    amount = tx.get("amount", 0)
    # Plaid: positive = money leaving account (withdrawal), negative = deposit
    is_withdrawal = amount > 0

    return {
        "type": "withdrawal" if is_withdrawal else "deposit",
        "date": tx.get("date"),
        "description": tx.get("merchant_name") or tx.get("name", "Unknown"),
        "amount": str(abs(amount)),
        "currency_code": tx.get("iso_currency_code", "CAD"),
        "external_id": tx.get("transaction_id"),
        **({"source_id": BANK_ACCOUNT_ID, "destination_name": "Cash"} if is_withdrawal
           else {"source_name": "Cash", "destination_id": BANK_ACCOUNT_ID}),
    }


@router.post("/plaid-sync")
async def plaid_sync():
    state = load_state()
    cursor = state.get("plaid_cursor")

    # Fetch all new transactions from Plaid
    sync_result = await plaid.transactions_sync(cursor)
    new_cursor = sync_result["cursor"]

    stats = {"added": 0, "modified": 0, "removed": 0, "errors": []}

    # Process added transactions
    for tx in sync_result["added"]:
        try:
            ext_id = tx.get("transaction_id")
            # Check for duplicates
            existing = await firefly.search_transactions(f"external_id_is:{ext_id}")
            if existing:
                continue

            mapped = _map_transaction(tx)
            await firefly.post("/transactions", {
                "apply_rules": True,
                "fire_webhooks": False,
                "error_if_duplicate_hash": True,
                "transactions": [mapped],
            })
            stats["added"] += 1
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                # Duplicate hash — skip
                pass
            else:
                stats["errors"].append(f"add {tx.get('transaction_id')}: {e}")
        except Exception as e:
            stats["errors"].append(f"add {tx.get('transaction_id')}: {e}")

    # Process modified transactions
    for tx in sync_result["modified"]:
        try:
            ext_id = tx.get("transaction_id")
            existing = await firefly.search_transactions(f"external_id_is:{ext_id}")
            if not existing:
                continue

            ff_id = existing[0]["id"]
            mapped = _map_transaction(tx)
            await firefly.put(f"/transactions/{ff_id}", {
                "apply_rules": False,
                "transactions": [mapped],
            })
            stats["modified"] += 1
        except Exception as e:
            stats["errors"].append(f"modify {tx.get('transaction_id')}: {e}")

    # Process removed transactions
    for tx in sync_result["removed"]:
        try:
            ext_id = tx.get("transaction_id")
            existing = await firefly.search_transactions(f"external_id_is:{ext_id}")
            if not existing:
                continue

            ff_id = existing[0]["id"]
            await firefly.delete(f"/transactions/{ff_id}")
            stats["removed"] += 1
        except Exception as e:
            stats["errors"].append(f"remove {tx.get('transaction_id')}: {e}")

    # Only persist cursor if no errors (protect against data loss)
    cursor_updated = False
    if not stats["errors"]:
        state["plaid_cursor"] = new_cursor
        save_state(state)
        cursor_updated = True

    total = stats["added"] + stats["modified"] + stats["removed"]
    summary = (
        f"Plaid Sync complete: {stats['added']} added, "
        f"{stats['modified']} modified, {stats['removed']} removed, "
        f"{len(stats['errors'])} errors"
    )

    return {
        "status": "partial" if stats["errors"] else "ok",
        "summary": summary,
        "cursor": new_cursor if cursor_updated else (cursor or ""),
        "cursorUpdated": cursor_updated,
        "stats": {
            **stats,
            "errors": [str(e) for e in stats["errors"][:20]],
        },
    }
