# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
import base64


class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    # -------------------------
    # Helpers: Confirm + Sequence
    # -------------------------
    def _try_confirm_and_sequence(self, insurance):
        tried = []
        for method in ("action_confirm", "button_confirm", "confirm", "action_validate"):
            if hasattr(insurance, method):
                tried.append(method)
                try:
                    getattr(insurance, method)()
                    return True, tried
                except Exception:
                    continue
        return False, tried

    def _force_ins_sequence_if_needed(self, insurance):
        if not insurance.name or insurance.name == "/":
            seq = self.env["ir.sequence"].sudo().search(
                ["|", ("prefix", "ilike", "INS"), ("name", "ilike", "Insurance")],
                order="id desc",
                limit=1,
            )
            if seq:
                nxt = seq.next_by_id()
                if nxt:
                    insurance.write({"name": nxt})
                    return {
                        "forced_sequence": True,
                        "sequence_id": seq.id,
                        "sequence_name": seq.name,
                        "new_name": nxt,
                    }
        return {"forced_sequence": False}

    # -------------------------
    # Helpers: Link invoice -> Insurance (Cybro)
    # -------------------------
    def _set_cybro_invoice_link_fields(self, move_vals, insurance):
        """
        Cybro insurance.details shows invoices via insurance.details.invoice_ids (O2M).
        That O2M needs an inverse M2O on account.move, usually 'insurance_id'.
        We set that field if it exists + also set our own insurance_details_id.
        """
        move_fields = self.env["account.move"]._fields

        # Always set our explicit link (custom field added by our module)
        move_vals["insurance_details_id"] = insurance.id

        # Try set Cybro inverse field if present
        candidates = ["insurance_id", "insurance_detail_id", "insurance_claim_id"]
        for fname in candidates:
            if fname in move_fields:
                f = move_fields[fname]
                if getattr(f, "comodel_name", None) == "insurance.details":
                    move_vals[fname] = insurance.id
                    move_vals["_cybro_link_field_used"] = fname
                    break

        return move_vals

    # -------------------------
    # Helpers: create agent safely (handles DB NOT NULL constraints)
    # -------------------------
    def _build_required_vals(self, Model, base_vals: dict):
        """
        Fill required fields (ORM required=True). This prevents many DB NOT NULL crashes.
        If a required field is unknown, we best-effort fill it with a safe default.
        """
        vals = dict(base_vals or {})

        for fname, field in Model._fields.items():
            if not field.required:
                continue
            if fname in vals and vals[fname] not in (False, None, ""):
                continue

            # Common safe defaults:
            if fname == "company_id" and field.type == "many2one":
                vals[fname] = self.env.company.id
                continue

            if fname == "user_id" and field.type == "many2one":
                vals[fname] = self.env.user.id
                continue

            # Char/Text required fields → safe placeholder
            if field.type in ("char", "text"):
                vals[fname] = "N/A"
                continue

            # Selection required → first allowed value
            if field.type == "selection":
                try:
                    sel = field.selection(self.env)
                except Exception:
                    sel = field.selection
                if sel:
                    vals[fname] = sel[0][0]
                continue

            # Numeric required → 0
            if field.type in ("integer", "float", "monetary"):
                vals[fname] = 0
                continue

            # Boolean required → False
            if field.type == "boolean":
                vals[fname] = False
                continue

            # Many2one required: can't guess safely without a valid record.
            # Leave it. If DB requires it too, then payload must provide it.
            continue

        return vals

    def _get_or_create_agent(self, employee_dict: dict):
        emp_name = (employee_dict.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        # PHONE IS DB NOT NULL in employee_details → always set a non-empty value
        emp_phone = (employee_dict.get("phone") or "").strip() or "0000000000"

        def ensure_user_link(rec, Model):
            if "user_id" in Model._fields:
                try:
                    if not rec.user_id:
                        rec.write({"user_id": self.env.user.id})
                except Exception:
                    pass

        # Prefer Cybro's employee.details
        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)

            if not emp_rec:
                base_vals = {"name": emp_name, "phone": emp_phone}

                if "user_id" in Emp._fields:
                    base_vals["user_id"] = self.env.user.id

                vals = self._build_required_vals(Emp, base_vals)

                # hard guarantee for DB NOT NULL
                vals["phone"] = emp_phone

                emp_rec = Emp.create(vals)
            else:
                ensure_user_link(emp_rec, Emp)
                try:
                    if hasattr(emp_rec, "phone") and not emp_rec.phone:
                        emp_rec.write({"phone": emp_phone})
                except Exception:
                    pass

            return emp_rec, "employee.details"

        # Fallback to hr.employee if employee.details doesn't exist
        if "hr.employee" in self.env:
            Emp = self.env["hr.employee"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)

            if not emp_rec:
                vals = {"name": emp_name}
                if "user_id" in Emp._fields:
                    vals["user_id"] = self.env.user.id
                vals = self._build_required_vals(Emp, vals)
                emp_rec = Emp.create(vals)
            else:
                ensure_user_link(emp_rec, Emp)

            return emp_rec, "hr.employee"

        raise UserError("No employee model found (employee.details/hr.employee).")

    # -------------------------
    # Main RPC
    # -------------------------
    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload: dict):
        customer = payload.get("customer") or {}
        employee = payload.get("employee") or {}
        policy = payload.get("policy") or {}
        inv = payload.get("invoice") or {}

        cust_name = (customer.get("name") or "").strip()
        cust_email = (customer.get("email") or "").strip().lower()
        if not cust_name:
            raise UserError("Payload missing customer.name")
        if not cust_email:
            raise UserError("Payload missing customer.email")

        company = self.env.company
        target_state = (payload.get("state") or "confirmed").strip().lower()

        # -------------------------
        # Partner
        # -------------------------
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "ilike", cust_email)], limit=1)
        if not partner:
            try:
                partner = Partner.create({"name": cust_name, "email": cust_email, "customer_rank": 1})
            except Exception:
                partner = Partner.search([("email", "ilike", cust_email)], limit=1)
                if not partner:
                    raise
        else:
            if cust_name and partner.name != cust_name:
                partner.write({"name": cust_name})

        # -------------------------
        # Agent
        # -------------------------
        emp_rec, employee_model_used = self._get_or_create_agent(employee)

        # -------------------------
        # Policy (AUTO-CREATE if missing)
        # -------------------------
        if "policy.details" not in self.env:
            raise UserError("policy.details model not found.")

        Policy = self.env["policy.details"].sudo()

        policy_payload = policy or {}
        policy_id = policy_payload.get("id")
        policy_name = (policy_payload.get("name") or "").strip()

        policy_rec = None

        # 1) Use id if valid
        if policy_id:
            policy_rec = Policy.browse(int(policy_id))
            if not policy_rec.exists():
                raise UserError(f"Invalid policy.id: {policy_id}")

        # 2) Search by name
        if not policy_rec:
            if not policy_name:
                # policy_id is REQUIRED on insurance.details -> must have something
                policy_name = "Default Policy"
            policy_rec = Policy.search([("name", "=", policy_name)], limit=1)

        # 3) Create if still missing
        if not policy_rec:
            base_vals = {"name": policy_name}
            vals = self._build_required_vals(Policy, base_vals)
            vals["name"] = policy_name
            policy_rec = Policy.create(vals)

        # -------------------------
        # Currency
        # -------------------------
        currency_code = (payload.get("currency") or "AUD").strip()
        currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            raise UserError(f"Currency not found: {currency_code}")

        # -------------------------
        # Insurance
        # -------------------------
        start_date = payload.get("start_date") or fields.Date.context_today(self)
        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp_rec.id,
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "currency_id": currency.id,
            "policy_number": int(payload.get("policy_number") or 0),
            "payment_type": payload.get("payment_type") or "fixed",
            "state": "draft",
            "start_date": start_date,
            "name": "/",
        }
        insurance = self.sudo().create(insurance_vals)

        confirm_ran = False
        confirm_tried = []
        force_seq_info = {"forced_sequence": False}

        if target_state in ("confirmed", "confirm", "validated", "posted"):
            confirm_ran, confirm_tried = self._try_confirm_and_sequence(insurance)
            if "state" in insurance._fields and insurance.state == "draft":
                insurance.write({"state": "confirmed"})
            force_seq_info = self._force_ins_sequence_if_needed(insurance)

        insurance_name = insurance.name

        # -------------------------
        # Product (company-safe)
        # -------------------------
        Product = self.env["product.product"].sudo()
        product = Product.search(
            [("sale_ok", "=", True), "|", ("company_id", "=", False), ("company_id", "=", company.id)],
            limit=1,
        )
        if not product:
            product = Product.create(
                {"name": "Insurance Service", "type": "service", "sale_ok": True, "company_id": company.id}
            )

        # -------------------------
        # Journal
        # -------------------------
        journal = self.env["account.journal"].sudo().search(
            [("type", "=", "sale"), ("company_id", "=", company.id)],
            limit=1,
        )
        if not journal:
            raise UserError("No Sales Journal found for this company.")

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)

        # -------------------------
        # Invoice
        # -------------------------
        move_vals = {
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "invoice_user_id": self.env.user.id,
            "invoice_origin": insurance_name,
            "ref": insurance_name,
            "invoice_line_ids": [
                (0, 0, {
                    "product_id": product.id,
                    "name": inv.get("line_name") or f"Insurance: {insurance_name}",
                    "quantity": qty,
                    "price_unit": price_unit,
                })
            ],
        }
        move_vals = self._set_cybro_invoice_link_fields(move_vals, insurance)
        cybro_link_field_used = move_vals.pop("_cybro_link_field_used", None)

        move = self.env["account.move"].sudo().with_company(company).create(move_vals)
        move.action_post()

        # -------------------------
        # Email PDF
        # -------------------------
        emailed = False
        email_error = None
        try:
            report = self.env["ir.actions.report"].sudo().search(
                [("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")],
                limit=1,
            )
            if not report:
                raise UserError("No PDF report found for account.move.")

            ext = report.get_external_id()
            report_ref = ext.get(report.id)
            if not report_ref:
                raise UserError("Invoice report has no external id (xmlid).")

            pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(report_ref, res_ids=[move.id])

            attachment = self.env["ir.attachment"].sudo().create({
                "name": f"{move.name}.pdf",
                "type": "binary",
                "datas": base64.b64encode(pdf_content),
                "res_model": "account.move",
                "res_id": move.id,
                "mimetype": "application/pdf",
            })

            mail = self.env["mail.mail"].sudo().create({
                "subject": f"Invoice {move.name}",
                "email_to": cust_email,
                "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
                "attachment_ids": [(4, attachment.id)],
            })
            mail.send()
            emailed = True
        except Exception as e:
            emailed = False
            email_error = str(e)

        return {
            "insurance_id": insurance.id,
            "insurance_name": insurance.name,
            "insurance_state": insurance.state if "state" in insurance._fields else None,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "invoice_origin": move.invoice_origin,
            "emailed_to": cust_email,
            "emailed": emailed,
            "email_error": email_error,
            "employee_model_used": employee_model_used,
            "confirm_method_tried": confirm_tried,
            "confirm_method_ran": confirm_ran,
            "forced_sequence": force_seq_info,
            "cybro_link_field_used": cybro_link_field_used,
        }
