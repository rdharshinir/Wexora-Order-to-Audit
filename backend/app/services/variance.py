from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any

class VarianceCalculator:
    @staticmethod
    def calculate_variance(
        planned: Decimal,
        actual: Decimal,
        tolerance_pct: Decimal = Decimal("3.0")
    ) -> Dict[str, Any]:
        """
        Computes variance: (actual - planned) / planned * 100
        Flags variance if |variance_pct| > tolerance_pct
        """
        variance_qty = (actual - planned).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
        if planned == Decimal("0"):
            variance_pct = Decimal("0.00")
            flagged = actual > Decimal("0")
        else:
            variance_pct = (((actual - planned) / planned) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            flagged = abs(variance_pct) > tolerance_pct

        return {
            "planned_qty": planned,
            "actual_qty": actual,
            "variance_qty": variance_qty,
            "variance_pct": variance_pct,
            "tolerance_pct": tolerance_pct,
            "flagged": bool(flagged)
        }

    @staticmethod
    def calculate_yield(
        expected_output: Decimal,
        actual_good_output: Decimal,
        tolerance_pct: Decimal = Decimal("3.0")
    ) -> Dict[str, Any]:
        """
        Yield variance: (actual_good - expected_output) / expected_output * 100
        """
        variance_qty = (actual_good_output - expected_output).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if expected_output == Decimal("0"):
            variance_pct = Decimal("0.00")
            flagged = False
        else:
            variance_pct = (((actual_good_output - expected_output) / expected_output) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            flagged = abs(variance_pct) > tolerance_pct

        return {
            "expected_output": expected_output,
            "actual_good_output": actual_good_output,
            "variance_qty": variance_qty,
            "variance_pct": variance_pct,
            "flagged": bool(flagged)
        }
