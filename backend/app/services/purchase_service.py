import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List
from app.ledger import LedgerEngine, AuditEngine

class PurchaseService:
    @staticmethod
    def create_purchase(
        conn,
        supplier_id: str,
        bill_no: str,
        bill_date: str,
        items: List[Dict[str, Any]], # [{"item_id", "qty", "unit", "unit_rate", "gst_rate", "batch_no", "expiry_date"}]
        user_id: str = "ADMIN"
    ) -> Dict[str, Any]:
        cursor = conn.cursor()
        purchase_id = f"PUR-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Generate sequence purchase number
        cursor.execute("SELECT COUNT(*) as count FROM purchases")
        count = cursor.fetchone()["count"] + 1
        purchase_number = f"PO/{datetime.now().year}/{count:04d}"

        total_taxable = Decimal("0")
        total_tax = Decimal("0")
        total_amount = Decimal("0")

        cursor.execute(
            """
            INSERT INTO purchases (
                id, purchase_number, supplier_id, bill_no, bill_date,
                total_taxable, total_tax, total_amount, created_at
            ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?)
            """,
            (purchase_id, purchase_number, supplier_id, bill_no, bill_date, now_iso)
        )

        for line in items:
            item_id = line["item_id"]
            qty = Decimal(str(line["qty"]))
            unit_rate = Decimal(str(line["unit_rate"]))
            gst_rate = Decimal(str(line.get("gst_rate", 5.0)))
            batch_no = line.get("batch_no")
            expiry_date = line.get("expiry_date")

            taxable = qty * unit_rate
            tax = taxable * (gst_rate / Decimal("100"))
            line_total = taxable + tax

            total_taxable += taxable
            total_tax += tax
            total_amount += line_total

            cursor.execute(
                """
                INSERT INTO purchase_lines (
                    purchase_id, item_id, qty, unit, unit_rate,
                    taxable_amount, gst_rate, tax_amount, total_amount,
                    batch_no, expiry_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase_id, item_id, float(qty), line.get("unit", "kg"),
                    float(unit_rate), float(taxable), float(gst_rate),
                    float(tax), float(line_total), batch_no, expiry_date
                )
            )

            # Append to stock ledger (+receipt)
            LedgerEngine.post_movement(
                conn,
                item_id=item_id,
                qty_delta=qty,
                movement_type="PURCHASE",
                source_type="PURCHASE",
                source_id=purchase_id,
                unit_cost=unit_rate,
                batch_no=batch_no,
                user_id=user_id,
                note=f"Purchase from supplier {supplier_id}, Bill {bill_no}"
            )

        cursor.execute(
            """
            UPDATE purchases
            SET total_taxable = ?, total_tax = ?, total_amount = ?
            WHERE id = ?
            """,
            (float(total_taxable), float(total_tax), float(total_amount), purchase_id)
        )

        AuditEngine.log_action(
            conn,
            user_id=user_id,
            action="PURCHASE_CREATED",
            entity_name="purchases",
            entity_id=purchase_id,
            payload={
                "purchase_number": purchase_number,
                "supplier_id": supplier_id,
                "total_amount": str(total_amount),
                "items_count": len(items)
            }
        )

        return {
            "purchase_id": purchase_id,
            "purchase_number": purchase_number,
            "total_taxable": total_taxable,
            "total_tax": total_tax,
            "total_amount": total_amount
        }
