from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List

class CostingService:
    @staticmethod
    def calculate_wac_rate(conn, item_id: str) -> Decimal:
        """
        Computes Weighted Average Cost (WAC) based on receipts in the ledger:
        Opening + Purchases.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT qty_delta, unit_cost
            FROM stock_ledger
            WHERE item_id = ? AND qty_delta > 0 AND unit_cost IS NOT NULL
            ORDER BY id ASC
            """,
            (item_id,)
        )
        rows = cursor.fetchall()
        if not rows:
            # Fallback to last recorded cost or zero
            cursor.execute("SELECT unit_cost FROM stock_ledger WHERE item_id = ? AND unit_cost IS NOT NULL ORDER BY id DESC LIMIT 1", (item_id,))
            last = cursor.fetchone()
            return Decimal(str(last["unit_cost"] or 0)).quantize(Decimal("0.0001"))

        total_qty = Decimal("0")
        total_value = Decimal("0")
        for r in rows:
            q = Decimal(str(r["qty_delta"]))
            c = Decimal(str(r["unit_cost"]))
            total_qty += q
            total_value += (q * c)

        if total_qty == Decimal("0"):
            return Decimal("0.0000")

        return (total_value / total_qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @staticmethod
    def calculate_run_cost(
        rm_items: List[Dict[str, Any]], # [{"item_id", "qty", "rate", "kind"}]
        pm_items: List[Dict[str, Any]],
        overheads: List[Dict[str, Any]], # [{"kind", "amount"}]
        good_packets: Decimal,
        selling_price: Decimal
    ) -> Dict[str, Any]:
        """
        Calculates total run cost, cost per packet, and gross margin.
        Overheads are spread across good packets.
        Damaged pouches and scrap are included in PM/RM cost.
        """
        total_rm_cost = Decimal("0")
        for item in rm_items:
            q = Decimal(str(item["qty"]))
            r = Decimal(str(item["rate"]))
            total_rm_cost += (q * r)

        total_pm_cost = Decimal("0")
        for item in pm_items:
            q = Decimal(str(item["qty"]))
            r = Decimal(str(item["rate"]))
            total_pm_cost += (q * r)

        total_overhead = Decimal("0")
        for oh in overheads:
            total_overhead += Decimal(str(oh["amount"]))

        total_run_cost = total_rm_cost + total_pm_cost + total_overhead

        if good_packets > Decimal("0"):
            cost_per_packet = (total_run_cost / good_packets).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            margin_per_packet = (selling_price - cost_per_packet).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            margin_pct = ((margin_per_packet / selling_price) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            cost_per_packet = Decimal("0.00")
            margin_per_packet = Decimal("0.00")
            margin_pct = Decimal("0.00")

        return {
            "rm_cost": total_rm_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "pm_cost": total_pm_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "overhead_cost": total_overhead.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "total_cost": total_run_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "good_output_qty": good_packets,
            "cost_per_packet": cost_per_packet,
            "selling_price": selling_price.quantize(Decimal("0.01")),
            "margin_per_packet": margin_per_packet,
            "margin_pct": margin_pct,
            "valuation_method": "WAC"
        }
