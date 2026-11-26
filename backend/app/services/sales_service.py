import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional
from app.ledger import LedgerEngine, AuditEngine
from app.services.gst import GSTCalculator, FACTORY_STATE_CODE

class SalesService:
    @staticmethod
    def create_order(
        conn,
        customer_id: str,
        salesman_id: str,
        lines: List[Dict[str, Any]], # [{"product_id", "qty", "unit_rate" (optional, falls back to product price)}]
        client_uuid: Optional[str] = None,
        device_created_at: Optional[str] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        cursor = conn.cursor()
        
        # Idempotency check for offline sync
        if client_uuid:
            cursor.execute("SELECT * FROM sales_orders WHERE client_uuid = ?", (client_uuid,))
            existing = cursor.fetchone()
            if existing:
                return {"order_id": existing["id"], "order_number": existing["order_number"], "status": existing["status"], "is_duplicate": True}

        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        cursor.execute("SELECT COUNT(*) as cnt FROM sales_orders")
        cnt = cursor.fetchone()["cnt"] + 1
        order_number = f"SO/{datetime.now().year}/{cnt:04d}"
        now_iso = datetime.now(timezone.utc).isoformat()

        total_taxable = Decimal("0")
        total_tax = Decimal("0")
        total_amount = Decimal("0")

        # Customer state for tax estimate
        cursor.execute("SELECT state_code FROM customers WHERE id = ?", (customer_id,))
        cust = cursor.fetchone()
        cust_state = cust["state_code"] if cust else FACTORY_STATE_CODE

        cursor.execute(
            """
            INSERT INTO sales_orders (
                id, order_number, client_uuid, customer_id, salesman_id,
                status, notes, total_taxable, total_tax, total_amount,
                created_at, device_created_at
            ) VALUES (?, ?, ?, ?, ?, 'SUBMITTED', ?, 0, 0, 0, ?, ?)
            """,
            (order_id, order_number, client_uuid, customer_id, salesman_id, notes, now_iso, device_created_at or now_iso)
        )

        for line in lines:
            product_id = line["product_id"]
            ordered_qty = Decimal(str(line["qty"]))
            
            cursor.execute("SELECT selling_price, gst_rate FROM products WHERE id = ?", (product_id,))
            prod = cursor.fetchone()
            unit_rate = Decimal(str(line.get("unit_rate", prod["selling_price"])))
            gst_rate = Decimal(str(prod["gst_rate"]))

            tax_info = GSTCalculator.calculate_line(ordered_qty * unit_rate, gst_rate, cust_state)
            
            total_taxable += tax_info["taxable_amount"]
            total_tax += tax_info["total_tax"]
            total_amount += tax_info["line_total"]

            cursor.execute(
                """
                INSERT INTO sales_order_lines (
                    order_id, product_id, ordered_qty, approved_qty,
                    dispatched_qty, unit_rate, gst_rate, line_total
                ) VALUES (?, ?, ?, NULL, 0, ?, ?, ?)
                """,
                (order_id, product_id, float(ordered_qty), float(unit_rate), float(gst_rate), float(tax_info["line_total"]))
            )

        cursor.execute(
            """
            UPDATE sales_orders
            SET total_taxable = ?, total_tax = ?, total_amount = ?
            WHERE id = ?
            """,
            (float(total_taxable), float(total_tax), float(total_amount), order_id)
        )

        AuditEngine.log_action(
            conn,
            user_id=salesman_id,
            action="ORDER_SUBMITTED",
            entity_name="sales_orders",
            entity_id=order_id,
            payload={
                "order_number": order_number,
                "customer_id": customer_id,
                "lines_count": len(lines),
                "total_amount": str(total_amount),
                "client_uuid": client_uuid
            }
        )

        return {
            "order_id": order_id,
            "order_number": order_number,
            "status": "SUBMITTED",
            "total_amount": total_amount,
            "is_duplicate": False
        }

    @staticmethod
    def check_order_stock_coverage(conn, order_id: str) -> List[Dict[str, Any]]:
        """
        Calculates for each line in the order:
        - Ordered quantity
        - Current FG on hand
        - Current FG reserved
        - Net FG available
        - Shortage = max(0, ordered - available)
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT sol.*, p.name as product_name, p.item_id
            FROM sales_order_lines sol
            JOIN products p ON sol.product_id = p.id
            WHERE sol.order_id = ?
            """,
            (order_id,)
        )
        lines = cursor.fetchall()
        coverage = []

        for line in lines:
            ordered_qty = Decimal(str(line["ordered_qty"]))
            stock_info = LedgerEngine.get_fg_available(conn, line["product_id"])
            on_hand = stock_info["on_hand"]
            reserved = stock_info["reserved"]
            available = stock_info["available"]
            shortage = max(Decimal("0"), ordered_qty - available)

            coverage.append({
                "line_id": line["id"],
                "product_id": line["product_id"],
                "product_name": line["product_name"],
                "ordered_qty": ordered_qty,
                "on_hand": on_hand,
                "reserved": reserved,
                "available": available,
                "shortage": shortage,
                "is_sufficient": shortage == Decimal("0")
            })

        return coverage

    @staticmethod
    def approve_order(
        conn,
        order_id: str,
        approvals: Optional[List[Dict[str, Any]]] = None, # [{"line_id", "approved_qty", "approved_rate" (opt)}]
        admin_id: str = "ADMIN"
    ) -> Dict[str, Any]:
        """
        Approves an order.
        If approvals list is provided, allows partial approval (e.g. approve 88 packets out of 120).
        Creates ACTIVE stock reservations for the approved quantities.
        """
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,))
        order = cursor.fetchone()
        if not order:
            raise ValueError(f"Order {order_id} not found")
        if order["status"] not in ("SUBMITTED", "APPROVED"):
            raise ValueError(f"Cannot approve order in status {order['status']}")

        cursor.execute("SELECT * FROM sales_order_lines WHERE order_id = ?", (order_id,))
        lines = cursor.fetchall()

        now_iso = datetime.now(timezone.utc).isoformat()
        total_taxable = Decimal("0")
        total_tax = Decimal("0")
        total_amount = Decimal("0")

        cursor.execute("SELECT state_code FROM customers WHERE id = ?", (order["customer_id"],))
        cust = cursor.fetchone()
        cust_state = cust["state_code"] if cust else FACTORY_STATE_CODE

        has_partial = False

        for line in lines:
            line_id = line["id"]
            ordered_qty = Decimal(str(line["ordered_qty"]))
            
            # Check if specific approved_qty was sent
            app_line = next((a for a in approvals if a["line_id"] == line_id), None) if approvals else None
            if app_line:
                approved_qty = Decimal(str(app_line["approved_qty"]))
                if approved_qty < ordered_qty:
                    has_partial = True
            else:
                approved_qty = ordered_qty

            unit_rate = Decimal(str(line["unit_rate"]))
            gst_rate = Decimal(str(line["gst_rate"]))

            tax_info = GSTCalculator.calculate_line(approved_qty * unit_rate, gst_rate, cust_state)
            total_taxable += tax_info["taxable_amount"]
            total_tax += tax_info["total_tax"]
            total_amount += tax_info["line_total"]

            cursor.execute(
                """
                UPDATE sales_order_lines
                SET approved_qty = ?, line_total = ?
                WHERE id = ?
                """,
                (float(approved_qty), float(tax_info["line_total"]), line_id)
            )

            # Create or update reservation
            cursor.execute(
                "SELECT id FROM stock_reservations WHERE order_id = ? AND product_id = ? AND status = 'ACTIVE'",
                (order_id, line["product_id"])
            )
            res_row = cursor.fetchone()
            if res_row:
                cursor.execute(
                    "UPDATE stock_reservations SET reserved_qty = ? WHERE id = ?",
                    (float(approved_qty), res_row["id"])
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO stock_reservations (order_id, product_id, reserved_qty, status, created_at)
                    VALUES (?, ?, ?, 'ACTIVE', ?)
                    """,
                    (order_id, line["product_id"], float(approved_qty), now_iso)
                )

        cursor.execute(
            """
            UPDATE sales_orders
            SET status = 'APPROVED', total_taxable = ?, total_tax = ?, total_amount = ?
            WHERE id = ?
            """,
            (float(total_taxable), float(total_tax), float(total_amount), order_id)
        )

        AuditEngine.log_action(
            conn,
            user_id=admin_id,
            action="ORDER_APPROVED",
            entity_name="sales_orders",
            entity_id=order_id,
            payload={
                "order_number": order["order_number"],
                "total_amount": str(total_amount),
                "has_partial": has_partial
            }
        )

        return {
            "order_id": order_id,
            "status": "APPROVED",
            "total_taxable": total_taxable,
            "total_tax": total_tax,
            "total_amount": total_amount,
            "has_partial": has_partial
        }

    @staticmethod
    def raise_invoice(conn, order_id: str, admin_id: str = "ADMIN") -> Dict[str, Any]:
        """
        Converts an APPROVED order into a GST tax invoice with sequential FY number.
        """
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,))
        order = cursor.fetchone()
        if not order:
            raise ValueError(f"Order {order_id} not found")
        if order["status"] not in ("APPROVED", "PARTIALLY_DISPATCHED"):
            raise ValueError(f"Cannot invoice order in status {order['status']}")

        cursor.execute("SELECT * FROM customers WHERE id = ?", (order["customer_id"],))
        customer = cursor.fetchone()
        if not customer:
            raise ValueError("Customer not found")

        # Generate sequential invoice number
        invoice_number, fy, seq = GSTCalculator.generate_invoice_number(conn)
        invoice_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        is_intra = (customer["state_code"].strip() == FACTORY_STATE_CODE)
        supply_type = "INTRA" if is_intra else "INTER"
        place_of_supply = f"{customer['state_code']} - {customer['state_name']}"

        cursor.execute("SELECT * FROM sales_order_lines WHERE order_id = ?", (order_id,))
        lines = cursor.fetchall()

        total_taxable = Decimal("0")
        total_cgst = Decimal("0")
        total_sgst = Decimal("0")
        total_igst = Decimal("0")
        total_amount = Decimal("0")

        cursor.execute(
            """
            INSERT INTO invoices (
                id, invoice_number, fy, seq, order_id, customer_id,
                place_of_supply, supply_type, taxable_amount, cgst_amount,
                sgst_amount, igst_amount, round_off, total_amount, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 'POSTED', ?)
            """,
            (invoice_id, invoice_number, fy, seq, order_id, customer["id"], place_of_supply, supply_type, now_iso)
        )

        for line in lines:
            qty = Decimal(str(line["approved_qty"] or line["ordered_qty"]))
            rate = Decimal(str(line["unit_rate"]))
            gst_rate = Decimal(str(line["gst_rate"]))

            cursor.execute("SELECT hsn_code FROM products WHERE id = ?", (line["product_id"],))
            prod = cursor.fetchone()
            hsn_code = prod["hsn_code"] if prod else "19059040"

            tax_info = GSTCalculator.calculate_line(qty * rate, gst_rate, customer["state_code"])

            total_taxable += tax_info["taxable_amount"]
            total_cgst += tax_info["cgst_amount"]
            total_sgst += tax_info["sgst_amount"]
            total_igst += tax_info["igst_amount"]
            total_amount += tax_info["line_total"]

            cursor.execute(
                """
                INSERT INTO invoice_lines (
                    invoice_id, product_id, hsn_code, qty, unit_rate,
                    taxable_amount, gst_rate, cgst_rate, cgst_amount,
                    sgst_rate, sgst_amount, igst_rate, igst_amount, total_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id, line["product_id"], hsn_code, float(qty), float(rate),
                    float(tax_info["taxable_amount"]), float(gst_rate),
                    float(tax_info["cgst_rate"]), float(tax_info["cgst_amount"]),
                    float(tax_info["sgst_rate"]), float(tax_info["sgst_amount"]),
                    float(tax_info["igst_rate"]), float(tax_info["igst_amount"]),
                    float(tax_info["line_total"])
                )
            )

        cursor.execute(
            """
            UPDATE invoices
            SET taxable_amount = ?, cgst_amount = ?, sgst_amount = ?, igst_amount = ?, total_amount = ?
            WHERE id = ?
            """,
            (float(total_taxable), float(total_cgst), float(total_sgst), float(total_igst), float(total_amount), invoice_id)
        )

        cursor.execute("UPDATE sales_orders SET status = 'INVOICED' WHERE id = ?", (order_id,))

        AuditEngine.log_action(
            conn,
            user_id=admin_id,
            action="INVOICE_POSTED",
            entity_name="invoices",
            entity_id=invoice_id,
            payload={
                "invoice_number": invoice_number,
                "order_id": order_id,
                "customer_name": customer["name"],
                "supply_type": supply_type,
                "taxable": str(total_taxable),
                "cgst": str(total_cgst),
                "sgst": str(total_sgst),
                "igst": str(total_igst),
                "total": str(total_amount)
            }
        )

        return {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "supply_type": supply_type,
            "taxable_amount": total_taxable,
            "cgst_amount": total_cgst,
            "sgst_amount": total_sgst,
            "igst_amount": total_igst,
            "total_amount": total_amount
        }

    @staticmethod
    def record_dispatch(
        conn,
        order_id: str,
        invoice_id: Optional[str] = None,
        dispatch_items: Optional[List[Dict[str, Any]]] = None, # [{"product_id", "qty"}]
        vehicle_no: str = "",
        user_id: str = "ADMIN"
    ) -> Dict[str, Any]:
        """
        Records dispatch:
        - Decreases Finished Goods stock in stock_ledger (-DISPATCH)
        - Converts reservations from ACTIVE to CONSUMED
        - Updates sales_orders status to DISPATCHED or PARTIALLY_DISPATCHED
        """
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,))
        order = cursor.fetchone()
        if not order:
            raise ValueError(f"Order {order_id} not found")

        cursor.execute("SELECT * FROM sales_order_lines WHERE order_id = ?", (order_id,))
        order_lines = cursor.fetchall()

        dispatch_id = f"DSP-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("SELECT COUNT(*) as cnt FROM dispatches")
        dsp_cnt = cursor.fetchone()["cnt"] + 1
        dispatch_number = f"DSP/{datetime.now().year}/{dsp_cnt:04d}"

        is_all_fully_dispatched = True

        cursor.execute(
            """
            INSERT INTO dispatches (
                id, dispatch_number, invoice_id, order_id, status,
                vehicle_no, dispatched_by, dispatched_at
            ) VALUES (?, ?, ?, ?, 'DISPATCHED', ?, ?, ?)
            """,
            (dispatch_id, dispatch_number, invoice_id, order_id, vehicle_no, user_id, now_iso)
        )

        for line in order_lines:
            product_id = line["product_id"]
            cursor.execute("SELECT item_id, carton_capacity FROM products WHERE id = ?", (product_id,))
            prod = cursor.fetchone()
            fg_item_id = prod["item_id"]
            carton_cap = prod["carton_capacity"] or 20

            # Determine dispatch qty
            custom_disp = next((d for d in dispatch_items if d["product_id"] == product_id), None) if dispatch_items else None
            if custom_disp:
                dispatch_qty = Decimal(str(custom_disp["qty"]))
            else:
                dispatch_qty = Decimal(str(line["approved_qty"] or line["ordered_qty"])) - Decimal(str(line["dispatched_qty"] or 0))

            if dispatch_qty <= Decimal("0"):
                continue

            new_dispatched_total = Decimal(str(line["dispatched_qty"] or 0)) + dispatch_qty
            approved_target = Decimal(str(line["approved_qty"] or line["ordered_qty"]))
            if new_dispatched_total < approved_target:
                is_all_fully_dispatched = False

            cartons = int((dispatch_qty / Decimal(str(carton_cap))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

            cursor.execute(
                """
                INSERT INTO dispatch_lines (dispatch_id, product_id, qty, cartons)
                VALUES (?, ?, ?, ?)
                """,
                (dispatch_id, product_id, float(dispatch_qty), cartons)
            )

            cursor.execute(
                "UPDATE sales_order_lines SET dispatched_qty = ? WHERE id = ?",
                (float(new_dispatched_total), line["id"])
            )

            # Deduct finished goods stock from ledger
            LedgerEngine.post_movement(
                conn,
                item_id=fg_item_id,
                qty_delta=-dispatch_qty,
                movement_type="DISPATCH",
                source_type="DISPATCH",
                source_id=dispatch_id,
                unit_cost=None,
                user_id=user_id,
                note=f"Dispatched order {order['order_number']}, Invoice {invoice_id or 'N/A'}"
            )

            # Consume reservation
            cursor.execute(
                """
                UPDATE stock_reservations
                SET status = 'CONSUMED'
                WHERE order_id = ? AND product_id = ? AND status = 'ACTIVE'
                """,
                (order_id, product_id)
            )

        new_status = "DISPATCHED" if is_all_fully_dispatched else "PARTIALLY_DISPATCHED"
        cursor.execute("UPDATE sales_orders SET status = ? WHERE id = ?", (new_status, order_id))
        cursor.execute("UPDATE dispatches SET status = ? WHERE id = ?", (new_status, dispatch_id))

        AuditEngine.log_action(
            conn,
            user_id=user_id,
            action=f"ORDER_{new_status}",
            entity_name="dispatches",
            entity_id=dispatch_id,
            payload={
                "dispatch_number": dispatch_number,
                "order_number": order["order_number"],
                "status": new_status,
                "vehicle_no": vehicle_no
            }
        )

        return {
            "dispatch_id": dispatch_id,
            "dispatch_number": dispatch_number,
            "status": new_status
        }
