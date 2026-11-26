<div align="center">

# WEXORA

### Order-to-Audit ERP for a Small Food Manufacturer

*Every Order. Every Transaction. Complete Transparency.*

**Centre for Digital Infrastructure, NIT Tiruchirappalli · Internship shortlisting task**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-Vite-61DAFB?logo=react&logoColor=black)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![Benchmark](https://img.shields.io/badge/Section_5_benchmark-11%2F11_match-brightgreen)

</div>

---

## Contents

1. [Overview](#1-overview)
2. [Quick start](#2-quick-start)
3. [Architecture](#3-architecture)
4. [Stack and justification](#4-stack-and-justification)
5. [Features by tier](#5-features-by-tier)
6. [Benchmark results](#6-benchmark-results)
7. [Costing method](#7-costing-method)
8. [Assumptions and known gaps](#8-assumptions-and-known-gaps)
9. [Repository layout](#9-repository-layout)
10. [Documentation](#10-documentation)

---

## 1. Overview

WEXORA takes a packaged-snacks factory (murukku, mixture, chips, sweets) from a salesman's order to the auditor's monthly report. Every transaction is entered once, at its source, and flows into stock, production, costing and accounts.

**Two loops meet at finished-goods stock:**

| Loop | Flow |
| :--- | :--- |
| **Sales** | Order → verification → GST invoice → dispatch → finished-goods stock down → receivables and collections |
| **Production** | Raw material purchased → issued against a recipe (BOM) → packets produced → finished-goods stock up → variance and cost per packet |

**Core design principle:** stock is never an overwritten number. Every movement is an immutable ledger row linked to its source document, and balances are derived from the ledger.

---

## 2. Quick start

**Prerequisites**

- Python 3.10+ (SQLite is bundled)
- Node.js 18+ and npm (only needed to rebuild the UI; the production build is already in `frontend/dist`)

**Run locally**

```bash
# Windows
run.bat

# PowerShell
./run.ps1

# Any terminal
python backend/seed.py
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Then open **http://127.0.0.1:8000**.

**Test logins**

| Role | Username | Purpose |
| :--- | :--- | :--- |
| Factory admin | `admin` | Verify orders, GST invoicing, dispatch, collections |
| Salesman A (Tamil Nadu) | `salesman_a` | Mobile order entry for Tamil Nadu retailers |
| Salesman B (Karnataka) | `salesman_b` | Mobile order entry for Karnataka distributors |
| Production supervisor | `supervisor` | BOM, batch logging, actual issues, scrap and yield variance |
| External auditor | `auditor` | Read-only reports (GSTR-1, 3B, stock, ageing, audit pack) |
| Factory owner | `owner` | Dashboard: revenue, variance radar, packet cost and margin |

> A role switcher in the top header lets you change roles instantly while evaluating.

**Run the tests**

```bash
python backend/tests/test_benchmark.py              # every Section 5 check and ledger invariant
python backend/tests/test_units_gst_immutability.py # unit conversion, GST maths, database triggers
```

---

## 3. Architecture

![WEXORA architecture layers](docs/architecture.svg)

The system is built in layers, and each layer only talks to the one below it.

| Layer | Responsibility |
| :--- | :--- |
| **Clients** | Salesman mobile app (offline-capable), admin and production screens, read-only auditor and owner views |
| **API** | Login, role-based access, idempotent order submission |
| **Business logic** | Sales, production, purchasing, costing and GST as pure Python services |
| **Posting engine** | The only code that writes stock and audit rows, so no screen or report can alter a balance directly |
| **Storage** | Append-only stock ledger, documents and masters, hash-chained audit log |
| **Reports** | Balances, GST, variance, ageing and the audit pack, all derived from stored data |

---

## 4. Stack and justification

| Layer | Choice | Why |
| :--- | :--- | :--- |
| Backend | **FastAPI + SQLite (WAL mode)** | Strict Pydantic schemas and pure Python domain services. SQLite needs no external server, runs on Windows, and supports triggers that enforce ledger immutability. |
| Money and quantity | **Python `Decimal`** | Avoids floating-point drift. Money is held to 2 decimal places with `ROUND_HALF_UP`; quantities to 4 decimal places. |
| Frontend | **React + Vite + Tailwind CSS + Lucide** | One single-page app with desktop workspaces for admin, production and auditor, and a mobile layout for salesmen. Pre-built and served by FastAPI. |
| Offline sync | **Client outbox (IndexedDB / LocalStorage)** | Salesmen often work with weak signal. Orders queue locally and sync later, with `client_uuid` preventing duplicates. |
| Exports | **openpyxl, ZipFile, SHA-256** | Five-sheet Excel workbook and a one-click Audit Pack ZIP with a checksum `manifest.json`. |

---

## 5. Features by tier

### Must have: complete

- Role-based login and scoped views (salesman, admin, production supervisor, auditor, owner)
- Masters: items (raw, packaging, finished), products, customers, suppliers, units, BOMs
- Mobile order entry with product selection, quantity stepper, price display and order timeline
- GST tax invoices with HSN, taxable value, CGST/SGST or IGST, and financial-year numbering (`TN/26-27/0001`), with a printable invoice view
- BOM and production run engine that deducts raw and packaging stock and adds finished goods
- Planned vs actual consumption and yield, flagged beyond a ±3.0% tolerance
- Stock summary and stock ledger, each movement linked to its source document
- Sales register and stock reports, filterable by date and exportable to Excel and CSV

### Should have: complete

- Purchases and supplier records with batch numbers and expiry dates
- Payments against invoices (FIFO allocation) and ageing buckets: 0–30, 31–60, 61–90, 90+ days
- Cost per packet with labour, gas and power overheads, and margin against selling price
- GST summary mapped to GSTR-1 Table 12 (HSN summary) and GSTR-3B Table 3.1(a)
- Variance radar alert cards
- Owner dashboard: today's orders, revenue, stock health, unit economics

### Stretch goals delivered

| Feature | What it does |
| :--- | :--- |
| Offline order outbox | Captures orders without signal and syncs automatically |
| Reservation engine | `available = on_hand − reserved`, so two orders cannot claim the same stock |
| Partial approval and dispatch | Handles Distributor B's order when stock is short |
| Hash-chained audit trail | SHA-256 chain with a live check at `/api/audit/verify` |
| One-click Audit Pack | ZIP of all monthly reports with cryptographic checksums |
| Benchmark verification tab | Runs and checks the Section 5 scenario inside the app |

---

## 6. Benchmark results

All figures below come from the live run of the Section 5 scenario.

| Check | Expected | WEXORA result | Status |
| :--- | :--- | :--- | :---: |
| Flour closing balance | 120 kg (100 + 60 − 40) | 120.0000 kg | ✅ |
| Oil closing balance | 19.5 L (30 − 10.5) | 19.5000 L | ✅ |
| Pouches closing balance | 306 (500 − 188 − 6) | 306.0000 pcs | ✅ |
| Finished goods after run | 238 packets (50 + 188) | 238.0000 pkts | ✅ |
| Finished goods after Retailer A dispatch | 88 packets (238 − 150) | 88.0000 pkts | ✅ |
| Yield variance | −6%, flagged | −6.00%, flagged | ✅ |
| Oil consumption variance | +5%, flagged | +5.00%, flagged | ✅ |
| Retailer A invoice | ₹7,500 + ₹187.50 CGST + ₹187.50 SGST = ₹7,875 | ₹7,875.00 | ✅ |
| Retailer A outstanding | ₹3,875 after ₹4,000 payment | ₹3,875.00 | ✅ |
| Distributor B order | Shortage of 32 flagged; IGST if invoiced | 32 packets short, flagged; IGST applied | ✅ |
| Cost per packet | Stated figure with method | ₹31.14 (WAC) / ₹30.90 (FIFO) | ✅ |

---

## 7. Costing method

**Valuation: weighted average cost (WAC)**, recomputed on every receipt. FIFO is calculated alongside as a comparison.

**Overheads:** labour, gas and power are spread across **good packets**, so scrap raises the cost per good packet.

**Worked example (benchmark run)**

| Item | Calculation | Amount (₹) |
| :--- | :--- | ---: |
| Flour | 40 kg × 43.125 | 1,725.00 |
| Oil | 10.5 L × 140 | 1,470.00 |
| Salt and spice mix | 1.2 kg × 200 | 240.00 |
| Pouches (188 good + 6 damaged) | 194 × 2.50 | 485.00 |
| Cartons | 9 × 15 | 135.00 |
| **Direct materials** | | **4,055.00** |
| Labour | | 1,200.00 |
| Gas and power | | 600.00 |
| **Total run cost** | | **5,855.00** |
| **Cost per good packet** | 5,855 ÷ 188 | **₹31.14** |
| **Margin** | 50.00 − 31.14 | **₹18.86 (37.7%)** |

**Flour rate:** the opening stock was 100 kg at ₹42 (₹4,200) and the purchase was 60 kg at ₹45 (₹2,700). Together that is 160 kg for ₹6,900, so WAC is ₹43.125 per kg.

**FIFO contrast:** FIFO takes the 40 kg of flour from the opening lot at ₹42. The run cost is ₹5,810 and the cost per packet is ₹30.90.

---

## 8. Assumptions and known gaps

**Assumptions**

1. The factory is in Tamil Nadu, so sales to other states are inter-state (IGST).
2. GST is 5% on benchmark products.
3. Damaged pouches are issued from stock and charged to the run.
4. Overheads are allocated per good packet.
5. The carton figure in the scenario (9 cartons for 188 packets at 20 per carton) is recorded as given, although 188 packets would normally need 10 cartons.

**Known gaps**

> Fill this in before submitting, for example: what is not implemented, what you would build next, and any limits of SQLite for multi-user use.

---

## 9. Repository layout

```
nit-wexora/
├── backend/
│   ├── app/
│   │   ├── main.py                       # FastAPI app and static mount
│   │   ├── database.py                   # SQLite schema, WAL mode, immutability triggers
│   │   ├── ledger.py                     # Append-only posting engine, SHA-256 audit log
│   │   └── services/
│   │       ├── unit_converter.py         # Base-unit normalization
│   │       ├── gst.py                    # Intra/inter-state GST, FY numbering
│   │       ├── costing.py                # WAC and FIFO costing
│   │       ├── variance.py               # Planned vs actual, tolerance alerts
│   │       ├── sales_service.py          # Order lifecycle, reservations
│   │       ├── production_service.py     # BOM execution, issues, scrap, output
│   │       ├── purchase_service.py       # Raw material purchases
│   │       ├── payment_service.py        # Payment allocation, ageing
│   │       └── report_service.py         # Reports, Excel, Audit Pack
│   ├── tests/
│   │   ├── test_benchmark.py             # Section 5 end-to-end checks
│   │   └── test_units_gst_immutability.py
│   └── seed.py                           # Section 5 master data and opening balances
├── frontend/
│   ├── src/
│   │   ├── App.jsx                       # Multi-role workspace UI
│   │   ├── api.js                        # API client and offline outbox
│   │   └── index.css
│   └── dist/                             # Pre-built production bundle
├── docs/
│   ├── architecture.svg                  # Architecture diagram
│   ├── DESIGN.md                         # Design note: ER diagram, maths, costing
│   └── BENCHMARK_WALKTHROUGH.md          # Demo script and check matrix
├── run.bat
├── run.ps1
├── pytest.ini
└── README.md
```

---

## 10. Documentation

| Document | Contents |
| :--- | :--- |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Data model, stock and BOM computation, costing and valuation |
| [`docs/BENCHMARK_WALKTHROUGH.md`](docs/BENCHMARK_WALKTHROUGH.md) | Script for the 8-minute demo video and the check matrix |