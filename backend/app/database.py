import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("WEXORA_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wexora.db"))

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- Users and Roles
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('SALESMAN', 'ADMIN', 'PRODUCTION', 'AUDITOR', 'OWNER')),
    phone TEXT,
    created_at TEXT NOT NULL
);

-- Units & Conversions
CREATE TABLE IF NOT EXISTS units (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('WEIGHT', 'VOLUME', 'COUNT'))
);

CREATE TABLE IF NOT EXISTS unit_conversions (
    from_unit TEXT NOT NULL,
    to_unit TEXT NOT NULL,
    factor REAL NOT NULL,
    PRIMARY KEY (from_unit, to_unit),
    FOREIGN KEY (from_unit) REFERENCES units(code),
    FOREIGN KEY (to_unit) REFERENCES units(code)
);

-- Items (Raw Materials RM, Packaging Materials PM, Finished Goods FG)
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('RM', 'PM', 'FG')),
    base_unit TEXT NOT NULL,
    reorder_level REAL DEFAULT 0,
    hsn_code TEXT,
    gst_rate REAL DEFAULT 5.0,
    is_batch_tracked INTEGER DEFAULT 1,
    FOREIGN KEY (base_unit) REFERENCES units(code)
);

-- Finished Goods Products
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    item_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    pack_size_g REAL NOT NULL,
    selling_price REAL NOT NULL,
    hsn_code TEXT NOT NULL,
    gst_rate REAL NOT NULL DEFAULT 5.0,
    carton_capacity INTEGER DEFAULT 20,
    FOREIGN KEY (item_id) REFERENCES items(id)
);

-- Customers
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('RETAILER', 'DISTRIBUTOR')),
    gstin TEXT,
    state_code TEXT NOT NULL, -- '33' for Tamil Nadu, '29' for Karnataka, etc.
    state_name TEXT NOT NULL,
    address TEXT,
    credit_days INTEGER DEFAULT 30,
    salesman_id TEXT,
    FOREIGN KEY (salesman_id) REFERENCES users(id)
);

-- Suppliers
CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    gstin TEXT,
    state_code TEXT NOT NULL,
    state_name TEXT NOT NULL,
    phone TEXT,
    address TEXT
);

-- Bill of Materials (BOM)
CREATE TABLE IF NOT EXISTS boms (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    yield_qty REAL NOT NULL, -- e.g. 200 packets
    yield_unit TEXT NOT NULL,
    tolerance_pct REAL NOT NULL DEFAULT 3.0,
    is_active INTEGER NOT NULL DEFAULT 1,
    effective_from TEXT NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS bom_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    qty REAL NOT NULL,
    unit TEXT NOT NULL,
    per_batch INTEGER DEFAULT 1,
    FOREIGN KEY (bom_id) REFERENCES boms(id),
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (unit) REFERENCES units(code)
);

-- Sales Orders
CREATE TABLE IF NOT EXISTS sales_orders (
    id TEXT PRIMARY KEY,
    order_number TEXT UNIQUE NOT NULL,
    client_uuid TEXT UNIQUE,
    customer_id TEXT NOT NULL,
    salesman_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SUBMITTED', 'APPROVED', 'INVOICED', 'PARTIALLY_DISPATCHED', 'DISPATCHED', 'REJECTED', 'CANCELLED')),
    notes TEXT,
    total_taxable REAL DEFAULT 0,
    total_tax REAL DEFAULT 0,
    total_amount REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    device_created_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (salesman_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sales_order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    ordered_qty REAL NOT NULL,
    approved_qty REAL,
    dispatched_qty REAL DEFAULT 0,
    unit_rate REAL NOT NULL,
    gst_rate REAL NOT NULL,
    line_total REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES sales_orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Stock Reservations
CREATE TABLE IF NOT EXISTS stock_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    reserved_qty REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'CONSUMED', 'RELEASED')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES sales_orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Invoices
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    invoice_number TEXT UNIQUE NOT NULL,
    fy TEXT NOT NULL,
    seq INTEGER NOT NULL,
    order_id TEXT,
    customer_id TEXT NOT NULL,
    place_of_supply TEXT NOT NULL,
    supply_type TEXT NOT NULL CHECK(supply_type IN ('INTRA', 'INTER')),
    taxable_amount REAL NOT NULL,
    cgst_amount REAL NOT NULL,
    sgst_amount REAL NOT NULL,
    igst_amount REAL NOT NULL,
    round_off REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('POSTED', 'PAID', 'PARTIALLY_PAID', 'CANCELLED')),
    cancelled_by_credit_note_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES sales_orders(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    hsn_code TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_rate REAL NOT NULL,
    taxable_amount REAL NOT NULL,
    gst_rate REAL NOT NULL,
    cgst_rate REAL NOT NULL,
    cgst_amount REAL NOT NULL,
    sgst_rate REAL NOT NULL,
    sgst_amount REAL NOT NULL,
    igst_rate REAL NOT NULL,
    igst_amount REAL NOT NULL,
    total_amount REAL NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Dispatches
CREATE TABLE IF NOT EXISTS dispatches (
    id TEXT PRIMARY KEY,
    dispatch_number TEXT UNIQUE NOT NULL,
    invoice_id TEXT,
    order_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DISPATCHED', 'PARTIALLY_DISPATCHED')),
    vehicle_no TEXT,
    dispatched_by TEXT NOT NULL,
    dispatched_at TEXT NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (order_id) REFERENCES sales_orders(id)
);

CREATE TABLE IF NOT EXISTS dispatch_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispatch_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    qty REAL NOT NULL,
    cartons INTEGER,
    FOREIGN KEY (dispatch_id) REFERENCES dispatches(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Payments and Allocations
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    payment_number TEXT UNIQUE NOT NULL,
    customer_id TEXT NOT NULL,
    amount REAL NOT NULL,
    payment_mode TEXT NOT NULL CHECK(payment_mode IN ('CASH', 'UPI', 'NEFT', 'CHEQUE')),
    reference_no TEXT,
    received_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS payment_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    allocated_amount REAL NOT NULL,
    allocated_at TEXT NOT NULL,
    FOREIGN KEY (payment_id) REFERENCES payments(id),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id)
);

-- Purchases
CREATE TABLE IF NOT EXISTS purchases (
    id TEXT PRIMARY KEY,
    purchase_number TEXT UNIQUE NOT NULL,
    supplier_id TEXT NOT NULL,
    bill_no TEXT,
    bill_date TEXT,
    total_taxable REAL NOT NULL,
    total_tax REAL NOT NULL,
    total_amount REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS purchase_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    qty REAL NOT NULL,
    unit TEXT NOT NULL,
    unit_rate REAL NOT NULL,
    taxable_amount REAL NOT NULL,
    gst_rate REAL NOT NULL,
    tax_amount REAL NOT NULL,
    total_amount REAL NOT NULL,
    batch_no TEXT,
    expiry_date TEXT,
    FOREIGN KEY (purchase_id) REFERENCES purchases(id),
    FOREIGN KEY (item_id) REFERENCES items(id)
);

-- Production Runs
CREATE TABLE IF NOT EXISTS production_runs (
    id TEXT PRIMARY KEY,
    run_number TEXT UNIQUE NOT NULL,
    product_id TEXT NOT NULL,
    bom_id TEXT NOT NULL,
    batch_no TEXT NOT NULL,
    planned_batches REAL NOT NULL DEFAULT 1,
    expected_output REAL NOT NULL,
    actual_good_output REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'POSTED', 'REVERSED')),
    started_at TEXT NOT NULL,
    posted_at TEXT,
    supervisor_id TEXT NOT NULL,
    notes TEXT,
    yield_variance_pct REAL,
    yield_flagged INTEGER DEFAULT 0,
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (bom_id) REFERENCES boms(id),
    FOREIGN KEY (supervisor_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS run_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    planned_qty REAL NOT NULL,
    actual_qty REAL NOT NULL,
    unit TEXT NOT NULL,
    unit_cost REAL NOT NULL,
    total_cost REAL NOT NULL,
    variance_qty REAL NOT NULL,
    variance_pct REAL NOT NULL,
    flagged INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES production_runs(id),
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE TABLE IF NOT EXISTS run_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    good_qty REAL NOT NULL,
    rejected_qty REAL NOT NULL DEFAULT 0,
    damaged_pm_qty REAL NOT NULL DEFAULT 0,
    cartons_used INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES production_runs(id)
);

CREATE TABLE IF NOT EXISTS run_overheads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('LABOUR', 'GAS', 'POWER', 'OTHER')),
    amount REAL NOT NULL,
    description TEXT,
    FOREIGN KEY (run_id) REFERENCES production_runs(id)
);

CREATE TABLE IF NOT EXISTS run_cost_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    rm_cost REAL NOT NULL,
    pm_cost REAL NOT NULL,
    overhead_cost REAL NOT NULL,
    total_cost REAL NOT NULL,
    good_output_qty REAL NOT NULL,
    cost_per_packet REAL NOT NULL,
    cost_per_packet_fifo REAL,
    selling_price REAL NOT NULL,
    margin_per_packet REAL NOT NULL,
    margin_pct REAL NOT NULL,
    valuation_method TEXT NOT NULL DEFAULT 'WAC',
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES production_runs(id)
);

-- THE APPEND-ONLY STOCK LEDGER
CREATE TABLE IF NOT EXISTS stock_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posted_at TEXT NOT NULL,
    item_id TEXT NOT NULL,
    batch_no TEXT,
    qty_delta REAL NOT NULL, -- +receipt / -issue in item base_unit
    unit_cost REAL,          -- valuation at time of posting
    movement_type TEXT NOT NULL CHECK(movement_type IN (
        'OPENING', 'PURCHASE', 'PROD_ISSUE', 'PROD_OUTPUT', 'PM_DAMAGE', 
        'DISPATCH', 'SALES_RETURN', 'ADJUSTMENT', 'REVERSAL'
    )),
    source_type TEXT NOT NULL, -- 'OPENING', 'PURCHASE', 'PRODUCTION_RUN', 'DISPATCH', 'RETURN', 'MANUAL'
    source_id TEXT NOT NULL,   -- Traceability ID to source document
    reverses_id INTEGER,
    user_id TEXT,
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (reverses_id) REFERENCES stock_ledger(id)
);

-- TAMPER-EVIDENT AUDIT LOG (SHA-256 HASH CHAINED)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);

-- Financial Year Sequence Generator for Gap-Free Invoicing
CREATE TABLE IF NOT EXISTS invoice_sequences (
    fy TEXT PRIMARY KEY,
    last_seq INTEGER NOT NULL DEFAULT 0
);

-- IMMUTABILITY TRIGGERS: Prevent UPDATE & DELETE on stock_ledger and audit_log
DROP TRIGGER IF EXISTS trg_prevent_stock_ledger_update;
CREATE TRIGGER trg_prevent_stock_ledger_update BEFORE UPDATE ON stock_ledger
BEGIN
    SELECT RAISE(ABORT, 'ILLEGAL ACTION: stock_ledger is an append-only ledger and cannot be updated');
END;

DROP TRIGGER IF EXISTS trg_prevent_stock_ledger_delete;
CREATE TRIGGER trg_prevent_stock_ledger_delete BEFORE DELETE ON stock_ledger
BEGIN
    SELECT RAISE(ABORT, 'ILLEGAL ACTION: stock_ledger is an append-only ledger and cannot be deleted');
END;

DROP TRIGGER IF EXISTS trg_prevent_audit_log_update;
CREATE TRIGGER trg_prevent_audit_log_update BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'ILLEGAL ACTION: audit_log is immutable and cannot be updated');
END;

DROP TRIGGER IF EXISTS trg_prevent_audit_log_delete;
CREATE TRIGGER trg_prevent_audit_log_delete BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'ILLEGAL ACTION: audit_log is immutable and cannot be deleted');
END;
"""

def get_db_connection(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

@contextmanager
def get_db(db_path=None):
    conn = get_db_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path=None):
    conn = get_db_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DB_PATH)
