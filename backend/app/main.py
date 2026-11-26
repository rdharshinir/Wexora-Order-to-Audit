import os
import sys
from decimal import Decimal
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, init_db
from app.ledger import LedgerEngine, AuditEngine
from app.services.purchase_service import PurchaseService
from app.services.production_service import ProductionService
from app.services.sales_service import SalesService
from app.services.payment_service import PaymentService
from app.services.report_service import ReportService
from seed import seed_benchmark_data

app = FastAPI(
    title="WEXORA - Order-to-Audit ERP",
    description="Every Order. Every Transaction. Complete Transparency. Built for NIT Tiruchirappalli shortlisting.",
    version="1.0.0"
)

# Enable CORS for frontend Vite dev server & production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()

# --- HEALTH & AUTH ---
@app.get("/api/health")
def health_check():
    return {"status": "ok", "system": "WEXORA", "tagline": "Every Order. Every Transaction. Complete Transparency."}

class LoginRequest(BaseModel):
    username: str

@app.post("/api/auth/login")
def login(req: LoginRequest):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (req.username,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {"user": dict(user)}

@app.get("/api/users")
def list_users():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, full_name, role, phone FROM users ORDER BY role")
        return {"users": [dict(r) for r in cursor.fetchall()]}

# --- MASTERS ---
@app.get("/api/masters")
def get_masters():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM items ORDER BY kind, sku")
        items = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT p.*, i.name as item_name, i.base_unit FROM products p JOIN items i ON p.item_id = i.id")
        products = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM customers ORDER BY name")
        customers = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM suppliers ORDER BY name")
        suppliers = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM boms WHERE is_active = 1")
        boms = [dict(r) for r in cursor.fetchall()]
        for b in boms:
            cursor.execute("SELECT bl.*, i.name as item_name, i.base_unit FROM bom_lines bl JOIN items i ON bl.item_id = i.id WHERE bl.bom_id = ?", (b["id"],))
            b["lines"] = [dict(r) for r in cursor.fetchall()]

        return {
            "items": items,
            "products": products,
            "customers": customers,
            "suppliers": suppliers,
            "boms": boms
        }

# --- OWNER DASHBOARD ---
@app.get("/api/dashboard/owner")
def get_owner_dashboard():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Today's orders & revenue
        cursor.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(total_amount), 0) as total FROM sales_orders WHERE status != 'CANCELLED'")
        order_stat = cursor.fetchone()

        # Stock summary
        stock = ReportService.get_stock_summary(conn)
        low_stock_alerts = [s for s in stock if s["closing"] <= s["reorder_level"]]

        # Recent variance alerts
        cursor.execute(
            """
            SELECT pr.id, pr.run_number, pr.batch_no, p.name as product_name,
                   pr.expected_output, pr.actual_good_output, pr.yield_variance_pct, pr.yield_flagged,
                   pr.posted_at
            FROM production_runs pr
            JOIN products p ON pr.product_id = p.id
            ORDER BY pr.started_at DESC LIMIT 5
            """
        )
        recent_runs = [dict(r) for r in cursor.fetchall()]

        # Latest cost per packet snapshot
        cursor.execute(
            """
            SELECT rcs.*, p.name as product_name, pr.run_number
            FROM run_cost_snapshots rcs
            JOIN production_runs pr ON rcs.run_id = pr.id
            JOIN products p ON pr.product_id = p.id
            ORDER BY rcs.id DESC LIMIT 1
            """
        )
        cost_snap = cursor.fetchone()

        # Outstanding receivables
        cursor.execute("SELECT c.id, c.name FROM customers c")
        custs = cursor.fetchall()
        total_outstanding = Decimal("0")
        total_0_30 = Decimal("0")
        total_31_60 = Decimal("0")
        total_61_plus = Decimal("0")

        for c in custs:
            out = PaymentService.get_customer_outstanding(conn, c["id"])
            total_outstanding += out["outstanding"]
            total_0_30 += out["ageing_buckets"]["0_30"]
            total_31_60 += out["ageing_buckets"]["31_60"]
            total_61_plus += (out["ageing_buckets"]["61_90"] + out["ageing_buckets"]["90_plus"])

        # Audit integrity status
        audit_stat = AuditEngine.verify_integrity(conn)

        return {
            "orders_count": order_stat["cnt"],
            "orders_total_amount": float(order_stat["total"]),
            "stock_summary": stock,
            "low_stock_alerts": low_stock_alerts,
            "recent_production_runs": recent_runs,
            "latest_cost_snapshot": dict(cost_snap) if cost_snap else None,
            "receivables": {
                "total_outstanding": float(total_outstanding),
                "bucket_0_30": float(total_0_30),
                "bucket_31_60": float(total_31_60),
                "bucket_61_plus": float(total_61_plus)
            },
            "audit_chain": audit_stat
        }

# --- INVENTORY & PROVENANCE ---
@app.get("/api/inventory/summary")
def get_inventory_summary():
    with get_db() as conn:
        return {"items": ReportService.get_stock_summary(conn)}

@app.get("/api/inventory/ledger")
def get_inventory_ledger(item_id: Optional[str] = None):
    with get_db() as conn:
        return {"ledger": ReportService.get_stock_ledger(conn, item_id)}

@app.get("/api/inventory/coverage/{product_id}")
def get_fg_coverage(product_id: str):
    with get_db() as conn:
        stock_info = LedgerEngine.get_fg_available(conn, product_id)
        return {
            "product_id": product_id,
            "on_hand": float(stock_info["on_hand"]),
            "reserved": float(stock_info["reserved"]),
            "available": float(stock_info["available"])
        }

# --- SALES ORDERS ---
class OrderLineCreate(BaseModel):
    product_id: str
    qty: float
    unit_rate: Optional[float] = None

class OrderCreate(BaseModel):
    customer_id: str
    salesman_id: str
    lines: List[OrderLineCreate]
    client_uuid: Optional[str] = None
    device_created_at: Optional[str] = None
    notes: Optional[str] = ""

@app.get("/api/orders")
def list_orders(salesman_id: Optional[str] = None, status: Optional[str] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT so.*, c.name as customer_name, c.type as customer_type, c.state_code, c.state_name,
                   u.full_name as salesman_name
            FROM sales_orders so
            JOIN customers c ON so.customer_id = c.id
            JOIN users u ON so.salesman_id = u.id
            WHERE 1=1
        """
        params = []
        if salesman_id:
            query += " AND so.salesman_id = ?"
            params.append(salesman_id)
        if status:
            query += " AND so.status = ?"
            params.append(status)
        query += " ORDER BY so.created_at DESC"

        cursor.execute(query, params)
        orders = [dict(r) for r in cursor.fetchall()]
        for o in orders:
            cursor.execute(
                """
                SELECT sol.*, p.name as product_name
                FROM sales_order_lines sol
                JOIN products p ON sol.product_id = p.id
                WHERE sol.order_id = ?
                """,
                (o["id"],)
            )
            o["lines"] = [dict(r) for r in cursor.fetchall()]
        return {"orders": orders}

@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT so.*, c.name as customer_name, c.state_code, c.state_name, c.gstin as customer_gstin,
                   u.full_name as salesman_name
            FROM sales_orders so
            JOIN customers c ON so.customer_id = c.id
            JOIN users u ON so.salesman_id = u.id
            WHERE so.id = ?
            """,
            (order_id,)
        )
        o = cursor.fetchone()
        if not o:
            raise HTTPException(status_code=404, detail="Order not found")
        order_dict = dict(o)

        cursor.execute(
            """
            SELECT sol.*, p.name as product_name, p.selling_price
            FROM sales_order_lines sol
            JOIN products p ON sol.product_id = p.id
            WHERE sol.order_id = ?
            """,
            (order_id,)
        )
        order_dict["lines"] = [dict(r) for r in cursor.fetchall()]
        order_dict["coverage"] = SalesService.check_order_stock_coverage(conn, order_id)
        return order_dict

@app.post("/api/orders")
def create_sales_order(req: OrderCreate):
    with get_db() as conn:
        lines = [l.dict() for l in req.lines]
        res = SalesService.create_order(
            conn,
            customer_id=req.customer_id,
            salesman_id=req.salesman_id,
            lines=lines,
            client_uuid=req.client_uuid,
            device_created_at=req.device_created_at,
            notes=req.notes or ""
        )
        return res

class LineApproval(BaseModel):
    line_id: int
    approved_qty: float

class ApproveOrderRequest(BaseModel):
    admin_id: str = "USR-ADMIN-1"
    approvals: Optional[List[LineApproval]] = None

@app.post("/api/orders/{order_id}/approve")
def approve_sales_order(order_id: str, req: ApproveOrderRequest):
    with get_db() as conn:
        app_list = [a.dict() for a in req.approvals] if req.approvals else None
        res = SalesService.approve_order(conn, order_id, approvals=app_list, admin_id=req.admin_id)
        return res

class InvoiceOrderRequest(BaseModel):
    admin_id: str = "USR-ADMIN-1"

@app.post("/api/orders/{order_id}/invoice")
def invoice_sales_order(order_id: str, req: InvoiceOrderRequest):
    with get_db() as conn:
        res = SalesService.raise_invoice(conn, order_id, admin_id=req.admin_id)
        return res

class DispatchItem(BaseModel):
    product_id: str
    qty: float

class DispatchOrderRequest(BaseModel):
    invoice_id: Optional[str] = None
    vehicle_no: str = ""
    dispatch_items: Optional[List[DispatchItem]] = None
    user_id: str = "USR-ADMIN-1"

@app.post("/api/orders/{order_id}/dispatch")
def dispatch_sales_order(order_id: str, req: DispatchOrderRequest):
    with get_db() as conn:
        items = [i.dict() for i in req.dispatch_items] if req.dispatch_items else None
        res = SalesService.record_dispatch(
            conn,
            order_id=order_id,
            invoice_id=req.invoice_id,
            dispatch_items=items,
            vehicle_no=req.vehicle_no,
            user_id=req.user_id
        )
        return res

# --- INVOICES & PAYMENTS ---
@app.get("/api/invoices")
def list_invoices():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT i.*, c.name as customer_name, c.state_code, c.state_name, c.gstin as customer_gstin,
                   so.order_number
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            LEFT JOIN sales_orders so ON i.order_id = so.id
            ORDER BY i.created_at DESC
            """
        )
        invoices = [dict(r) for r in cursor.fetchall()]
        for inv in invoices:
            cursor.execute(
                """
                SELECT il.*, p.name as product_name
                FROM invoice_lines il
                JOIN products p ON il.product_id = p.id
                WHERE il.invoice_id = ?
                """,
                (inv["id"],)
            )
            inv["lines"] = [dict(r) for r in cursor.fetchall()]
        return {"invoices": invoices}

@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT i.*, c.name as customer_name, c.state_code, c.state_name, c.gstin as customer_gstin,
                   c.address as customer_address, so.order_number
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            LEFT JOIN sales_orders so ON i.order_id = so.id
            WHERE i.id = ?
            """,
            (invoice_id,)
        )
        inv = cursor.fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        inv_dict = dict(inv)

        cursor.execute(
            """
            SELECT il.*, p.name as product_name
            FROM invoice_lines il
            JOIN products p ON il.product_id = p.id
            WHERE il.invoice_id = ?
            """,
            (invoice_id,)
        )
        inv_dict["lines"] = [dict(r) for r in cursor.fetchall()]
        return inv_dict

@app.get("/api/customers/{customer_id}/outstanding")
def get_customer_receivables(customer_id: str):
    with get_db() as conn:
        return PaymentService.get_customer_outstanding(conn, customer_id)

class PaymentCreate(BaseModel):
    customer_id: str
    amount: float
    payment_mode: str = "NEFT"
    reference_no: str = ""
    invoice_id: Optional[str] = None
    notes: Optional[str] = ""
    user_id: str = "USR-ADMIN-1"

@app.post("/api/payments")
def record_payment(req: PaymentCreate):
    with get_db() as conn:
        res = PaymentService.record_payment(
            conn,
            customer_id=req.customer_id,
            amount=Decimal(str(req.amount)),
            payment_mode=req.payment_mode,
            reference_no=req.reference_no,
            invoice_id=req.invoice_id,
            notes=req.notes or "",
            user_id=req.user_id
        )
        return res

# --- PURCHASES ---
class PurchaseItem(BaseModel):
    item_id: str
    qty: float
    unit: str = "kg"
    unit_rate: float
    gst_rate: float = 5.0
    batch_no: Optional[str] = None
    expiry_date: Optional[str] = None

class PurchaseCreate(BaseModel):
    supplier_id: str
    bill_no: str
    bill_date: str
    items: List[PurchaseItem]
    user_id: str = "USR-ADMIN-1"

@app.post("/api/purchases")
def create_purchase(req: PurchaseCreate):
    with get_db() as conn:
        items = [i.dict() for i in req.items]
        res = PurchaseService.create_purchase(
            conn,
            supplier_id=req.supplier_id,
            bill_no=req.bill_no,
            bill_date=req.bill_date,
            items=items,
            user_id=req.user_id
        )
        return res

@app.get("/api/purchases")
def list_purchases():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.*, s.name as supplier_name, s.gstin as supplier_gstin
            FROM purchases p
            JOIN suppliers s ON p.supplier_id = s.id
            ORDER BY p.created_at DESC
            """
        )
        purchases = [dict(r) for r in cursor.fetchall()]
        for pur in purchases:
            cursor.execute(
                """
                SELECT pl.*, i.name as item_name
                FROM purchase_lines pl
                JOIN items i ON pl.item_id = i.id
                WHERE pl.purchase_id = ?
                """,
                (pur["id"],)
            )
            pur["lines"] = [dict(r) for r in cursor.fetchall()]
        return {"purchases": purchases}

# --- PRODUCTION RUNS ---
class IssueItem(BaseModel):
    item_id: str
    actual_qty: float
    unit: str = "kg"

class OverheadItem(BaseModel):
    kind: str # LABOUR, GAS, POWER, OTHER
    amount: float
    description: Optional[str] = ""

class ProductionRunCreate(BaseModel):
    product_id: str
    bom_id: str
    batch_no: str
    planned_batches: float = 1.0
    issued_materials: List[IssueItem]
    actual_good_output: float
    damaged_pm_qty: float = 0.0
    cartons_used: int = 0
    rejected_output: float = 0.0
    overheads: Optional[List[OverheadItem]] = None
    supervisor_id: str = "USR-PROD-1"
    notes: Optional[str] = ""

@app.post("/api/production-runs")
def create_production_run(req: ProductionRunCreate):
    with get_db() as conn:
        issues = [i.dict() for i in req.issued_materials]
        ohs = [o.dict() for o in req.overheads] if req.overheads else []
        res = ProductionService.post_production_run(
            conn,
            product_id=req.product_id,
            bom_id=req.bom_id,
            batch_no=req.batch_no,
            planned_batches=Decimal(str(req.planned_batches)),
            issued_materials=issues,
            actual_good_output=Decimal(str(req.actual_good_output)),
            damaged_pm_qty=Decimal(str(req.damaged_pm_qty)),
            cartons_used=req.cartons_used,
            rejected_output=Decimal(str(req.rejected_output)),
            overheads=ohs,
            supervisor_id=req.supervisor_id,
            notes=req.notes or ""
        )
        return res

@app.get("/api/production-runs")
def list_production_runs():
    with get_db() as conn:
        return {"runs": ReportService.get_production_report(conn)}

# --- AUDIT & REPORTS ---
@app.get("/api/reports/sales")
def get_sales_report(from_date: Optional[str] = None, to_date: Optional[str] = None):
    with get_db() as conn:
        return {"sales": ReportService.get_sales_register(conn, from_date, to_date)}

@app.get("/api/reports/gst")
def get_gst_report(from_date: Optional[str] = None, to_date: Optional[str] = None):
    with get_db() as conn:
        return ReportService.get_gst_summary(conn, from_date, to_date)

@app.get("/api/reports/stock")
def get_stock_report():
    with get_db() as conn:
        return {"summary": ReportService.get_stock_summary(conn)}

@app.get("/api/reports/production")
def get_production_variance_report():
    with get_db() as conn:
        return {"production": ReportService.get_production_report(conn)}

@app.get("/api/reports/excel")
def download_excel_report():
    with get_db() as conn:
        excel_bytes = ReportService.generate_excel_export(conn)
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=WEXORA_Audit_Reports.xlsx"}
        )

@app.get("/api/reports/audit-pack")
def download_audit_pack():
    with get_db() as conn:
        zip_bytes = ReportService.generate_audit_pack(conn)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=WEXORA_Audit_Pack.zip"}
        )

@app.get("/api/audit/verify")
def verify_audit_log():
    with get_db() as conn:
        return AuditEngine.verify_integrity(conn)

# --- ONE-CLICK BENCHMARK RUNNER & RESET ---
@app.post("/api/benchmark/reset")
def reset_to_benchmark_opening():
    seed_benchmark_data()
    return {"status": "ok", "message": "Database reset to Section 5 Benchmark Opening Balance (Flour 100kg, Oil 30L, Spice 5kg, Pouches 500, Cartons 30, FG 50)"}

@app.post("/api/benchmark/run-full")
def run_full_benchmark_api():
    """
    Executes the entire 9-step benchmark scenario in order,
    demonstrating the complete Order-to-Audit flow!
    """
    seed_benchmark_data()
    with get_db() as conn:
        # Step 1: Purchase 60 kg flour @ ₹45
        p1 = PurchaseService.create_purchase(
            conn,
            supplier_id="SUP-AGRO-FOODS",
            bill_no="BILL-BENCH-01",
            bill_date="2026-11-20",
            items=[{"item_id": "RM-FLOUR", "qty": Decimal("60"), "unit_rate": Decimal("45.00"), "batch_no": "LOT-FLOUR-P1"}],
            user_id="USR-ADMIN-1"
        )

        # Step 2 & 3 & 8: Production Run with Overheads
        pr = ProductionService.post_production_run(
            conn,
            product_id="PROD-MURUKKU-200G",
            bom_id="BOM-MURUKKU-200G-V1",
            batch_no="BATCH-BENCH-01",
            planned_batches=Decimal("1"),
            issued_materials=[
                {"item_id": "RM-FLOUR", "actual_qty": Decimal("40"), "unit": "kg"},
                {"item_id": "RM-OIL", "actual_qty": Decimal("10.5"), "unit": "L"},
                {"item_id": "RM-SPICE", "actual_qty": Decimal("1.2"), "unit": "kg"}
            ],
            actual_good_output=Decimal("188"),
            damaged_pm_qty=Decimal("6"),
            cartons_used=9,
            overheads=[
                {"kind": "LABOUR", "amount": Decimal("1200.00"), "description": "Floor labour"},
                {"kind": "GAS", "amount": Decimal("600.00"), "description": "LPG & electricity"}
            ],
            supervisor_id="USR-PROD-1"
        )

        # Step 4 & 5: Salesman A order -> Approve -> Invoice -> Dispatch
        ord_a = SalesService.create_order(
            conn,
            customer_id="CUST-RETAILER-A",
            salesman_id="USR-SALES-A",
            lines=[{"product_id": "PROD-MURUKKU-200G", "qty": Decimal("150")}],
            client_uuid="UUID-API-BENCH-A"
        )
        SalesService.approve_order(conn, ord_a["order_id"])
        inv_a = SalesService.raise_invoice(conn, ord_a["order_id"])
        SalesService.record_dispatch(conn, ord_a["order_id"], invoice_id=inv_a["invoice_id"], vehicle_no="TN-45-AZ-1234")

        # Step 6: Salesman B order for Distributor B (120 packets, 32 shortage flagged, partial approval of 88 packets)
        ord_b = SalesService.create_order(
            conn,
            customer_id="CUST-DISTRIB-B",
            salesman_id="USR-SALES-B",
            lines=[{"product_id": "PROD-MURUKKU-200G", "qty": Decimal("120")}],
            client_uuid="UUID-API-BENCH-B"
        )
        cov_b = SalesService.check_order_stock_coverage(conn, ord_b["order_id"])
        SalesService.approve_order(
            conn,
            ord_b["order_id"],
            approvals=[{"line_id": cov_b[0]["line_id"], "approved_qty": Decimal("88")}]
        )
        inv_b = SalesService.raise_invoice(conn, ord_b["order_id"])

        # Step 7: Payment ₹4,000 from Retailer A
        pay_a = PaymentService.record_payment(
            conn,
            customer_id="CUST-RETAILER-A",
            amount=Decimal("4000.00"),
            payment_mode="NEFT",
            reference_no="UTR-BENCHMARK-4000",
            invoice_id=inv_a["invoice_id"]
        )

        # Get final balances
        balances = LedgerEngine.get_all_balances(conn)
        out_a = PaymentService.get_customer_outstanding(conn, "CUST-RETAILER-A")

        return {
            "status": "success",
            "message": "Full Benchmark Scenario Executed Successfully!",
            "results": {
                "flour_closing": float(balances["RM-FLOUR"]),
                "oil_closing": float(balances["RM-OIL"]),
                "pouches_closing": float(balances["PM-POUCH-200G"]),
                "finished_goods_closing": float(balances["FG-MURUKKU-200G"]),
                "yield_variance_pct": float(pr["yield_variance"]["variance_pct"]),
                "yield_flagged": pr["yield_variance"]["flagged"],
                "cost_per_packet": float(pr["cost_summary"]["cost_per_packet"]),
                "retailer_a_invoice_total": float(inv_a["total_amount"]),
                "retailer_a_outstanding": float(out_a["outstanding"]),
                "distributor_b_shortage": float(cov_b[0]["shortage"]),
                "distributor_b_approved": 88.0,
                "distributor_b_invoice_total": float(inv_b["total_amount"])
            }
        }

from fastapi.staticfiles import StaticFiles

# Mount static frontend if built
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
