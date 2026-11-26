from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Tuple

class UnitConverter:
    # Standard metric conversions to base units (kg, L, piece)
    STANDARD_FACTORS: Dict[Tuple[str, str], Decimal] = {
        ("kg", "g"): Decimal("1000"),
        ("g", "kg"): Decimal("0.001"),
        ("L", "mL"): Decimal("1000"),
        ("mL", "L"): Decimal("0.001"),
        ("carton", "piece"): Decimal("20"), # default, can be overridden per product
        ("piece", "carton"): Decimal("0.05"),
        ("packet", "piece"): Decimal("1"),
        ("piece", "packet"): Decimal("1"),
    }

    @classmethod
    def to_base(cls, qty: Decimal, from_unit: str, base_unit: str, carton_capacity: int = 20) -> Decimal:
        if from_unit == base_unit:
            return qty

        # Custom carton to piece/packet
        if from_unit == "carton" and base_unit in ("piece", "packet"):
            return qty * Decimal(str(carton_capacity))
        if from_unit in ("piece", "packet") and base_unit == "carton":
            return (qty / Decimal(str(carton_capacity))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        pair = (from_unit, base_unit)
        if pair in cls.STANDARD_FACTORS:
            return (qty * cls.STANDARD_FACTORS[pair]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        # Reverse lookup
        rev_pair = (base_unit, from_unit)
        if rev_pair in cls.STANDARD_FACTORS:
            return (qty / cls.STANDARD_FACTORS[rev_pair]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        raise ValueError(f"Unsupported unit conversion from '{from_unit}' to '{base_unit}'")

    @classmethod
    def from_base(cls, qty_base: Decimal, to_unit: str, base_unit: str, carton_capacity: int = 20) -> Decimal:
        if to_unit == base_unit:
            return qty_base
        return cls.to_base(qty_base, base_unit, to_unit, carton_capacity)
