import os
import sys
import pytest
from decimal import Decimal

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, init_db
from app.ledger import LedgerEngine, AuditEngine
from app.services.purchase_service import PurchaseService
from app.services.production_service import ProductionService
from app.services.sales_service import SalesService
from app.services.payment_service import PaymentService
from app.services.report_service import ReportService
from seed import seed_benchmark_data

def test_full_benchmark_scenario():
    # 0. Initialize and Seed
    test_db = "wexora_test.db"
    seed_benchmark_data(test_db)

    with get_db(test_db) as conn:
        # Initial check
        balances = LedgerEngine.get_all_balances(conn)
        assert balances["RM-FLOUR"] == Decimal("100.0000")
        assert balances["RM-OIL"] == Decimal("30.0000")
        assert balances["RM-SPICE"] == Decimal("5.0000")
        assert balances["PM-POUCH-200G"] == Decimal("500.0000")
        assert balances["PM-CARTON-20"] == Decimal("30.0000")
        assert balances["FG-MURUKKU-200G"] == Decimal("50.0000")

        # STEP 1: Record purchase of 60 kg flour at ₹45/kg
        pur_res = PurchaseService.create_purchase(
            conn,
            supplier_id="SUP-AGRO-FOODS",
            bill_no="BILL-2026-001",
            bill_date="2026-11-20",
            items=[{
                "item_id": "RM-FLOUR",
                "qty": Decimal("60"),
                "unit": "kg",
                "unit_rate": Decimal("45.00"),
                "gst_rate": Decimal("5.0"),
                "batch_no": "LOT-FLOUR-PUR-01"
            }],
            user_id="USR-ADMIN-1"
        )
        assert pur_res["total_taxable"] == Decimal("2700.00")
        assert LedgerEngine.get_item_balance(conn, "RM-FLOUR") == Decimal("160.0000")

        # STEP 2 & 3: Production Run Murukku 200 g
        # Issue 40 kg flour, 10.5 L oil (0.5 L over standard), 1.2 kg spice mix
        # Actual output: 188 good packets, 6 pouches damaged, 9 cartons used
        # Overheads: Labour ₹1,200, Gas/Power ₹600 (from Step 8)
        prod_res = ProductionService.post_production_run(
            conn,
            product_id="PROD-MURUKKU-200G",
            bom_id="BOM-MURUKKU-200G-V1",
            batch_no="BATCH-2026-M01",
            planned_batches=Decimal("1"),
            issued_materials=[
                {"item_id": "RM-FLOUR", "actual_qty": Decimal("40"), "unit": "kg"},
                {"item_id": "RM-OIL", "actual_qty": Decimal("10.5"), "unit": "L"},
                {"item_id": "RM-SPICE", "actual_qty": Decimal("1.2"), "unit": "kg"},
            ],
            actual_good_output=Decimal("188"),
            damaged_pm_qty=Decimal("6"),
            cartons_used=9,
            overheads=[
                {"kind": "LABOUR", "amount": Decimal("1200.00"), "description": "Floor workers wages for run"},
                {"kind": "GAS", "amount": Decimal("600.00"), "description": "LPG fuel & electricity for fryers"}
            ],
            supervisor_id="USR-PROD-1"
        )

        # CHECK BENCHMARK RESULTS TABLE
        # 1. Flour closing balance = 120 kg (100 + 60 - 40)
        flour_bal = LedgerEngine.get_item_balance(conn, "RM-FLOUR")
        assert flour_bal == Decimal("120.0000"), f"Expected 120 kg, got {flour_bal}"

        # 2. Oil closing balance = 19.5 L (30 - 10.5)
        oil_bal = LedgerEngine.get_item_balance(conn, "RM-OIL")
        assert oil_bal == Decimal("19.5000"), f"Expected 19.5 L, got {oil_bal}"

        # 3. Pouches closing balance = 306 (500 - 188 - 6)
        pouch_bal = LedgerEngine.get_item_balance(conn, "PM-POUCH-200G")
        assert pouch_bal == Decimal("306.0000"), f"Expected 306 pouches, got {pouch_bal}"

        # 4. Finished goods after run = 238 packets (50 + 188)
        fg_bal_after_run = LedgerEngine.get_item_balance(conn, "FG-MURUKKU-200G")
        assert fg_bal_after_run == Decimal("238.0000"), f"Expected 238 packets, got {fg_bal_after_run}"

        # 5. Yield variance: 188 vs 200 expected (-6%, flagged)
        yield_var = prod_res["yield_variance"]
        assert yield_var["variance_pct"] == Decimal("-6.00"), f"Expected -6.00%, got {yield_var['variance_pct']}"
        assert yield_var["flagged"] is True, "Yield variance must be flagged beyond 3% tolerance"

        # 6. Oil consumption variance: +5%, flagged
        # Check run_issues table
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM run_issues WHERE run_id = ? AND item_id = 'RM-OIL'", (prod_res["run_id"],))
        oil_issue = cursor.fetchone()
        assert Decimal(str(oil_issue["variance_pct"])) == Decimal("5.00")
        assert oil_issue["flagged"] == 1

        # 7. Check Cost per packet:
        # WAC: Total cost = ₹5,855.00, Cost per packet = ₹31.14
        cost_sum = prod_res["cost_summary"]
        assert cost_sum["total_cost"] == Decimal("5855.00"), f"Expected ₹5,855.00, got {cost_sum['total_cost']}"
        assert cost_sum["cost_per_packet"] == Decimal("31.14"), f"Expected ₹31.14, got {cost_sum['cost_per_packet']}"
        assert cost_sum["margin_per_packet"] == Decimal("18.86"), f"Expected ₹18.86, got {cost_sum['margin_per_packet']}"

        # STEP 4: Salesman A (mobile) places order for Retailer A (Tamil Nadu): 150 packets
        order_a = SalesService.create_order(
            conn,
            customer_id="CUST-RETAILER-A",
            salesman_id="USR-SALES-A",
            lines=[{"product_id": "PROD-MURUKKU-200G", "qty": Decimal("150")}],
            client_uuid="UUID-BENCHMARK-ORDER-A"
        )
        assert order_a["status"] == "SUBMITTED"

        # Check stock cover for Order A
        cov_a = SalesService.check_order_stock_coverage(conn, order_a["order_id"])
        assert cov_a[0]["available"] == Decimal("238.0000")
        assert cov_a[0]["shortage"] == Decimal("0")
        assert cov_a[0]["is_sufficient"] is True

        # STEP 5: Admin approves it, raises GST invoice, records dispatch
        app_a = SalesService.approve_order(conn, order_a["order_id"], admin_id="USR-ADMIN-1")
        assert app_a["status"] == "APPROVED"

        inv_a = SalesService.raise_invoice(conn, order_a["order_id"], admin_id="USR-ADMIN-1")
        # Retailer A invoice: ₹7,500 taxable + ₹187.50 CGST + ₹187.50 SGST = ₹7,875
        assert inv_a["supply_type"] == "INTRA"
        assert inv_a["taxable_amount"] == Decimal("7500.00")
        assert inv_a["cgst_amount"] == Decimal("187.50")
        assert inv_a["sgst_amount"] == Decimal("187.50")
        assert inv_a["igst_amount"] == Decimal("0.00")
        assert inv_a["total_amount"] == Decimal("7875.00")

        # Record dispatch
        disp_a = SalesService.record_dispatch(conn, order_a["order_id"], invoice_id=inv_a["invoice_id"], vehicle_no="TN-45-AZ-1234", user_id="USR-ADMIN-1")
        assert disp_a["status"] == "DISPATCHED"

        # Finished goods after Retailer A dispatch = 88 packets (238 - 150)
        fg_bal_after_disp = LedgerEngine.get_item_balance(conn, "FG-MURUKKU-200G")
        assert fg_bal_after_disp == Decimal("88.0000"), f"Expected 88 packets, got {fg_bal_after_disp}"

        # STEP 6: Salesman B places order for Distributor B (Karnataka): 120 packets
        order_b = SalesService.create_order(
            conn,
            customer_id="CUST-DISTRIB-B",
            salesman_id="USR-SALES-B",
            lines=[{"product_id": "PROD-MURUKKU-200G", "qty": Decimal("120")}],
            client_uuid="UUID-BENCHMARK-ORDER-B"
        )
        cov_b = SalesService.check_order_stock_coverage(conn, order_b["order_id"])
        # Available is 88, ordered 120 -> Shortage of 32 packets flagged!
        assert cov_b[0]["available"] == Decimal("88.0000")
        assert cov_b[0]["shortage"] == Decimal("32.0000"), f"Expected shortage of 32, got {cov_b[0]['shortage']}"
        assert cov_b[0]["is_sufficient"] is False

        # Support Partial Approval / Partial Dispatch for Distributor B
        # Admin partially approves 88 packets (the available stock)
        app_b = SalesService.approve_order(
            conn,
            order_b["order_id"],
            approvals=[{"line_id": cov_b[0]["line_id"], "approved_qty": Decimal("88")}],
            admin_id="USR-ADMIN-1"
        )
        assert app_b["has_partial"] is True

        # Raise Invoice for approved 88 packets
        inv_b = SalesService.raise_invoice(conn, order_b["order_id"], admin_id="USR-ADMIN-1")
        # Distributor B is in Karnataka (29) -> INTER state -> IGST applies!
        assert inv_b["supply_type"] == "INTER"
        assert inv_b["cgst_amount"] == Decimal("0.00")
        assert inv_b["sgst_amount"] == Decimal("0.00")
        assert inv_b["igst_amount"] == Decimal("220.00") # 88 * 50 = 4,400 * 5% = 220
        assert inv_b["total_amount"] == Decimal("4620.00")

        # STEP 7: Record payment of ₹4,000 from Retailer A
        pay_res = PaymentService.record_payment(
            conn,
            customer_id="CUST-RETAILER-A",
            amount=Decimal("4000.00"),
            payment_mode="NEFT",
            reference_no="UTR-99887766",
            invoice_id=inv_a["invoice_id"],
            user_id="USR-ADMIN-1"
        )
        assert pay_res["allocated_amount"] == Decimal("4000.00")

        # Retailer A outstanding balance = ₹3,875 (7,875 - 4,000)
        out_a = PaymentService.get_customer_outstanding(conn, "CUST-RETAILER-A")
        assert out_a["outstanding"] == Decimal("3875.00"), f"Expected ₹3,875.00 outstanding, got {out_a['outstanding']}"

        # STEP 9: Generate reports from Section 4.6
        sales_reg = ReportService.get_sales_register(conn)
        assert len(sales_reg) >= 1

        gst_summary = ReportService.get_gst_summary(conn)
        assert len(gst_summary["hsn_summary"]) >= 1

        stock_summary = ReportService.get_stock_summary(conn)
        assert len(stock_summary) == 6

        excel_pack = ReportService.generate_excel_export(conn)
        assert len(excel_pack) > 1000

        audit_zip = ReportService.generate_audit_pack(conn)
        assert len(audit_zip) > 1000

        # Verify Tamper-evident Audit Log
        audit_verify = AuditEngine.verify_integrity(conn)
        assert audit_verify["is_valid"] is True
        assert audit_verify["total_records"] > 10

    print("ALL BENCHMARK CRITERIA MET AND VERIFIED WITH 100% ACCURACY!")

if __name__ == "__main__":
    test_full_benchmark_scenario()
