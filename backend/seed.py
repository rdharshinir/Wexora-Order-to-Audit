import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import init_db, get_db
from app.ledger import LedgerEngine, AuditEngine

def seed_benchmark_data(db_path=None):
    from app.database import DB_PATH
    actual_path = db_path or DB_PATH
    # If file exists, remove to ensure clean schema and triggers initialization
    if os.path.exists(actual_path):
        try:
            os.remove(actual_path)
        except Exception:
            pass

    init_db(actual_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_db(actual_path) as conn:
        cursor = conn.cursor()

        # 1. Users
        users = [
            ("USR-SALES-A", "salesman_a", "hash_pw", "Salesman A (Tamil Nadu)", "SALESMAN", "9876543210"),
            ("USR-SALES-B", "salesman_b", "hash_pw", "Salesman B (Karnataka/Interstate)", "SALESMAN", "9876543211"),
            ("USR-ADMIN-1", "admin", "hash_pw", "Factory Admin", "ADMIN", "9876543212"),
            ("USR-PROD-1", "supervisor", "hash_pw", "Production Supervisor", "PRODUCTION", "9876543213"),
            ("USR-AUDIT-1", "auditor", "hash_pw", "External Auditor & Accountant", "AUDITOR", "9876543214"),
            ("USR-OWNER-1", "owner", "hash_pw", "Factory Owner", "OWNER", "9876543215")
        ]
        for u in users:
            cursor.execute(
                "INSERT INTO users (id, username, password_hash, full_name, role, phone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (u[0], u[1], u[2], u[3], u[4], u[5], now_iso)
            )

        # 2. Units
        units = [
            ("kg", "Kilogram", "WEIGHT"),
            ("g", "Gram", "WEIGHT"),
            ("L", "Litre", "VOLUME"),
            ("mL", "Millilitre", "VOLUME"),
            ("piece", "Piece", "COUNT"),
            ("packet", "Packet", "COUNT"),
            ("carton", "Carton", "COUNT")
        ]
        for unit in units:
            cursor.execute("INSERT INTO units (code, name, kind) VALUES (?, ?, ?)", unit)

        unit_convs = [
            ("kg", "g", 1000.0),
            ("g", "kg", 0.001),
            ("L", "mL", 1000.0),
            ("mL", "L", 0.001),
            ("carton", "packet", 20.0),
            ("packet", "carton", 0.05),
            ("piece", "packet", 1.0),
            ("packet", "piece", 1.0)
        ]
        for uc in unit_convs:
            cursor.execute("INSERT INTO unit_conversions (from_unit, to_unit, factor) VALUES (?, ?, ?)", uc)

        # 3. Items (Section 5 Benchmark Masters)
        items = [
            ("RM-FLOUR", "RM-FLOUR", "Flour (Gram Flour/Rice Flour)", "RM", "kg", 50.0, "11010000", 5.0, 1),
            ("RM-OIL", "RM-OIL", "Cooking Oil", "RM", "L", 20.0, "15159099", 5.0, 1),
            ("RM-SPICE", "RM-SPICE", "Salt and Spice Mix", "RM", "kg", 5.0, "21039040", 5.0, 1),
            ("PM-POUCH-200G", "PM-POUCH-200G", "200 g Printed Pouch", "PM", "piece", 200.0, "39232990", 18.0, 0),
            ("PM-CARTON-20", "PM-CARTON-20", "Corrugated Carton (holds 20 pkts)", "PM", "piece", 20.0, "48191010", 18.0, 0),
            ("FG-MURUKKU-200G", "FG-MURUKKU-200G", "Murukku 200 g", "FG", "packet", 50.0, "19059040", 5.0, 1)
        ]
        for it in items:
            cursor.execute(
                """
                INSERT INTO items (id, sku, name, kind, base_unit, reorder_level, hsn_code, gst_rate, is_batch_tracked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                it
            )

        # 4. Products (Murukku 200 g, selling price ₹50, 5% GST, carton holds 20 pkts)
        cursor.execute(
            """
            INSERT INTO products (id, item_id, name, pack_size_g, selling_price, hsn_code, gst_rate, carton_capacity)
            VALUES ('PROD-MURUKKU-200G', 'FG-MURUKKU-200G', 'Murukku 200 g', 200.0, 50.0, '19059040', 5.0, 20)
            """
        )

        # 5. Customers
        customers = [
            ("CUST-RETAILER-A", "Retailer A", "RETAILER", "33AAAAA0000A1Z5", "33", "Tamil Nadu", "Shop 14, Main Bazaar, Tiruchirappalli", 30, "USR-SALES-A"),
            ("CUST-DISTRIB-B", "Distributor B", "DISTRIBUTOR", "29BBBBB0000B1Z6", "29", "Karnataka", "Plot 42, Peenya Industrial Area, Bengaluru", 45, "USR-SALES-B")
        ]
        for c in customers:
            cursor.execute(
                """
                INSERT INTO customers (id, name, type, gstin, state_code, state_name, address, credit_days, salesman_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                c
            )

        # 6. Suppliers
        cursor.execute(
            """
            INSERT INTO suppliers (id, name, gstin, state_code, state_name, phone, address)
            VALUES ('SUP-AGRO-FOODS', 'Sri Balaji Agro & Spices Ltd', '33SUPPL0000C1Z7', '33', 'Tamil Nadu', '9443312345', 'Madurai Road, Dindigul')
            """
        )

        # 7. Bill of Materials (BOM) for Murukku 200 g
        # 1 batch = 200 packets expected
        # Flour: 40 kg, Oil: 10 L, Salt/Spice mix: 1.2 kg, 200g pouch: 200 piece, Carton: 10 piece
        cursor.execute(
            """
            INSERT INTO boms (id, product_id, version, yield_qty, yield_unit, tolerance_pct, is_active, effective_from)
            VALUES ('BOM-MURUKKU-200G-V1', 'PROD-MURUKKU-200G', 1, 200.0, 'packet', 3.0, 1, ?)
            """,
            (now_iso,)
        )

        bom_lines = [
            ('BOM-MURUKKU-200G-V1', 'RM-FLOUR', 40.0, 'kg', 1),
            ('BOM-MURUKKU-200G-V1', 'RM-OIL', 10.0, 'L', 1),
            ('BOM-MURUKKU-200G-V1', 'RM-SPICE', 1.2, 'kg', 1),
            ('BOM-MURUKKU-200G-V1', 'PM-POUCH-200G', 200.0, 'piece', 1),
            ('BOM-MURUKKU-200G-V1', 'PM-CARTON-20', 10.0, 'piece', 1)
        ]
        for bl in bom_lines:
            cursor.execute("INSERT INTO bom_lines (bom_id, item_id, qty, unit, per_batch) VALUES (?, ?, ?, ?, ?)", bl)

        # 8. OPENING STOCK (Section 5 Benchmark starting stock)
        # Flour: 100 kg @ ₹42
        # Oil: 30 L @ ₹140
        # Spice mix: 5 kg @ ₹200
        # Pouches: 500 pcs @ ₹2.50
        # Cartons: 30 pcs @ ₹15
        # Finished Murukku 200 g: 50 packets @ ₹50 selling price
        opening_items = [
            ("RM-FLOUR", Decimal("100"), Decimal("42.00"), "LOT-FLOUR-OP"),
            ("RM-OIL", Decimal("30"), Decimal("140.00"), "LOT-OIL-OP"),
            ("RM-SPICE", Decimal("5"), Decimal("200.00"), "LOT-SPICE-OP"),
            ("PM-POUCH-200G", Decimal("500"), Decimal("2.50"), "LOT-POUCH-OP"),
            ("PM-CARTON-20", Decimal("30"), Decimal("15.00"), "LOT-CARTON-OP"),
            ("FG-MURUKKU-200G", Decimal("50"), Decimal("31.00"), "LOT-FG-OP")
        ]

        for item_id, qty, rate, lot in opening_items:
            LedgerEngine.post_movement(
                conn,
                item_id=item_id,
                qty_delta=qty,
                movement_type="OPENING",
                source_type="OPENING",
                source_id="BENCHMARK-OPENING",
                unit_cost=rate,
                batch_no=lot,
                user_id="SYSTEM",
                note="Section 5 Benchmark Opening Balance"
            )

        print("Benchmark Master Data and Opening Stock successfully seeded!")

if __name__ == "__main__":
    seed_benchmark_data()
