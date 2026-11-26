# WEXORA — Benchmark Demonstration Walkthrough
**Internship Problem Statement:** Centre for Digital Infrastructure, NIT Tiruchirappalli  
**Product:** WEXORA ("Every Order. Every Transaction. Complete Transparency.")  
**Scenario Duration:** Under 8 Minutes

---

## Benchmark Master Data (Starting State)

- **Factory Location:** Tamil Nadu (State Code: 33)
- **Murukku 200 g Selling Price:** ₹50.00 / packet before tax (GST: 5.0%)
- **BOM Recipe (1 Batch = 200 packets expected output):**
  - Flour: 40 kg
  - Cooking Oil: 10 L
  - Salt & Spice Mix: 1.2 kg
  - 200 g Pouches: 200 pcs
  - Cartons (holds 20 pkts): 10 pcs
- **Starting Opening Stock:**
  - Flour: 100 kg (@ ₹42.00)
  - Cooking Oil: 30 L (@ ₹140.00)
  - Salt & Spice Mix: 5 kg (@ ₹200.00)
  - 200 g Pouches: 500 pcs (@ ₹2.50)
  - Cartons: 30 pcs (@ ₹15.00)
  - Finished Goods Murukku 200 g: 50 packets

---

## Step-by-Step Walkthrough Guide

### Step 1: Record Purchase of Raw Material (Flour)
- **Actor:** Factory Admin (`admin`)
- **Action:**
  1. Open the Admin Desk / Purchases.
  2. Record purchase from *Sri Balaji Agro & Spices Ltd* (Supplier):
     - Item: Flour (`RM-FLOUR`)
     - Quantity: 60 kg
     - Unit Rate: ₹45.00 / kg
     - Bill No: `BILL-BENCH-01`
- **Ledger & Stock Check:**
  - `stock_ledger` appends `PURCHASE` movement (+60 kg).
  - Flour closing balance: $100 + 60 = \mathbf{160\ kg}$.
  - Recomputed Flour WAC Rate: $\frac{(100 \times 42) + (60 \times 45)}{160} = \mathbf{₹43.125 / kg}$.

---

### Step 2 & 3: Production Run & Wastage Accounting
- **Actor:** Production Supervisor (`supervisor`)
- **Action:**
  1. Navigate to **Production Floor**.
  2. Select Product: **Murukku 200 g** (BOM Version 1).
  3. Enter Batch No: `BATCH-2026-M01`.
  4. Enter Actual Issues:
     - Flour: **40 kg**
     - Cooking Oil: **10.5 L** (Deliberate 0.5 L over standard)
     - Salt & Spice Mix: **1.2 kg**
  5. Enter Output & Wastage:
     - Actual Good Packets: **188 pkts**
     - Damaged Pouches: **6 pcs**
     - Cartons Used: **9 pcs**
- **Ledger & Stock Check:**
  - Flour balance: $160 - 40 = \mathbf{120\ kg}$ ✓
  - Oil balance: $30 - 10.5 = \mathbf{19.5\ L}$ ✓
  - Pouches balance: $500 - (188 + 6) = \mathbf{306\ pcs}$ ✓
  - Cartons balance: $30 - 9 = \mathbf{21\ pcs}$ ✓
  - Finished Goods stock: $50 + 188 = \mathbf{238\ packets}$ ✓
- **Variance Radar Check:**
  - Yield Variance: $\frac{188 - 200}{200} \times 100 = \mathbf{-6.0\%}$ 🚩 **FLAGGED** (Exceeds 3% tolerance).
  - Oil Consumption Variance: $\frac{10.5 - 10}{10} \times 100 = \mathbf{+5.0\%}$ 🚩 **FLAGGED** (Exceeds 3% tolerance).
  - Flour & Spices: 0.0% variance (Within tolerance).

---

### Step 4: Field Salesman A Places Order for Retailer A (Mobile View)
- **Actor:** Salesman A (`salesman_a`) on mobile device
- **Action:**
  1. Switch role to Salesman A, view opens in mobile layout.
  2. Customer: **Retailer A** (Tamil Nadu, Intra-state).
  3. Select **Murukku 200 g**, set quantity to **150 packets**.
  4. Tap **Submit Order to Factory**.
- **Result:**
  - Order `SO/2026/0001` created with status `SUBMITTED`.
  - Zero WhatsApp/phone call step required.
  - If offline, order queues in client outbox and syncs automatically when connection restores.

---

### Step 5: Admin Approves, Invoices & Dispatches Order A
- **Actor:** Factory Admin (`admin`)
- **Action:**
  1. Select Order `SO/2026/0001` on Admin Desk.
  2. Review Stock Cover: Ordered: 150 pkts, On Hand: 238 pkts, Available: 238 pkts, Shortage: 0 pkts. **Status: Stock Fully Covered**.
  3. Click **Approve Full Order** (reserves 150 pkts).
  4. Click **Raise GST Invoice**:
     - Supply Type: **INTRA-STATE** (Tamil Nadu State Code 33 to 33).
     - Taxable Value: $150 \times 50 = \mathbf{₹7,500.00}$.
     - CGST (2.5%): $\mathbf{₹187.50}$.
     - SGST (2.5%): $\mathbf{₹187.50}$.
     - Total Invoice Value: $\mathbf{₹7,875.00}$ (Sequential Invoice Number: `TN/26-27/0001`).
  5. Click **Record Dispatch** (Vehicle: `TN-45-AZ-1234`).
- **Ledger & Stock Check:**
  - Finished Goods closing balance: $238 - 150 = \mathbf{88\ packets}$ ✓.

---

### Step 6: Salesman B Places Order for Distributor B (Karnataka) & Stock Shortage Handling
- **Actor:** Salesman B (`salesman_b`)
- **Action:**
  1. Customer: **Distributor B** (Karnataka, State Code 29, Inter-state).
  2. Select **Murukku 200 g**, set quantity to **120 packets**.
  3. Submit Order `SO/2026/0002`.
- **Admin Verification & Shortage Radar Check:**
  - Admin inspects order on Verification Desk.
  - **Live Stock Cover:** Ordered: 120 pkts, Net Available: **88 pkts**.
  - **Shortage Flagged:** $\mathbf{32\ packets}$ shortage flagged in red!
- **Partial Approval & Interstate Tax Invoicing:**
  1. Admin uses **Partial Approval** for the available **88 packets**.
  2. Order advances to `APPROVED` (with partial status).
  3. Click **Raise GST Invoice**:
     - Customer is in Karnataka (State Code 29 $\neq$ 33) $\rightarrow$ **INTER-STATE (IGST applies)**.
     - Taxable: $88 \times 50 = \mathbf{₹4,400.00}$.
     - IGST (5.0%): $\mathbf{₹220.00}$.
     - Total Invoice Value: $\mathbf{₹4,620.00}$.
  4. *(If whole 120 pkts were invoiced: ₹6,000 + ₹300 IGST = ₹6,300).*
  5. The remaining 32 packets remain back-ordered on the Order State Machine.

---

### Step 7: Record Payment Collection from Retailer A
- **Actor:** Factory Admin / Accountant
- **Action:**
  1. Open Collections Desk.
  2. Select Customer: **Retailer A**.
  3. Enter Payment: **₹4,000.00** via NEFT (Ref: `UTR-99887766`).
  4. Click **Record Payment**.
- **Receivables & Ageing Check:**
  - Total Invoiced: ₹7,875.00
  - Total Paid: ₹4,000.00
  - **Retailer A Outstanding Balance:** $7875 - 4000 = \mathbf{₹3,875.00}$ ✓.

---

### Step 8: Add Labour & Power Overheads, Display Packet Costing
- **Overheads Added to Run:**
  - Labour: ₹1,200.00
  - Gas & Power: ₹600.00
  - Total Overheads: ₹1,800.00
- **Costing Computation (Weighted Average Cost):**
  - Direct Raw Materials (Flour ₹1725 + Oil ₹1470 + Spice ₹240): ₹3,435.00
  - Packaging Materials (194 Pouches ₹485 + 9 Cartons ₹135): ₹620.00
  - Total Direct Materials: ₹4,055.00
  - Total Overheads: ₹1,800.00
  - Total Run Cost: **₹5,855.00**
  - Good Output Packets: **188 packets**
  - **Cost Per Packet (WAC):** $\frac{5855}{188} = \mathbf{₹31.14}$ ✓
  - **Gross Margin:** $50 - 31.14 = \mathbf{₹18.86\ (37.7\%)}$ ✓

---

### Step 9: Monthly Auditor Reports & One-Click Audit Pack
- **Actor:** External Auditor (`auditor`)
- **Deliverables Generated:**
  1. **Sales Register:** Complete customer-wise and invoice-wise outward register.
  2. **GST Summary:** Clean GSTR-1 Table 12 HSN Summary & GSTR-3B Table 3.1(a) Outward Taxable Supplies.
  3. **Stock Summary & Ledger:** Opening, receipts, issues, closing for all 6 items with full provenance drill-down.
  4. **Production Variance Report:** Planned vs actual consumption, scrap count, flags.
  5. **Customer Outstanding & Ageing Report:** 0-30, 31-60, 61-90, 90+ days.
  6. **Download Auditor Excel (`WEXORA_Audit_Reports.xlsx`):** Professional 5-sheet workbook.
  7. **Download One-Click Audit Pack (`WEXORA_Audit_Pack.zip`):** Contains all reports in CSV + Excel + `manifest.json` containing cryptographic SHA-256 hashes of every file.
  8. **Verify Audit Trail:** Click **Verify SHA-256 Hash Chain** $\rightarrow$ verifies 100% integrity across all ledger postings.

---

## Benchmark Results Verification Table

| Benchmark Check Item | Required Result | Live WEXORA Result | Status |
| :--- | :--- | :--- | :---: |
| Flour closing balance | 120 kg | **120.0 kg** | ✅ **MATCH** |
| Oil closing balance | 19.5 L | **19.5 L** | ✅ **MATCH** |
| Pouches closing balance | 306 pcs | **306 pcs** | ✅ **MATCH** |
| Finished goods after run | 238 pkts | **238 pkts** | ✅ **MATCH** |
| Finished goods after Retailer A dispatch | 88 pkts | **88 pkts** | ✅ **MATCH** |
| Yield variance | 188 vs 200 (-6%, flagged) | **-6.0%, FLAGGED** | ✅ **MATCH** |
| Oil consumption variance | +5%, flagged | **+5.0%, FLAGGED** | ✅ **MATCH** |
| Retailer A GST Invoice | ₹7,500 + ₹187.50 CGST + ₹187.50 SGST = ₹7,875 | **₹7,875.00 Total** | ✅ **MATCH** |
| Retailer A outstanding balance | ₹3,875 | **₹3,875.00** | ✅ **MATCH** |
| Distributor B 120 pkts order | 32 pkts shortage flagged, IGST applies | **32 Shortage Flagged, IGST applied on 88 pkts** | ✅ **MATCH** |
| Cost per packet (WAC valuation) | Documented with method | **₹31.14 (WAC) / ₹30.90 (FIFO)** | ✅ **MATCH** |
