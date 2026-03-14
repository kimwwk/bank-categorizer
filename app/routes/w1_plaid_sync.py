from collections import defaultdict

import httpx
from fastapi import APIRouter

from app.clients import firefly, plaid
from app.config import settings
from app.state import load_state, save_state

router = APIRouter(prefix="/w1", tags=["W1 Plaid Sync"])


def _resolve_firefly_account(plaid_account_id: str) -> str | None:
    """Map a Plaid account_id to a Firefly account ID.

    Returns None if the account isn't in the map (skip it).
    Falls back to "1" if no mapping is configured at all.
    """
    mapping = settings.account_mapping
    if mapping:
        return mapping.get(plaid_account_id)
    return "1"


def _detect_transfers(transactions: list[dict]) -> tuple[dict[str, str], set[str]]:
    """Find pairs of transactions that are inter-account transfers.

    Matches by: same date, same abs(amount), opposite signs, different mapped accounts.

    Returns:
        pairs: {withdrawal_tx_id: deposit_tx_id}
        paired_ids: set of all tx_ids involved in transfers
    """
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for tx in transactions:
        ff_acct = _resolve_firefly_account(tx.get("account_id", ""))
        if ff_acct is None:
            continue
        key = (tx.get("date"), round(abs(tx.get("amount", 0)), 2))
        by_key[key].append(tx)

    pairs = {}
    paired_ids: set[str] = set()

    for group in by_key.values():
        if len(group) < 2:
            continue
        outgoing = [t for t in group if t.get("amount", 0) > 0]
        incoming = [t for t in group if t.get("amount", 0) < 0]

        for out_tx in outgoing:
            if out_tx["transaction_id"] in paired_ids:
                continue
            out_acct = _resolve_firefly_account(out_tx.get("account_id", ""))
            for in_tx in incoming:
                if in_tx["transaction_id"] in paired_ids:
                    continue
                in_acct = _resolve_firefly_account(in_tx.get("account_id", ""))
                if out_acct != in_acct:
                    pairs[out_tx["transaction_id"]] = in_tx["transaction_id"]
                    paired_ids.add(out_tx["transaction_id"])
                    paired_ids.add(in_tx["transaction_id"])
                    break

    return pairs, paired_ids


def _map_transaction(tx: dict) -> dict | None:
    """Map a Plaid transaction to Firefly III format.

    Returns None if the account isn't mapped (skip it).
    """
    account_id = _resolve_firefly_account(tx.get("account_id", ""))
    if account_id is None:
        return None

    amount = tx.get("amount", 0)
    is_withdrawal = amount > 0

    return {
        "type": "withdrawal" if is_withdrawal else "deposit",
        "date": tx.get("date"),
        "description": tx.get("merchant_name") or tx.get("name", "Unknown"),
        "amount": str(abs(amount)),
        "currency_code": tx.get("iso_currency_code", "CAD"),
        "external_id": tx.get("transaction_id"),
        **({"source_id": account_id} if is_withdrawal
           else {"destination_id": account_id}),
    }


def _map_transfer(out_tx: dict, in_tx: dict) -> dict:
    """Map a transfer pair to a Firefly III transfer transaction."""
    source_id = _resolve_firefly_account(out_tx.get("account_id", ""))
    dest_id = _resolve_firefly_account(in_tx.get("account_id", ""))

    return {
        "type": "transfer",
        "date": out_tx.get("date"),
        "description": out_tx.get("merchant_name") or out_tx.get("name", "Transfer"),
        "amount": str(abs(out_tx.get("amount", 0))),
        "currency_code": out_tx.get("iso_currency_code", "CAD"),
        "external_id": out_tx.get("transaction_id"),
        "source_id": source_id,
        "destination_id": dest_id,
    }


@router.post("/plaid-sync")
async def plaid_sync():
    state = load_state()
    cursor = state.get("plaid_cursor")

    # Fetch new transactions from Plaid
    sync_result = await plaid.transactions_sync(cursor)
    new_cursor = sync_result["cursor"]

    stats = {"added": 0, "modified": 0, "removed": 0, "transfers": 0, "errors": []}

    # Detect inter-account transfers before processing
    added = sync_result["added"]
    transfer_pairs, paired_ids = _detect_transfers(added)
    tx_by_id = {tx["transaction_id"]: tx for tx in added}

    # Process added transactions
    for tx in added:
        try:
            tx_id = tx.get("transaction_id")

            # Skip the deposit side of a transfer (handled by withdrawal side)
            if tx_id in paired_ids and tx_id not in transfer_pairs:
                continue

            # Check for duplicates
            existing = await firefly.search_transactions(f"external_id_is:{tx_id}")
            if existing:
                continue

            # Transfer: create a single Firefly transfer
            if tx_id in transfer_pairs:
                deposit_tx = tx_by_id[transfer_pairs[tx_id]]
                mapped = _map_transfer(tx, deposit_tx)
                await firefly.post("/transactions", {
                    "apply_rules": True,
                    "fire_webhooks": False,
                    "error_if_duplicate_hash": True,
                    "transactions": [mapped],
                })
                stats["transfers"] += 1
                continue

            # Normal transaction
            mapped = _map_transaction(tx)
            if mapped is None:
                continue
            await firefly.post("/transactions", {
                "apply_rules": True,
                "fire_webhooks": False,
                "error_if_duplicate_hash": True,
                "transactions": [mapped],
            })
            stats["added"] += 1
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
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
            if mapped is None:
                continue
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

    summary = (
        f"Plaid Sync complete: {stats['added']} added, "
        f"{stats['transfers']} transfers, "
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
