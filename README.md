# WEXORA — Order-to-Audit ERP System

**Tagline:** *Every Order. Every Transaction. Complete Transparency.*  
**Organization:** Centre for Digital Infrastructure, NIT Tiruchirappalli  
**Use Case:** Small-scale food manufacturer of packaged South Indian snacks (Murukku, Mixture, Chips, Sweets).

---

## 1. Quick Start (Single Command Run)

### Prerequisites:
- Python 3.10+ (comes pre-bundled with SQLite)
- Node.js v18+ & npm (already built and bundled in `frontend/dist`)

### Run Locally:
```bash
# Windows
run.bat

# Or PowerShell
./run.ps1

# Or standard terminal:
python backend/seed.py
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```
Open your browser at: **`http://127.0.0.1:8000`**

### Test Logins (Role-Based Access):
| Role | Username | Purpose & Device |
| :--- | :--- | :--- |
| **Factory Admin** | `admin` | Order verification, GST tax invoicing, dispatch, collections |
| **Salesman A (TN)** | `salesman_a` | Mobile order entry, Tamil Nadu retailer sales |
| **Salesman B (KA)** | `salesman_b` | Mobile order entry, Karnataka distributor sales |
| **Production Supervisor** | `supervisor` | Recipe BOM, batch logging, actual issues, scrap & yield variance |
| **External Auditor** | `auditor` | Read-only monthly reports (GSTR-1, 3B, Stock, Ageing, Audit Pack) |
| **Factory Owner** | `owner` | Telemetry dashboard: revenue, variance radar, packet cost & margin |

*(A role switcher dropdown is available directly in the top header for instant evaluation switching).*

### Run Automated Test Suite:
```bash
# Validates every single Section 5 benchmark check and ledger invariant
python backend/tests/test_benchmark.py
python backend/tests/test_units_gst_immutability.py
```

---

## 2. Stack & Justification

| Layer | Choice | Justification |
| :--- | :--- | :--- |
| **Backend** | **Python (FastAPI) + SQLite (WAL Mode)** | FastAPI provides native asynchronous performance, strict Pydantic schemas, and pure Python domain services. SQLite with Write-Ahead Logging (WAL) requires zero external server setup, runs natively on Windows, and enforces database-level immutability triggers. |
| **Ledger & Math** | **Pure `Decimal` Fixed-Point Arithmetic** | In food manufacturing and taxation, IEEE 754 floating-point rounding errors lead to tax mismatches. Money is strictly calculated to 2 decimal places (paise) with `ROUND_HALF_UP`, and quantities to 4 decimal places. |
| **Frontend** | **React + Vite + Tailwind CSS + Lucide** | Responsive Single Page Application with dedicated desktop workspaces for Factory Admin, Production Floor, and Auditor, plus a mobile-optimized PWA layout for field salesmen. Pre-compiled into static production assets served directly by FastAPI. |
| **Offline Sync** | **IndexedDB / LocalStorage Client Outbox** | Field salesmen often visit rural retailers with weak or absent mobile signal. Orders taken offline are saved to a client outbox and automatically synchronized when connectivity returns, backed by idempotent `client_uuid` deduplication. |
| **Exports & Audit** | **openpyxl + ZipFile + SHA-256** | Generates an auditor-ready 5-sheet Excel workbook (`WEXORA_Audit_Reports.xlsx`) and a one-click Audit Pack ZIP containing CSVs, Excel, and a cryptographic `manifest.json`. |

---

## 3. Features Implemented vs. Section 6 Tiers

### ✅ Must Have (Minimum Requirement) — 100% Complete
- **Multi-Role Authentication & Scoped Views:** Salesman, Admin, Production Supervisor, Auditor, Owner.
- **Master Data Models:** Items (RM, PM, FG), Products, Customers, Suppliers, Units, and BOMs.
- **Mobile-Friendly Field Order Entry:** Fast product selection, quantity stepper, price display, and order timeline.
- **GST-Compliant Tax Invoices:** HSN code, taxable value, CGST/SGST (intra-state) or IGST (inter-state), financial year sequential numbering (`TN/26-27/0001`), and printable invoice modal.
- **BOM & Production Run Engine:** Auto-deducts raw materials and packaging materials, adds finished goods to stock, and calculates unit costs.
- **Planned vs. Actual Consumption & Yield:** Color-coded variance radar flagging deviations beyond ±3.0% tolerance.
- **Stock Summary & Stock Ledger:** Opening balance + receipts − issues ± adjustments = closing balance. Every stock movement links back to its source document ID.
- **Sales Register & Stock Reports:** Date-range filterable, exportable to Excel and CSV.

### ✅ Should Have — 100% Complete
- **Purchases & Supplier Records:** Bill tracking, batch numbers, expiry dates, and inward receipts.
- **Collections & Receivables Ageing:** Payment recording against open invoices, FIFO allocation, and ageing buckets (0–30, 31–60, 61–90, 90+ days).
- **Packet Costing with Overheads:** Allocates labour, gas, and power across good packets; displays gross margin against selling price.
- **GST Summary Report:** Mapped to GSTR-1 Table 12 (HSN Summary) and GSTR-3B Table 3.1(a).
- **Variance Radar:** Visual alert cards for yield and material consumption spikes.
- **Owner Executive Dashboard:** Real-time summary of today's orders, revenue, stock health, and unit economics.

### 🌟 Stretch Goals Implemented — Bonus
- **Offline-First Salesman Outbox with Automatic Sync:** Full offline order capture with idempotency keys (`client_uuid`).
- **Reservation Engine:** Prevents double-allocation of finished goods (`available = on_hand - reserved`).
- **Partial Approval & Partial Dispatch:** Explicitly handles Distributor B's order when available stock is insufficient.
- **Tamper-Evident SHA-256 Hash Chain Audit Trail:** Hash-chained audit log with live verification endpoint (`/api/audit/verify`).
- **One-Click Audit Pack:** Bundles all monthly reports into a ZIP archive with cryptographic checksums.
- **Interactive Benchmark Verification Matrix:** Built-in UI tab and API runner to run and verify the Section 5 scenario live.

---

## 4. Benchmark Scenario Results (Section 5)

| Check Item | Section 5 Requirement | WEXORA Live Result | Status |
| :--- | :--- | :--- | :---: |
| **Flour closing balance** | 120 kg (100 + 60 − 40) | **120.0000 kg** | ✅ **MATCH** |
| **Oil closing balance** | 19.5 L (30 − 10.5) | **19.5000 L** | ✅ **MATCH** |
| **Pouches closing balance** | 306 pcs (500 − 188 − 6) | **306.0000 pcs** | ✅ **MATCH** |
| **Finished goods after run** | 238 pkts (50 + 188) | **238.0000 pkts** | ✅ **MATCH** |
| **Finished goods after Retailer A dispatch** | 88 pkts (238 − 150) | **88.0000 pkts** | ✅ **MATCH** |
| **Yield variance** | 188 vs 200 expected, −6%, flagged | **-6.00%, FLAGGED** | ✅ **MATCH** |
| **Oil consumption variance** | 10.5 vs 10 L standard, +5%, flagged | **+5.00%, FLAGGED** | ✅ **MATCH** |
| **Retailer A invoice** | ₹7,500 taxable + ₹187.50 CGST + ₹187.50 SGST = ₹7,875 | **₹7,875.00 Total** | ✅ **MATCH** |
| **Retailer A outstanding** | ₹3,875 after ₹4,000 collection | **₹3,875.00** | ✅ **MATCH** |
| **Distributor B order** | Shortage of 32 pkts flagged; IGST applies if invoiced | **32 pkts Shortage Flagged; IGST applied** | ✅ **MATCH** |
| **Cost per packet** | Documented figure with valuation & overhead rules | **₹31.14 (WAC) / ₹30.90 (FIFO)** | ✅ **MATCH** |

### Explanation of Calculations & Valuation:
1. **Flour Valuation (WAC):** Opening stock had 100 kg @ ₹42.00 (₹4,200). Purchase added 60 kg @ ₹45.00 (₹2,700). Total: 160 kg for ₹6,900 $\rightarrow$ **WAC = ₹43.125 / kg**.
2. **Material Consumption for Run:**
   - Flour: $40 \times 43.125 = \mathbf{₹1,725.00}$
   - Oil: $10.5 \times 140 = \mathbf{₹1,470.00}$
   - Spice mix: $1.2 \times 200 = \mathbf{₹240.00}$
   - Pouches (188 good + 6 damaged = 194): $194 \times 2.50 = \mathbf{₹485.00}$
   - Cartons (9 used): $9 \times 15 = \mathbf{₹135.00}$
   - Direct Materials Total: $\mathbf{₹4,055.00}$
3. **Overheads:** Labour (₹1,200) + Gas & Power (₹600) = $\mathbf{₹1,800.00}$.
4. **Total Run Cost:** $4,055 + 1,800 = \mathbf{₹5,855.00}$.
5. **Cost per Good Packet:** $\frac{5,855}{188} = \mathbf{₹31.1436} \approx \mathbf{₹31.14}$.
6. **Margin:** Selling price ₹50.00 − ₹31.14 = $\mathbf{₹18.86\ (37.7\%)}$.
7. *(FIFO Contrast: Under FIFO, flour is taken from the opening lot at ₹42.00, yielding total cost ₹5,810.00 and cost per packet **₹30.90**).*

---

## 5. Documented Assumptions

1. **Factory Location & State Code:** Factory is situated in Tiruchirappalli, Tamil Nadu (State Code 33). Sales to Tamil Nadu customers are subject to intra-state GST (2.5% CGST + 2.5% SGST). Sales to customers outside Tamil Nadu (such as Distributor B in Karnataka, State Code 29) are subject to inter-state GST (5.0% IGST).
2. **Pouch Wastage Accounting:** Damaged pouches (6 pcs) are physically scrapped and deducted from packaging stock. Their purchase cost is absorbed into the run's packaging cost, appropriately elevating the cost per good packet.
3. **Carton Usage Anomaly:** 188 packets at 20 packets per carton physically represents 9 full cartons and 8 unboxed or loose packets. In accordance with Section 5, 9 cartons were consumed from stock and recorded.
4. **Reservation vs. Submission:** Stock is reserved upon Admin Order Approval rather than Salesman Submission, preventing field draft orders from locking factory inventory.
5. **Partial Dispatch & Back-Orders:** Supporting partial approval and partial dispatch allows the factory to fulfill Distributor B's available 88 packets immediately while keeping the remaining 32 packets active as a back-order.

---

## 6. Repository Layout

```
nit-wexora/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI application & static mount
│   │   ├── database.py                # SQLite schema, WAL mode, immutability triggers
│   │   ├── ledger.py                  # Append-only posting engine & SHA-256 audit log
│   │   ├── services/
│   │   │   ├── unit_converter.py      # Base unit normalization
│   │   │   ├── gst.py                 # Intra vs Inter GST engine & FY numbering
│   │   │   ├── costing.py             # WAC & FIFO unit costing engine
│   │   │   ├── variance.py            # Planned vs actual & tolerance alerts
│   │   │   ├── sales_service.py       # Order lifecycle, stock coverage, reservations
│   │   │   ├── production_service.py  # BOM execution, issues, scrap, FG output
│   │   │   ├── purchase_service.py    # Raw material inward purchases
│   │   │   ├── payment_service.py     # Customer payment allocation & ageing
│   │   │   └── report_service.py      # Sales, GST, Stock, Excel & Audit Pack generator
│   ├── tests/
│   │   ├── test_benchmark.py          # End-to-end Section 5 automated verification
│   │   └── test_units_gst_immutability.py # Unit tests for GST, units & DB triggers
│   └── seed.py                        # Loads Section 5 master data & opening balances
├── frontend/                          # React + Vite + Tailwind CSS SPA
│   ├── src/
│   │   ├── App.jsx                    # Comprehensive multi-role workspace UI
│   │   ├── api.js                     # API client + offline outbox sync engine
│   │   └── index.css                  # Tailwind styles
│   └── dist/                          # Pre-built production bundle
├── docs/
│   ├── DESIGN.md                      # System Design Note (ER diagram, math, costing)
│   └── BENCHMARK_WALKTHROUGH.md       # 8-minute demo video script & check matrix
├── run.bat                            # Windows one-click launcher
├── run.ps1                            # PowerShell launcher
├── pytest.ini                         # Pytest configuration
└── README.md                          # Comprehensive documentation
```
