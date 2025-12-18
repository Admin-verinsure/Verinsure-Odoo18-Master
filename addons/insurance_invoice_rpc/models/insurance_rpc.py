# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

class InsuranceDetailsRPC(models.Model):
    _inherit = "insurance.details"

    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload):
        payload = payload or {}
        customer = (payload.get("customer") or {})
        employee = (payload.get("employee") or {})
        policy = (payload.get("policy") or {})
        inv = (payload.get("invoice") or {})

        # ---- Customer ----
        cust_name = (customer.get("name") or "").strip()
        cust_email = (customer.get("email") or "").strip()

        if not cust_name:
            raise UserError("Payload missing customer.name")
        if not cust_email:
            raise UserError("Payload missing customer.email")

        email_norm = cust_email.strip().lower()

        Partner = self.env["res.partner"].sudo()
        # Try to find by email (case-insensitive)
        partner = Partner.search([("email", "=ilike", email_norm)], limit=1)
        if not partner:
            # Some systems store emails with spaces/case; fallback to ilike contains
            partner = Partner.search([("email", "ilike", email_norm)], limit=1)

        if partner:
            # IMPORTANT: do NOT write email (your duplicate email module can raise even on no-op writes)
            write_vals = {
                "name": cust_name or partner.name,
            }
            if customer.get("phone"):
                write_vals["phone"] = customer.get("phone")
            if customer.get("mobile"):
                write_vals["mobile"] = customer.get("mobile")
            if customer.get("gst"):
                write_vals["vat"] = customer.get("gst")
            # Only write if something actually changes
            if any(partner[field] != val for field, val in write_vals.items() if field in partner._fields):
                partner.write(write_vals)
        else:
            # Create partner. If duplicate email validation triggers, fallback to re-search and use that partner.
            try:
                partner = Partner.create({
                    "name": cust_name,
                    "email": email_norm,
                    "phone": customer.get("phone"),
                    "mobile": customer.get("mobile"),
                    "vat": customer.get("gst"),
                    "customer_rank": 1,
                })
            except ValidationError:
                partner = Partner.search([("email", "=ilike", email_norm)], limit=1)
                if not partner:
                    partner = Partner.search([("email", "ilike", email_norm)], limit=1)
                if not partner:
                    raise

        # ---- Employee ----
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        emp_rec = None
        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                emp_rec = Emp.create({"name": emp_name})
        else:
            Emp = self.env["hr.employee"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                emp_rec = Emp.create({"name": emp_name})

        # ---- Policy ----
        Policy = self.env["policy.details"].sudo()
        policy_id = policy.get("id")
        if policy_id:
            policy_rec = Policy.browse(int(policy_id))
            if not policy_rec.exists():
                raise UserError(f"Invalid policy.id: {policy_id}")
        else:
            policy_name = (policy.get("name") or "").strip()
            if not policy_name:
                raise UserError("Payload missing policy.id or policy.name")
            policy_rec = Policy.search([("name", "=", policy_name)], limit=1)
            if not policy_rec:
                raise UserError(f"Policy not found: {policy_name}")

        # ---- Currency ----
        currency_code = (payload.get("currency") or "AUD").strip()
        currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            raise UserError(f"Currency not found: {currency_code}")

        # ---- Create insurance.details ----
        start_date = payload.get("start_date") or fields.Date.context_today(self)
        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp_rec.id,
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "currency_id": currency.id,
            "policy_number": int(payload.get("policy_number") or 0),
            "name": payload.get("name") or f"{partner.name} - {policy_rec.name}",
            "payment_type": payload.get("payment_type") or "fixed",
            "state": payload.get("state") or "draft",
            "start_date": start_date,
        }
        insurance = self.sudo().create(insurance_vals)

        # ---- Create invoice ----
        company = self.env.company
        journal = self.env["account.journal"].sudo().search([("type", "=", "sale"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            raise UserError("No Sales Journal found for current company.")

        Product = self.env["product.product"].sudo()
        product = None
        product_id = inv.get("product_id")
        if product_id:
            product = Product.browse(int(product_id))
            if not product.exists():
                raise UserError("invoice.product_id not found")
            if product.company_id and product.company_id.id != company.id:
                raise UserError("invoice.product_id belongs to another company")
        else:
            product = Product.search([
                ("sale_ok", "=", True),
                "|", ("company_id", "=", False), ("company_id", "=", company.id)
            ], limit=1)

        if not product:
            # create safe service product in this company
            product = Product.create({
                "name": "Insurance Service",
                "type": "service",
                "sale_ok": True,
                "purchase_ok": False,
                "company_id": company.id,
            })

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)

        move = self.env["account.move"].sudo().create({
            "move_type": "out_invoice",
            "company_id": company.id,
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

        # ---- Render PDF ----
        report = self.env.ref("account.account_invoices", raise_if_not_found=False)
        if not report:
            report = self.env["ir.actions.report"].sudo().search([("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")], limit=1)
        if not report:
            raise UserError("Invoice PDF report not found.")

        pdf_content, _ = report._render_qweb_pdf([move.id])
        attachment = self.env["ir.attachment"].sudo().create({
            "name": f"{move.name}.pdf",
            "type": "binary",
            "datas": base64.b64encode(pdf_content),
            "res_model": "account.move",
            "res_id": move.id,
            "mimetype": "application/pdf",
        })

        emailed = True
        email_error = None
        try:
            mail = self.env["mail.mail"].sudo().create({
                "subject": f"Invoice {move.name}",
                "email_to": email_norm,
                "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
                "attachment_ids": [(4, attachment.id)],
            })
            mail.send()
        except Exception as e:
            emailed = False
            email_error = str(e)

        return {
            "insurance_id": insurance.id,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "emailed_to": email_norm,
            "emailed": emailed,
            "email_error": email_error,
        }
