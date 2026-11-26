import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any
from app.database import get_db

def format_decimal(val: Any, places: int = 4) -> str:
    if val is None:
        return "0.0000"
    d = Decimal(str(val))
    pattern = "0." + "0" * places
    return str(d.quantize(Decimal(pattern), rounding=ROUND_HALF_UP))

class LedgerEngine:
    @staticmethod
    def get_item_balance(conn, item_id: str) -> Decimal:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(qty_delta), 0) as balance FROM stock_ledger WHERE item_id = ?",
            (item_id,)
        )
        row = cursor.fetchone()
        return Decimal(str(row["balance"] or 0)).quantize(Decimal("0.0001"))

    @staticmethod
    def get_all_balances(conn) -> Dict[str, Decimal]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT i.id, i.sku, i.name, i.kind, i.base_unit,
                   COALESCE(SUM(l.qty_delta), 0) as balance
            FROM items i
            LEFT JOIN stock_ledger l ON i.id = l.item_id
            GROUP BY i.id
            """
        )
        return {row["id"]: Decimal(str(row["balance"] or 0)).quantize(Decimal("0.0001")) for row in cursor.fetchall()}

    @staticmethod
    def get_reserved_quantity(conn, product_id: str) -> Decimal:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(SUM(reserved_qty), 0) as reserved
            FROM stock_reservations
            WHERE product_id = ? AND status = 'ACTIVE'
            """,
            (product_id,)
        )
        row = cursor.fetchone()
        return Decimal(str(row["reserved"] or 0)).quantize(Decimal("0.0001"))

    @staticmethod
    def get_fg_available(conn, product_id: str) -> Dict[str, Decimal]:
        cursor = conn.cursor()
        cursor.execute("SELECT item_id FROM products WHERE id = ?", (product_id,))
        p = cursor.fetchone()
        if not p:
            return {"on_hand": Decimal("0"), "reserved": Decimal("0"), "available": Decimal("0")}
        
        item_id = p["item_id"]
        on_hand = LedgerEngine.get_item_balance(conn, item_id)
        reserved = LedgerEngine.get_reserved_quantity(conn, product_id)
        available = max(Decimal("0"), on_hand - reserved)
        return {
            "item_id": item_id,
            "on_hand": on_hand,
            "reserved": reserved,
            "available": available
        }

    @staticmethod
    def post_movement(
        conn,
        item_id: str,
        qty_delta: Decimal,
        movement_type: str,
        source_type: str,
        source_id: str,
        unit_cost: Optional[Decimal] = None,
        batch_no: Optional[str] = None,
        user_id: Optional[str] = "SYSTEM",
        note: Optional[str] = None,
        allow_negative: bool = False
    ) -> int:
        """
        The ONLY entry point to change stock.
        Guarantees ledger immutability and balance sanity.
        """
        current_balance = LedgerEngine.get_item_balance(conn, item_id)
        new_balance = current_balance + qty_delta

        if not allow_negative and new_balance < Decimal("0"):
            raise ValueError(
                f"Insufficient stock for item {item_id}: current {current_balance}, attempted delta {qty_delta}, resulting in {new_balance}"
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO stock_ledger (
                posted_at, item_id, batch_no, qty_delta, unit_cost,
                movement_type, source_type, source_id, user_id, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso,
                item_id,
                batch_no,
                float(qty_delta),
                float(unit_cost) if unit_cost is not None else None,
                movement_type,
                source_type,
                source_id,
                user_id,
                note
            )
        )
        ledger_id = cursor.lastrowid

        # Record tamper-evident audit entry
        AuditEngine.log_action(
            conn,
            user_id=user_id or "SYSTEM",
            action=f"STOCK_{movement_type}",
            entity_name="stock_ledger",
            entity_id=str(ledger_id),
            payload={
                "item_id": item_id,
                "qty_delta": str(qty_delta),
                "new_balance": str(new_balance),
                "movement_type": movement_type,
                "source_type": source_type,
                "source_id": source_id,
                "unit_cost": str(unit_cost) if unit_cost is not None else None
            }
        )

        return ledger_id

    @staticmethod
    def reverse_movement(conn, original_ledger_id: int, user_id: str, note: str) -> int:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stock_ledger WHERE id = ?", (original_ledger_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Ledger entry {original_ledger_id} not found")

        reversal_qty = Decimal(str(-row["qty_delta"]))
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO stock_ledger (
                posted_at, item_id, batch_no, qty_delta, unit_cost,
                movement_type, source_type, source_id, reverses_id, user_id, note
            ) VALUES (?, ?, ?, ?, ?, 'REVERSAL', ?, ?, ?, ?, ?)
            """,
            (
                now_iso,
                row["item_id"],
                row["batch_no"],
                float(reversal_qty),
                row["unit_cost"],
                row["source_type"],
                row["source_id"],
                original_ledger_id,
                user_id,
                note
            )
        )
        reversal_id = cursor.lastrowid
        return reversal_id


class AuditEngine:
    @staticmethod
    def get_latest_hash(conn) -> str:
        cursor = conn.cursor()
        cursor.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return row["hash"] if row else "GENESIS_BLOCK_00000000000000000000000000000000"

    @staticmethod
    def log_action(conn, user_id: str, action: str, entity_name: str, entity_id: str, payload: dict) -> int:
        prev_hash = AuditEngine.get_latest_hash(conn)
        now_iso = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, sort_keys=True)
        
        hash_content = f"{prev_hash}|{now_iso}|{user_id}|{action}|{entity_name}|{entity_id}|{payload_json}"
        curr_hash = hashlib.sha256(hash_content.encode("utf-8")).hexdigest()

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO audit_log (
                created_at, user_id, action, entity_name, entity_id,
                payload_json, prev_hash, hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_iso, user_id, action, entity_name, entity_id, payload_json, prev_hash, curr_hash)
        )
        return cursor.lastrowid

    @staticmethod
    def verify_integrity(conn) -> Dict[str, Any]:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_log ORDER BY id ASC")
        rows = cursor.fetchall()

        expected_prev = "GENESIS_BLOCK_00000000000000000000000000000000"
        for idx, row in enumerate(rows):
            if row["prev_hash"] != expected_prev:
                return {
                    "is_valid": False,
                    "tampered_at_id": row["id"],
                    "error": f"Chain broken at record {row['id']}: expected prev_hash {expected_prev}, got {row['prev_hash']}"
                }
            
            hash_content = f"{row['prev_hash']}|{row['created_at']}|{row['user_id']}|{row['action']}|{row['entity_name']}|{row['entity_id']}|{row['payload_json']}"
            computed_hash = hashlib.sha256(hash_content.encode("utf-8")).hexdigest()

            if computed_hash != row["hash"]:
                return {
                    "is_valid": False,
                    "tampered_at_id": row["id"],
                    "error": f"Hash mismatch at record {row['id']}: stored {row['hash']}, computed {computed_hash}"
                }

            expected_prev = row["hash"]

        return {
            "is_valid": True,
            "total_records": len(rows),
            "latest_hash": expected_prev
        }
