# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models
from odoo.exceptions import UserError

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload):
        """Create Insurance + Invoice + Email from a JSON-like dict payload."""
        if not isinstance(payload, dict):
            raise UserError("Payload must be a dict (JSON object).")

        def _safe_get(d, key, default=None):
            return d.get(key, default) if isinstance(d, dict) else default

        customer = _safe_get(payload, "customer", {}) or {}
        employee = _safe_get(payload, "employee", {}) or {}
        policy = _safe_get(payload, "policy", {}) or {}
        inv = _safe_get(payload, "invoice", {}) or {}

        cust_name = (_safe_get(customer, "name", "") or "").strip()
        cust_email = (_safe_get(customer, "email", "") or "").strip()
        if not cust_name:
            raise UserError("Payload missing customer.name")
        if not cust_email:
            raise UserError("Payload missing customer.email")

        def _pick_selection(field_name, preferred):
            field = self._fields.get(field_name)
            if not field or not getattr(field, "selection", None):
                return preferred
            sel = field.selection(self.env) if callable(field.selection) else field.selection
            keys = [k for (k, _label) in sel]
            if preferred in keys:
                return preferred
            for cand in ("draft", "new", "open", "confirm", "confirmed"):
                if cand in keys:
                    return cand
            return keys[0] if keys else preferred

        # 1) Partner
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "=", cust_email)], limit=1)
        vals_partner = {
            "name": cust_name,
            "email": cust_email,
            "phone": _safe_get(customer, "phone"),
            "mobile": _safe_get(customer, "mobile"),
            "vat": _safe_get(customer, "gst") or _safe_get(customer, "vat"),
            "customer_rank": 1,
        }
        vals_partner = {k: v for k, v in vals_partner.items() if v not in (None, "", False)}
        if not partner:
            partner = Partner.create(vals_partner)
        else:
            partner.write(vals_partner)

        # 2) Employee
        emp_name = (_safe_get(employee, "name", "") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        EmployeeModel = self.env.get("employee.details") or self.env.get("hr.employee")
        if not EmployeeModel:
            raise UserError("Neither employee.details nor hr.employee exists.")

        emp_rec = EmployeeModel.sudo().search([("name", "=", emp_name)], limit=1)
        if not emp_rec:
            emp_rec = EmployeeModel.sudo().create({"name": emp_name})

        # 3) Policy
        PolicyModel = self.env.get("policy.details")
        if not PolicyModel:
            raise UserError("policy.details model not found.")

        policy_id = _safe_get(policy, "id")
        if policy_id:
            policy_rec = PolicyModel.sudo().browse(int(policy_id))
            if not policy_rec.exists():
                raise UserError(f"Invalid policy.id: {policy_id}")
        else:
            policy_name = (_safe_get(policy, "name", "") or "").strip()
            if not policy_name:
                raise UserError("Payload missing policy.id or policy.name")
            policy_rec = PolicyModel.sudo().search([("name", "=", policy_name)], limit=1)
            if not policy_rec:
                raise UserError(f"Policy not found by name: {policy_name}")

        # 4) Currency
        currency_code = (payload.get("currency") or "AUD").strip()
        currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            raise UserError(f"Currency not found: {currency_code}")

        # 5) Dates and selections
        start_date = payload.get("start_date") or fields.Date.context_today(self)
        payment_type = _pick_selection("payment_type", payload.get("payment_type") or "fixed")
        state = _pick_selection("state", payload.get("state") or "draft")

        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp_rec.id,
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "currency_id": currency.id,
            "policy_number": int(payload.get("policy_number") or 0),
            "name": payload.get("name") or f"{partner.name} - {policy_rec.name}",
            "payment_type": payment_type,
            "state": state,
            "start_date": start_date,
        }

        insurance = self.sudo().create(insurance_vals)

        # 6) Invoice
        journal = self.env["account.journal"].sudo().search([
            ("type", "=", "sale"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError("No Sales Journal found for the current company.")

        product_id = inv.get("product_id")
        if product_id:
            product = self.env["product.product"].sudo().browse(int(product_id))
        else:
            product = self.env["product.product"].sudo().search([("sale_ok", "=", True)], limit=1)

        if not product or not product.exists():
            raise UserError("No valid product found for invoice line. Provide invoice.product_id or create a sale product.")

        price_unit = float(inv.get("price_unit") or payload.get("amount") or 0.0)
        qty = float(inv.get("qty") or 1.0)

        move = self.env["account.move"].sudo().create({
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "currency_id": currency.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "insurance_details_id": insurance.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": inv.get("line_name") or f"Insurance: {insurance.name}",
                "quantity": qty,
                "price_unit": price_unit,
            })],
        })
        move.action_post()

        # 7) PDF
        report = self.env.ref("account.account_invoices", raise_if_not_found=False)
        if not report:
            report = self.env["ir.actions.report"].sudo().search([
                ("model", "=", "account.move"),
                ("report_type", "=", "qweb-pdf"),
                ("name", "ilike", "invoice"),
            ], limit=1)
        if not report:
            raise UserError("Invoice PDF report not found (ir.actions.report).")

        pdf_content, _ = report._render_qweb_pdf([move.id])

        attachment = self.env["ir.attachment"].sudo().create({
            "name": f"{move.name}.pdf",
            "type": "binary",
            "datas": base64.b64encode(pdf_content),
            "res_model": "account.move",
            "res_id": move.id,
            "mimetype": "application/pdf",
        })

        mailed = False
        mail_error = None
        try:
            with self.env.cr.savepoint():
                mail = self.env["mail.mail"].sudo().create({
                    "subject": f"Invoice {move.name}",
                    "email_to": cust_email,
                    "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
                    "attachment_ids": [(4, attachment.id)],
                })
                mail.send()
                mailed = True
        except Exception as e:
            mailed = False
            mail_error = str(e)

        return {
            "insurance_id": insurance.id,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "partner_id": partner.id,
            "partner_email": cust_email,
            "employee_id": emp_rec.id,
            "policy_id": policy_rec.id,
            "emailed": mailed,
            "email_error": mail_error,
        }
