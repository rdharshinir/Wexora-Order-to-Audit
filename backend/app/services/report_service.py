import io
import csv
import zipfile
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

class ReportService:
    @staticmethod
    def get_sales_register(conn, from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        query = """
            SELECT i.id as invoice_id, i.invoice_number, i.created_at, i.supply_type,
                   c.name as customer_name, c.type as customer_type, c.gstin as customer_gstin,
                   c.state_code, c.state_name,
                   i.taxable_amount, i.cgst_amount, i.sgst_amount, i.igst_amount, i.total_amount,
                   i.status
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            WHERE i.status != 'CANCELLED'
        """
        params = []
        if from_date:
            query += " AND i.created_at >= ?"
            params.append(from_date)
        if to_date:
            query += " AND i.created_at <= ?"
            params.append(to_date)
        query += " ORDER BY i.created_at ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_gst_summary(conn, from_date: Optional[str] = None, to_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Produces GSTR-1 and GSTR-3B mapped summaries.
        Table 4: B2B Supplies (registered customers with GSTIN)
        Table 5 & 7: B2C Supplies (consumers/unregistered)
        Table 12: HSN Summary of Outward Supplies
        GSTR-3B Table 3.1(a): Outward taxable supplies
        """
        cursor = conn.cursor()
        
        # Line-level details with product HSN
        query = """
            SELECT il.hsn_code, p.name as product_name, il.gst_rate,
                   c.gstin as customer_gstin, c.state_code, i.supply_type,
                   SUM(il.qty) as total_qty,
                   SUM(il.taxable_amount) as taxable_amount,
                   SUM(il.cgst_amount) as cgst_amount,
                   SUM(il.sgst_amount) as sgst_amount,
                   SUM(il.igst_amount) as igst_amount,
                   SUM(il.total_amount) as total_amount
            FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            JOIN customers c ON i.customer_id = c.id
            JOIN products p ON il.product_id = p.id
            WHERE i.status != 'CANCELLED'
        """
        params = []
        if from_date:
            query += " AND i.created_at >= ?"
            params.append(from_date)
        if to_date:
            query += " AND i.created_at <= ?"
            params.append(to_date)
        query += " GROUP BY il.hsn_code, p.name, il.gst_rate, c.gstin, c.state_code, i.supply_type"

        cursor.execute(query, params)
        lines = cursor.fetchall()

        b2b_supplies = []
        b2c_supplies = []
        hsn_summary = {}

        total_taxable = Decimal("0")
        total_cgst = Decimal("0")
        total_sgst = Decimal("0")
        total_igst = Decimal("0")
        total_tax = Decimal("0")

        for line in lines:
            t = Decimal(str(line["taxable_amount"]))
            c = Decimal(str(line["cgst_amount"]))
            s = Decimal(str(line["sgst_amount"]))
            ig = Decimal(str(line["igst_amount"]))
            tot = Decimal(str(line["total_amount"]))

            total_taxable += t
            total_cgst += c
            total_sgst += s
            total_igst += ig
            total_tax += (c + s + ig)

            entry = {
                "hsn_code": line["hsn_code"],
                "product_name": line["product_name"],
                "gst_rate": line["gst_rate"],
                "state_code": line["state_code"],
                "supply_type": line["supply_type"],
                "taxable_amount": t,
                "cgst_amount": c,
                "sgst_amount": s,
                "igst_amount": ig,
                "total_amount": tot
            }

            if line["customer_gstin"] and len(line["customer_gstin"].strip()) > 5:
                entry["gstin"] = line["customer_gstin"]
                b2b_supplies.append(entry)
            else:
                b2c_supplies.append(entry)

            # HSN aggregation
            hsn = line["hsn_code"]
            if hsn not in hsn_summary:
                hsn_summary[hsn] = {
                    "hsn_code": hsn,
                    "description": line["product_name"],
                    "total_qty": Decimal("0"),
                    "taxable_amount": Decimal("0"),
                    "cgst_amount": Decimal("0"),
                    "sgst_amount": Decimal("0"),
                    "igst_amount": Decimal("0"),
                    "total_tax": Decimal("0")
                }
            hsn_summary[hsn]["total_qty"] += Decimal(str(line["total_qty"]))
            hsn_summary[hsn]["taxable_amount"] += t
            hsn_summary[hsn]["cgst_amount"] += c
            hsn_summary[hsn]["sgst_amount"] += s
            hsn_summary[hsn]["igst_amount"] += ig
            hsn_summary[hsn]["total_tax"] += (c + s + ig)

        return {
            "b2b_supplies": b2b_supplies,
            "b2c_supplies": b2c_supplies,
            "hsn_summary": list(hsn_summary.values()),
            "gstr3b_table_3_1_a": {
                "nature_of_supplies": "Outward taxable supplies (other than zero rated, nil rated and exempted)",
                "total_taxable_value": total_taxable,
                "integrated_tax": total_igst,
                "central_tax": total_cgst,
                "state_ut_tax": total_sgst,
                "cess": Decimal("0.00")
            },
            "grand_totals": {
                "taxable_amount": total_taxable,
                "cgst_amount": total_cgst,
                "sgst_amount": total_sgst,
                "igst_amount": total_igst,
                "total_tax": total_tax,
                "total_invoice_value": total_taxable + total_tax
            }
        }

    @staticmethod
    def get_stock_summary(conn) -> List[Dict[str, Any]]:
        """
        Stock Summary:
        For every item: Opening Balance + Receipts - Issues +/- Adjustments = Closing Balance
        """
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM items ORDER BY kind, sku")
        items = cursor.fetchall()

        summary = []
        for it in items:
            item_id = it["id"]
            cursor.execute(
                """
                SELECT 
                    COALESCE(SUM(CASE WHEN movement_type = 'OPENING' THEN qty_delta ELSE 0 END), 0) as opening,
                    COALESCE(SUM(CASE WHEN movement_type IN ('PURCHASE', 'PROD_OUTPUT', 'SALES_RETURN') THEN qty_delta ELSE 0 END), 0) as receipts,
                    COALESCE(SUM(CASE WHEN movement_type IN ('PROD_ISSUE', 'PM_DAMAGE', 'DISPATCH') THEN -qty_delta ELSE 0 END), 0) as issues,
                    COALESCE(SUM(CASE WHEN movement_type IN ('ADJUSTMENT', 'REVERSAL') THEN qty_delta ELSE 0 END), 0) as adjustments,
                    COALESCE(SUM(qty_delta), 0) as closing
                FROM stock_ledger
                WHERE item_id = ?
                """,
                (item_id,)
            )
            r = cursor.fetchone()
            summary.append({
                "item_id": item_id,
                "sku": it["sku"],
                "name": it["name"],
                "kind": it["kind"],
                "base_unit": it["base_unit"],
                "opening": Decimal(str(r["opening"])).quantize(Decimal("0.0001")),
                "receipts": Decimal(str(r["receipts"])).quantize(Decimal("0.0001")),
                "issues": Decimal(str(r["issues"])).quantize(Decimal("0.0001")),
                "adjustments": Decimal(str(r["adjustments"])).quantize(Decimal("0.0001")),
                "closing": Decimal(str(r["closing"])).quantize(Decimal("0.0001")),
                "reorder_level": Decimal(str(it["reorder_level"]))
            })

        return summary

    @staticmethod
    def get_stock_ledger(conn, item_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Full provenance stock movements linked to source documents.
        """
        cursor = conn.cursor()
        query = """
            SELECT sl.*, i.name as item_name, i.base_unit, i.kind as item_kind
            FROM stock_ledger sl
            JOIN items i ON sl.item_id = i.id
        """
        params = []
        if item_id:
            query += " WHERE sl.item_id = ?"
            params.append(item_id)
        query += " ORDER BY sl.id ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_production_report(conn) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pr.*, p.name as product_name,
                   rcs.rm_cost, rcs.pm_cost, rcs.overhead_cost, rcs.total_cost,
                   rcs.cost_per_packet, rcs.cost_per_packet_fifo, rcs.selling_price,
                   rcs.margin_per_packet, rcs.margin_pct
            FROM production_runs pr
            JOIN products p ON pr.product_id = p.id
            LEFT JOIN run_cost_snapshots rcs ON pr.id = rcs.run_id
            ORDER BY pr.started_at DESC
            """
        )
        runs = cursor.fetchall()
        result = []
        for r in runs:
            run_dict = dict(r)
            cursor.execute("SELECT ri.*, i.name as item_name FROM run_issues ri JOIN items i ON ri.item_id = i.id WHERE ri.run_id = ?", (r["id"],))
            run_dict["issues"] = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM run_outputs WHERE run_id = ?", (r["id"],))
            out = cursor.fetchone()
            run_dict["output_details"] = dict(out) if out else {}
            cursor.execute("SELECT * FROM run_overheads WHERE run_id = ?", (r["id"],))
            run_dict["overheads"] = [dict(row) for row in cursor.fetchall()]
            result.append(run_dict)
        return result

    @staticmethod
    def generate_excel_export(conn) -> bytes:
        """
        Creates an Auditor-ready multi-sheet Excel workbook.
        """
        wb = openpyxl.Workbook()
        # Remove default sheet
        wb.remove(wb.active)

        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid") # Dark Blue
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        num_format = "#,##0.00"

        # Sheet 1: Sales Register
        ws_sales = wb.create_sheet(title="Sales Register")
        sales_data = ReportService.get_sales_register(conn)
        ws_sales.append(["Invoice No", "Date", "Customer Name", "State", "Supply Type", "Taxable (Rs)", "CGST (Rs)", "SGST (Rs)", "IGST (Rs)", "Total (Rs)"])
        for r in ws_sales[1]:
            r.fill = header_fill
            r.font = header_font
        for s in sales_data:
            ws_sales.append([
                s["invoice_number"], s["created_at"][:10], s["customer_name"],
                f"{s['state_code']} - {s['state_name']}", s["supply_type"],
                float(s["taxable_amount"]), float(s["cgst_amount"]), float(s["sgst_amount"]),
                float(s["igst_amount"]), float(s["total_amount"])
            ])

        # Sheet 2: GST Summary (GSTR-1 & 3B)
        ws_gst = wb.create_sheet(title="GST Summary")
        gst_data = ReportService.get_gst_summary(conn)
        ws_gst.append(["HSN Code", "Description", "Total Qty", "Taxable Amount (Rs)", "CGST (Rs)", "SGST (Rs)", "IGST (Rs)", "Total Tax (Rs)"])
        for r in ws_gst[1]:
            r.fill = header_fill
            r.font = header_font
        for h in gst_data["hsn_summary"]:
            ws_gst.append([
                h["hsn_code"], h["description"], float(h["total_qty"]),
                float(h["taxable_amount"]), float(h["cgst_amount"]), float(h["sgst_amount"]),
                float(h["igst_amount"]), float(h["total_tax"])
            ])

        # Sheet 3: Stock Summary
        ws_stock = wb.create_sheet(title="Stock Summary")
        stock_data = ReportService.get_stock_summary(conn)
        ws_stock.append(["SKU", "Item Name", "Category", "Unit", "Opening", "Receipts", "Issues", "Adjustments", "Closing Balance"])
        for r in ws_stock[1]:
            r.fill = header_fill
            r.font = header_font
        for item in stock_data:
            ws_stock.append([
                item["sku"], item["name"], item["kind"], item["base_unit"],
                float(item["opening"]), float(item["receipts"]), float(item["issues"]),
                float(item["adjustments"]), float(item["closing"])
            ])

        # Sheet 4: Stock Movement Ledger (Audit Provenance)
        ws_ledger = wb.create_sheet(title="Stock Ledger")
        ledger_data = ReportService.get_stock_ledger(conn)
        ws_ledger.append(["ID", "Date", "Item Name", "Movement Type", "Qty Delta", "Unit Cost (Rs)", "Source Type", "Source ID", "User", "Notes"])
        for r in ws_ledger[1]:
            r.fill = header_fill
            r.font = header_font
        for mov in ledger_data:
            ws_ledger.append([
                mov["id"], mov["posted_at"][:19], mov["item_name"], mov["movement_type"],
                float(mov["qty_delta"]), float(mov["unit_cost"] or 0), mov["source_type"],
                mov["source_id"], mov["user_id"], mov["note"]
            ])

        # Sheet 5: Production Variance & Costing
        ws_prod = wb.create_sheet(title="Production & Costing")
        prod_data = ReportService.get_production_report(conn)
        ws_prod.append(["Run Number", "Batch No", "Product", "Expected Output", "Actual Good", "Yield Var %", "Flagged?", "Cost/Pkt (WAC)", "Cost/Pkt (FIFO)", "Selling Price", "Margin (Rs)", "Margin %"])
        for r in ws_prod[1]:
            r.fill = header_fill
            r.font = header_font
        for p in prod_data:
            ws_prod.append([
                p["run_number"], p["batch_no"], p["product_name"],
                float(p["expected_output"]), float(p["actual_good_output"]),
                float(p["yield_variance_pct"] or 0), "YES" if p["yield_flagged"] else "NO",
                float(p["cost_per_packet"] or 0), float(p["cost_per_packet_fifo"] or 0),
                float(p["selling_price"] or 0), float(p["margin_per_packet"] or 0),
                float(p["margin_pct"] or 0)
            ])

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    @staticmethod
    def generate_audit_pack(conn) -> bytes:
        """
        Creates a ZIP archive containing:
        - WEXORA_Audit_Reports.xlsx
        - Sales_Register.csv
        - Stock_Summary.csv
        - Stock_Ledger_Provenance.csv
        - Production_Variance.csv
        - GST_Outward_Supplies.csv
        - manifest.json with SHA-256 checksums of each report
        """
        zip_buffer = io.BytesIO()
        manifest = {
            "system": "WEXORA - Every Order. Every Transaction. Complete Transparency.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": {}
        }

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # 1. Master Excel
            excel_bytes = ReportService.generate_excel_export(conn)
            excel_hash = hashlib.sha256(excel_bytes).hexdigest()
            zip_file.writestr("WEXORA_Audit_Reports.xlsx", excel_bytes)
            manifest["files"]["WEXORA_Audit_Reports.xlsx"] = {
                "sha256": excel_hash,
                "description": "Consolidated 5-sheet Auditor Workbook"
            }

            # 2. Sales CSV
            sales_rows = ReportService.get_sales_register(conn)
            sales_buf = io.StringIO()
            sales_writer = csv.writer(sales_buf)
            sales_writer.writerow(["Invoice No", "Date", "Customer", "State Code", "Supply Type", "Taxable", "CGST", "SGST", "IGST", "Total"])
            for s in sales_rows:
                sales_writer.writerow([s["invoice_number"], s["created_at"], s["customer_name"], s["state_code"], s["supply_type"], s["taxable_amount"], s["cgst_amount"], s["sgst_amount"], s["igst_amount"], s["total_amount"]])
            sales_bytes = sales_buf.getvalue().encode("utf-8")
            zip_file.writestr("Sales_Register.csv", sales_bytes)
            manifest["files"]["Sales_Register.csv"] = {"sha256": hashlib.sha256(sales_bytes).hexdigest()}

            # 3. Stock Summary CSV
            stock_rows = ReportService.get_stock_summary(conn)
            stock_buf = io.StringIO()
            stock_writer = csv.writer(stock_buf)
            stock_writer.writerow(["SKU", "Item Name", "Category", "Unit", "Opening", "Receipts", "Issues", "Adjustments", "Closing"])
            for st in stock_rows:
                stock_writer.writerow([st["sku"], st["name"], st["kind"], st["base_unit"], st["opening"], st["receipts"], st["issues"], st["adjustments"], st["closing"]])
            stock_bytes = stock_buf.getvalue().encode("utf-8")
            zip_file.writestr("Stock_Summary.csv", stock_bytes)
            manifest["files"]["Stock_Summary.csv"] = {"sha256": hashlib.sha256(stock_bytes).hexdigest()}

            # 4. Stock Ledger Provenance CSV
            ledger_rows = ReportService.get_stock_ledger(conn)
            ledger_buf = io.StringIO()
            ledger_writer = csv.writer(ledger_buf)
            ledger_writer.writerow(["ID", "Timestamp", "Item Name", "Delta", "Unit Cost", "Movement Type", "Source Type", "Source ID", "User", "Note"])
            for l in ledger_rows:
                ledger_writer.writerow([l["id"], l["posted_at"], l["item_name"], l["qty_delta"], l["unit_cost"], l["movement_type"], l["source_type"], l["source_id"], l["user_id"], l["note"]])
            ledger_bytes = ledger_buf.getvalue().encode("utf-8")
            zip_file.writestr("Stock_Ledger_Provenance.csv", ledger_bytes)
            manifest["files"]["Stock_Ledger_Provenance.csv"] = {"sha256": hashlib.sha256(ledger_bytes).hexdigest()}

            # Write manifest.json
            import json
            manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
            zip_file.writestr("manifest.json", manifest_bytes)

        return zip_buffer.getvalue()
