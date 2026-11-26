import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional
from app.ledger import AuditEngine

class PaymentService:
    @staticmethod
    def record_payment(
        conn,
        customer_id: str,
        amount: Decimal,
        payment_mode: str = "NEFT",
        reference_no: str = "",
        invoice_id: Optional[str] = None,
        notes: str = "",
        user_id: str = "ADMIN"
    ) -> Dict[str, Any]:
        cursor = conn.cursor()
        payment_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("SELECT COUNT(*) as cnt FROM payments")
        cnt = cursor.fetchone()["cnt"] + 1
        payment_number = f"RCPT/{datetime.now().year}/{cnt:04d}"

        cursor.execute(
            """
            INSERT INTO payments (
                id, payment_number, customer_id, amount, payment_mode,
                reference_no, received_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (payment_id, payment_number, customer_id, float(amount), payment_mode, reference_no, now_iso, notes)
        )

        # Allocate payment to invoice(s)
        unallocated = amount
        if invoice_id:
            invoices_to_allocate = [invoice_id]
        else:
            # FIFO: Find open invoices for customer
            cursor.execute(
                """
                SELECT id, total_amount FROM invoices
                WHERE customer_id = ? AND status IN ('POSTED', 'PARTIALLY_PAID')
                ORDER BY created_at ASC
                """,
                (customer_id,)
            )
            invoices_to_allocate = [r["id"] for r in cursor.fetchall()]

        allocations = []
        for inv_id in invoices_to_allocate:
            if unallocated <= Decimal("0"):
                break
            
            # Find already allocated amount for this invoice
            cursor.execute(
                "SELECT COALESCE(SUM(allocated_amount), 0) as paid FROM payment_allocations WHERE invoice_id = ?",
                (inv_id,)
            )
            already_paid = Decimal(str(cursor.fetchone()["paid"]))
            
            cursor.execute("SELECT total_amount FROM invoices WHERE id = ?", (inv_id,))
            inv_total = Decimal(str(cursor.fetchone()["total_amount"]))
            inv_due = inv_total - already_paid

            if inv_due <= Decimal("0"):
                continue

            allocate_amt = min(unallocated, inv_due)
            cursor.execute(
                """
                INSERT INTO payment_allocations (payment_id, invoice_id, allocated_amount, allocated_at)
                VALUES (?, ?, ?, ?)
                """,
                (payment_id, inv_id, float(allocate_amt), now_iso)
            )

            new_paid = already_paid + allocate_amt
            new_status = "PAID" if new_paid >= inv_total else "PARTIALLY_PAID"
            cursor.execute("UPDATE invoices SET status = ? WHERE id = ?", (new_status, inv_id))

            unallocated -= allocate_amt
            allocations.append({"invoice_id": inv_id, "amount": allocate_amt, "status": new_status})

        AuditEngine.log_action(
            conn,
            user_id=user_id,
            action="PAYMENT_RECEIVED",
            entity_name="payments",
            entity_id=payment_id,
            payload={
                "payment_number": payment_number,
                "customer_id": customer_id,
                "amount": str(amount),
                "allocations": [{"invoice_id": a["invoice_id"], "amount": str(a["amount"])} for a in allocations]
            }
        )

        return {
            "payment_id": payment_id,
            "payment_number": payment_number,
            "allocated_amount": amount - unallocated,
            "unallocated_amount": unallocated,
            "allocations": allocations
        }

    @staticmethod
    def get_customer_outstanding(conn, customer_id: str) -> Dict[str, Any]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT i.id, i.invoice_number, i.total_amount, i.created_at,
                   COALESCE(SUM(pa.allocated_amount), 0) as paid_amount
            FROM invoices i
            LEFT JOIN payment_allocations pa ON i.id = pa.invoice_id
            WHERE i.customer_id = ? AND i.status != 'CANCELLED'
            GROUP BY i.id
            ORDER BY i.created_at ASC
            """,
            (customer_id,)
        )
        rows = cursor.fetchall()

        total_invoiced = Decimal("0")
        total_paid = Decimal("0")
        invoices_detail = []

        now = datetime.now(timezone.utc)
        buckets = {"0_30": Decimal("0"), "31_60": Decimal("0"), "61_90": Decimal("0"), "90_plus": Decimal("0")}

        for r in rows:
            inv_total = Decimal(str(r["total_amount"]))
            paid = Decimal(str(r["paid_amount"]))
            due = inv_total - paid
            total_invoiced += inv_total
            total_paid += paid

            # Ageing calculation
            created_dt = datetime.fromisoformat(r["created_at"])
            days = (now - created_dt).days

            if due > Decimal("0"):
                if days <= 30:
                    buckets["0_30"] += due
                elif days <= 60:
                    buckets["31_60"] += due
                elif days <= 90:
                    buckets["61_90"] += due
                else:
                    buckets["90_plus"] += due

            invoices_detail.append({
                "invoice_id": r["id"],
                "invoice_number": r["invoice_number"],
                "total_amount": inv_total,
                "paid_amount": paid,
                "due_amount": due,
                "days_outstanding": days
            })

        outstanding = total_invoiced - total_paid

        return {
            "customer_id": customer_id,
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "outstanding": outstanding,
            "ageing_buckets": buckets,
            "invoices": invoices_detail
        }
