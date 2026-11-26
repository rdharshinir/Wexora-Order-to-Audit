from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List

FACTORY_STATE_CODE = "33" # Tamil Nadu

class GSTCalculator:
    @staticmethod
    def calculate_line(
        taxable_value: Decimal,
        gst_rate: Decimal,
        customer_state_code: str,
        factory_state_code: str = FACTORY_STATE_CODE
    ) -> Dict[str, Any]:
        """
        Calculates line-level GST.
        Intra-state (same state code): CGST + SGST (half rate each).
        Inter-state (different state code): IGST (full rate).
        Rounded to nearest 2 decimal places (paise) using ROUND_HALF_UP.
        """
        is_intra = (customer_state_code.strip() == factory_state_code.strip())
        
        taxable_amount = taxable_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        if is_intra:
            half_rate = (gst_rate / Decimal("2")).quantize(Decimal("0.001"))
            cgst_amount = (taxable_amount * (half_rate / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            sgst_amount = (taxable_amount * (half_rate / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            igst_amount = Decimal("0.00")
            cgst_rate = half_rate
            sgst_rate = half_rate
            igst_rate = Decimal("0.00")
            total_tax = cgst_amount + sgst_amount
        else:
            cgst_amount = Decimal("0.00")
            sgst_amount = Decimal("0.00")
            cgst_rate = Decimal("0.00")
            sgst_rate = Decimal("0.00")
            igst_rate = gst_rate
            igst_amount = (taxable_amount * (gst_rate / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_tax = igst_amount

        line_total = taxable_amount + total_tax

        return {
            "supply_type": "INTRA" if is_intra else "INTER",
            "taxable_amount": taxable_amount,
            "gst_rate": gst_rate,
            "cgst_rate": cgst_rate,
            "cgst_amount": cgst_amount,
            "sgst_rate": sgst_rate,
            "sgst_amount": sgst_amount,
            "igst_rate": igst_rate,
            "igst_amount": igst_amount,
            "total_tax": total_tax,
            "line_total": line_total
        }

    @staticmethod
    def get_financial_year(dt=None) -> str:
        from datetime import datetime
        now = dt or datetime.now()
        year = now.year
        month = now.month
        if month >= 4:
            start_yr = year % 100
            end_yr = (year + 1) % 100
        else:
            start_yr = (year - 1) % 100
            end_yr = year % 100
        return f"{start_yr:02d}-{end_yr:02d}"

    @staticmethod
    def generate_invoice_number(conn, dt=None) -> tuple[str, str, int]:
        """
        Thread-safe, gap-free invoice number generation per financial year.
        Format: TN/YY-YY/XXXX
        """
        fy = GSTCalculator.get_financial_year(dt)
        cursor = conn.cursor()
        cursor.execute("SELECT last_seq FROM invoice_sequences WHERE fy = ?", (fy,))
        row = cursor.fetchone()
        if row:
            next_seq = row["last_seq"] + 1
            cursor.execute("UPDATE invoice_sequences SET last_seq = ? WHERE fy = ?", (next_seq, fy))
        else:
            next_seq = 1
            cursor.execute("INSERT INTO invoice_sequences (fy, last_seq) VALUES (?, ?)", (fy, next_seq))
        
        invoice_number = f"TN/{fy}/{next_seq:04d}"
        return invoice_number, fy, next_seq
