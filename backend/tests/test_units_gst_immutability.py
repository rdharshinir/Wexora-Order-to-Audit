import os
import sys
import sqlite3
import pytest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db
from app.services.unit_converter import UnitConverter
from app.services.gst import GSTCalculator
from seed import seed_benchmark_data

def test_unit_conversions():
    # Weight
    assert UnitConverter.to_base(Decimal("1.5"), "kg", "g") == Decimal("1500.0000")
    assert UnitConverter.to_base(Decimal("2500"), "g", "kg") == Decimal("2.5000")
    
    # Volume
    assert UnitConverter.to_base(Decimal("2"), "L", "mL") == Decimal("2000.0000")
    assert UnitConverter.to_base(Decimal("750"), "mL", "L") == Decimal("0.7500")

    # Packaging
    assert UnitConverter.to_base(Decimal("5"), "carton", "packet", carton_capacity=20) == Decimal("100")
    assert UnitConverter.to_base(Decimal("100"), "packet", "carton", carton_capacity=20) == Decimal("5.0000")

def test_gst_calculations():
    # Intra-state (Tamil Nadu to Tamil Nadu)
    res_intra = GSTCalculator.calculate_line(Decimal("7500.00"), Decimal("5.0"), "33")
    assert res_intra["supply_type"] == "INTRA"
    assert res_intra["cgst_amount"] == Decimal("187.50")
    assert res_intra["sgst_amount"] == Decimal("187.50")
    assert res_intra["igst_amount"] == Decimal("0.00")
    assert res_intra["line_total"] == Decimal("7875.00")

    # Inter-state (Tamil Nadu to Karnataka)
    res_inter = GSTCalculator.calculate_line(Decimal("6000.00"), Decimal("5.0"), "29")
    assert res_inter["supply_type"] == "INTER"
    assert res_inter["cgst_amount"] == Decimal("0.00")
    assert res_inter["sgst_amount"] == Decimal("0.00")
    assert res_inter["igst_amount"] == Decimal("300.00")
    assert res_inter["line_total"] == Decimal("6300.00")

def test_ledger_immutability():
    test_db = "wexora_immutability_test.db"
    seed_benchmark_data(test_db)

    with get_db(test_db) as conn:
        cursor = conn.cursor()
        
        # Test 1: Direct UPDATE on stock_ledger must be rejected by DB trigger
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            cursor.execute("UPDATE stock_ledger SET qty_delta = 999 WHERE id = 1")
        assert "append-only" in str(exc_info.value).lower() or "immutable" in str(exc_info.value).lower()

        # Test 2: Direct DELETE on stock_ledger must be rejected by DB trigger
        with pytest.raises(sqlite3.IntegrityError) as exc_info2:
            cursor.execute("DELETE FROM stock_ledger WHERE id = 1")
        assert "append-only" in str(exc_info2.value).lower() or "immutable" in str(exc_info2.value).lower()

        # Test 3: Direct UPDATE on audit_log must be rejected
        with pytest.raises(sqlite3.IntegrityError) as exc_info3:
            cursor.execute("UPDATE audit_log SET hash = 'HACKED' WHERE id = 1")
        assert "immutable" in str(exc_info3.value).lower()

if __name__ == "__main__":
    test_unit_conversions()
    test_gst_calculations()
    test_ledger_immutability()
    print("ALL UNIT & IMMUTABILITY TESTS PASSED!")
