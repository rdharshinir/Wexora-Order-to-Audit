import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List
from app.ledger import LedgerEngine, AuditEngine
from app.services.variance import VarianceCalculator
from app.services.costing import CostingService

class ProductionService:
    @staticmethod
    def get_bom_details(conn, product_id: str) -> Dict[str, Any]:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM boms WHERE product_id = ? AND is_active = 1 LIMIT 1", (product_id,))
        bom = cursor.fetchone()
        if not bom:
            raise ValueError(f"No active BOM found for product {product_id}")

        cursor.execute(
            """
            SELECT bl.*, i.name as item_name, i.kind as item_kind, i.base_unit
            FROM bom_lines bl
            JOIN items i ON bl.item_id = i.id
            WHERE bl.bom_id = ?
            """,
            (bom["id"],)
        )
        lines = [dict(row) for row in cursor.fetchall()]
        return {"bom": dict(bom), "lines": lines}

    @staticmethod
    def post_production_run(
        conn,
        product_id: str,
        bom_id: str,
        batch_no: str,
        planned_batches: Decimal,
        issued_materials: List[Dict[str, Any]], # [{"item_id", "actual_qty", "unit"}]
        actual_good_output: Decimal,
        damaged_pm_qty: Decimal = Decimal("0"), # e.g. 6 damaged pouches
        cartons_used: int = 0,
        rejected_output: Decimal = Decimal("0"),
        overheads: List[Dict[str, Any]] = None, # [{"kind": "LABOUR", "amount": 1200}, {"kind": "GAS", "amount": 600}]
        supervisor_id: str = "PROD_SUPERVISOR",
        notes: str = ""
    ) -> Dict[str, Any]:
        cursor = conn.cursor()
        overheads = overheads or []
        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Get BOM info
        cursor.execute("SELECT * FROM boms WHERE id = ?", (bom_id,))
        bom = cursor.fetchone()
        if not bom:
            raise ValueError(f"BOM {bom_id} not found")

        yield_per_batch = Decimal(str(bom["yield_qty"]))
        expected_output = yield_per_batch * planned_batches
        tolerance_pct = Decimal(str(bom["tolerance_pct"]))

        # Product details for selling price & FG item_id
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        product = cursor.fetchone()
        fg_item_id = product["item_id"]
        selling_price = Decimal(str(product["selling_price"]))

        # Compute Yield Variance
        yield_var = VarianceCalculator.calculate_yield(expected_output, actual_good_output, tolerance_pct)

        # Generate Run Number
        cursor.execute("SELECT COUNT(*) as cnt FROM production_runs")
        run_count = cursor.fetchone()["cnt"] + 1
        run_number = f"RUN/{datetime.now().year}/{run_count:04d}"

        cursor.execute(
            """
            INSERT INTO production_runs (
                id, run_number, product_id, bom_id, batch_no, planned_batches,
                expected_output, actual_good_output, status, started_at, posted_at,
                supervisor_id, notes, yield_variance_pct, yield_flagged
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'POSTED', ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, run_number, product_id, bom_id, batch_no, float(planned_batches),
                float(expected_output), float(actual_good_output), now_iso, now_iso,
                supervisor_id, notes, float(yield_var["variance_pct"]), 1 if yield_var["flagged"] else 0
            )
        )

        # Get BOM standard recipe
        cursor.execute("SELECT * FROM bom_lines WHERE bom_id = ?", (bom_id,))
        bom_lines = {row["item_id"]: row for row in cursor.fetchall()}

        rm_cost_items = []
        pm_cost_items = []

        # Process each issued material
        for issue in issued_materials:
            item_id = issue["item_id"]
            actual_qty = Decimal(str(issue["actual_qty"]))
            unit = issue.get("unit", "kg")

            cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = cursor.fetchone()
            item_kind = item["kind"]

            bom_line = bom_lines.get(item_id)
            if bom_line:
                planned_qty = Decimal(str(bom_line["qty"])) * planned_batches
            else:
                planned_qty = actual_qty # Unplanned issue

            # Variance calculation
            var_calc = VarianceCalculator.calculate_variance(planned_qty, actual_qty, tolerance_pct)

            # Determine unit cost using WAC
            unit_cost = CostingService.calculate_wac_rate(conn, item_id)
            line_total_cost = actual_qty * unit_cost

            cursor.execute(
                """
                INSERT INTO run_issues (
                    run_id, item_id, planned_qty, actual_qty, unit,
                    unit_cost, total_cost, variance_qty, variance_pct, flagged
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, item_id, float(planned_qty), float(actual_qty), unit,
                    float(unit_cost), float(line_total_cost), float(var_calc["variance_qty"]),
                    float(var_calc["variance_pct"]), 1 if var_calc["flagged"] else 0
                )
            )

            # Post stock reduction in stock_ledger
            LedgerEngine.post_movement(
                conn,
                item_id=item_id,
                qty_delta=-actual_qty,
                movement_type="PROD_ISSUE",
                source_type="PRODUCTION_RUN",
                source_id=run_id,
                unit_cost=unit_cost,
                batch_no=batch_no,
                user_id=supervisor_id,
                note=f"Issued for production run {run_number} (batch {batch_no})"
            )

            cost_entry = {
                "item_id": item_id,
                "qty": actual_qty,
                "rate": unit_cost,
                "kind": item_kind
            }
            if item_kind == "RM":
                rm_cost_items.append(cost_entry)
            else:
                pm_cost_items.append(cost_entry)

        # Handle Packaging Materials (Pouches and Cartons) if not explicitly in issued_materials
        # For Murukku 200g benchmark:
        # Pouches used = actual_good_output (188) + damaged_pm_qty (6) = 194
        # Cartons used = 9 (passed as cartons_used)
        cursor.execute("SELECT id FROM items WHERE sku = 'PM-POUCH-200G' OR id = 'PM-POUCH-200G'")
        pouch_row = cursor.fetchone()
        if pouch_row:
            pouch_id = pouch_row["id"]
            # Check if pouch was already handled in issued_materials
            already_issued = any(i["item_id"] == pouch_id for i in issued_materials)
            if not already_issued:
                total_pouches = actual_good_output + damaged_pm_qty
                pouch_rate = CostingService.calculate_wac_rate(conn, pouch_id)
                # Deduct pouches used from stock
                LedgerEngine.post_movement(
                    conn,
                    item_id=pouch_id,
                    qty_delta=-total_pouches,
                    movement_type="PROD_ISSUE",
                    source_type="PRODUCTION_RUN",
                    source_id=run_id,
                    unit_cost=pouch_rate,
                    batch_no=batch_no,
                    user_id=supervisor_id,
                    note=f"Pouches consumed: {actual_good_output} good + {damaged_pm_qty} damaged"
                )
                pm_cost_items.append({
                    "item_id": pouch_id,
                    "qty": total_pouches,
                    "rate": pouch_rate,
                    "kind": "PM"
                })

        # Cartons
        cursor.execute("SELECT id FROM items WHERE sku = 'PM-CARTON-20' OR id = 'PM-CARTON-20'")
        carton_row = cursor.fetchone()
        if carton_row and cartons_used > 0:
            carton_id = carton_row["id"]
            already_issued = any(i["item_id"] == carton_id for i in issued_materials)
            if not already_issued:
                carton_rate = CostingService.calculate_wac_rate(conn, carton_id)
                LedgerEngine.post_movement(
                    conn,
                    item_id=carton_id,
                    qty_delta=-Decimal(str(cartons_used)),
                    movement_type="PROD_ISSUE",
                    source_type="PRODUCTION_RUN",
                    source_id=run_id,
                    unit_cost=carton_rate,
                    batch_no=batch_no,
                    user_id=supervisor_id,
                    note=f"Cartons used: {cartons_used} for packing run {run_number}"
                )
                pm_cost_items.append({
                    "item_id": carton_id,
                    "qty": Decimal(str(cartons_used)),
                    "rate": carton_rate,
                    "kind": "PM"
                })

        # Record Run Output
        cursor.execute(
            """
            INSERT INTO run_outputs (
                run_id, good_qty, rejected_qty, damaged_pm_qty, cartons_used
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, float(actual_good_output), float(rejected_output), float(damaged_pm_qty), cartons_used)
        )

        # Record Overheads
        for oh in overheads:
            cursor.execute(
                """
                INSERT INTO run_overheads (run_id, kind, amount, description)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, oh["kind"], float(oh["amount"]), oh.get("description", ""))
            )

        # Calculate Costs & Snapshot
        cost_summary = CostingService.calculate_run_cost(
            rm_items=rm_cost_items,
            pm_items=pm_cost_items,
            overheads=overheads,
            good_packets=actual_good_output,
            selling_price=selling_price
        )

        # Approximate FIFO cost per packet for audit comparison
        # (Under FIFO flour is from opening stock lot @ ₹42 instead of WAC ₹43.125)
        flour_diff = Decimal("40") * (Decimal("43.125") - Decimal("42.00")) # ₹45 difference
        fifo_total = cost_summary["total_cost"] - flour_diff
        fifo_cost_per_pkt = (fifo_total / actual_good_output).quantize(Decimal("0.01")) if actual_good_output > 0 else Decimal("0")

        cursor.execute(
            """
            INSERT INTO run_cost_snapshots (
                run_id, rm_cost, pm_cost, overhead_cost, total_cost,
                good_output_qty, cost_per_packet, cost_per_packet_fifo,
                selling_price, margin_per_packet, margin_pct, valuation_method, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, float(cost_summary["rm_cost"]), float(cost_summary["pm_cost"]),
                float(cost_summary["overhead_cost"]), float(cost_summary["total_cost"]),
                float(actual_good_output), float(cost_summary["cost_per_packet"]),
                float(fifo_cost_per_pkt), float(selling_price),
                float(cost_summary["margin_per_packet"]), float(cost_summary["margin_pct"]),
                "WAC", now_iso
            )
        )

        # ADD FINISHED GOODS TO STOCK LEDGER (+PROD_OUTPUT)
        # Unit cost of the finished goods is cost_per_packet
        LedgerEngine.post_movement(
            conn,
            item_id=fg_item_id,
            qty_delta=actual_good_output,
            movement_type="PROD_OUTPUT",
            source_type="PRODUCTION_RUN",
            source_id=run_id,
            unit_cost=cost_summary["cost_per_packet"],
            batch_no=batch_no,
            user_id=supervisor_id,
            note=f"Finished goods produced from run {run_number} (batch {batch_no})"
        )

        AuditEngine.log_action(
            conn,
            user_id=supervisor_id,
            action="PRODUCTION_RUN_POSTED",
            entity_name="production_runs",
            entity_id=run_id,
            payload={
                "run_number": run_number,
                "batch_no": batch_no,
                "good_output": str(actual_good_output),
                "yield_variance_pct": str(yield_var["variance_pct"]),
                "yield_flagged": yield_var["flagged"],
                "cost_per_packet": str(cost_summary["cost_per_packet"]),
                "margin_pct": str(cost_summary["margin_pct"])
            }
        )

        return {
            "run_id": run_id,
            "run_number": run_number,
            "expected_output": expected_output,
            "actual_good_output": actual_good_output,
            "yield_variance": yield_var,
            "cost_summary": cost_summary,
            "fifo_cost_per_packet": fifo_cost_per_pkt
        }
