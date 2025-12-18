# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
import base64

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload: dict):
        # ---- Validate payload ----
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

        # Company context (invoice is multi-company; insurance.details in your DB has no company_id field)
        company = self.env.company

        # ---- Partner: find by email (case-insensitive) or create ----
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "ilike", cust_email)], limit=1)
        if not partner:
            # create; some custom modules enforce unique email; if create fails, re-search and reuse
            try:
                partner = Partner.create({
                    "name": cust_name,
                    "email": cust_email,
                    "phone": customer.get("phone"),
                    "mobile": customer.get("mobile"),
                    "customer_rank": 1,
                })
            except Exception:
                partner = Partner.search([("email", "ilike", cust_email)], limit=1)
                if not partner:
                    raise
        else:
            # IMPORTANT: avoid writing email again (your duplicate_contact_details_alert blocks it)
            vals = {}
            if cust_name and partner.name != cust_name:
                vals["name"] = cust_name
            if customer.get("phone") and partner.phone != customer.get("phone"):
                vals["phone"] = customer.get("phone")
            if customer.get("mobile") and partner.mobile != customer.get("mobile"):
                vals["mobile"] = customer.get("mobile")
            if vals:
                partner.write(vals)

        # ---- Employee: prefer employee.details, fallback to hr.employee ----
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        employee_model_used = None
        Emp = None
        emp_rec = None
        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                emp_rec = Emp.create({"name": emp_name})
            employee_model_used = "employee.details"
        elif "hr.employee" in self.env:
            Emp = self.env["hr.employee"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                emp_rec = Emp.create({"name": emp_name})
            employee_model_used = "hr.employee"
        else:
            raise UserError("No employee model found (employee.details/hr.employee).")

        # ---- Policy: must exist ----
        if "policy.details" not in self.env:
            raise UserError("policy.details model not found.")
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

        # ---- Create insurance.details (your model has no company_id field) ----
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

        # ---- Choose a company-safe product ----
        Product = self.env["product.product"].sudo()
        product = None
        product_id = inv.get("product_id")
        if product_id:
            p = Product.browse(int(product_id))
            if p.exists() and (not p.company_id or p.company_id.id == company.id):
                product = p
            else:
                raise UserError("Provided product_id belongs to another company.")
        if not product:
            product = Product.search([("sale_ok", "=", True), "|", ("company_id", "=", False), ("company_id", "=", company.id)], limit=1)
        if not product:
            # Create a safe service product in this company
            product = Product.create({
                "name": "Insurance Service",
                "type": "service",
                "sale_ok": True,
                "purchase_ok": False,
                "company_id": company.id,
            })

        # ---- Sales journal ----
        journal = self.env["account.journal"].sudo().search([("type", "=", "sale"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            raise UserError("No Sales Journal found for this company.")

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)

        # Set salesperson to current RPC user to satisfy "My Invoices" filters if any
        invoice_user_id = self.env.user.id

        move = self.env["account.move"].sudo().with_company(company).create({
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "invoice_user_id": invoice_user_id,
            "insurance_details_id": insurance.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": inv.get("line_name") or f"Insurance: {insurance.name}",
                "quantity": qty,
                "price_unit": price_unit,
            })],
        })

        move.action_post()

        # ---- Render PDF + send mail (do not hard-fail if email/report missing) ----
        emailed = False
        email_error = None

        try:
            report = self.env["ir.actions.report"].sudo().search(
                [("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")],
                limit=1
            )
            if not report:
                raise UserError("No PDF report found for account.move.")

            # Get a report_ref xmlid string
            ext = report.get_external_id()
            report_ref = ext.get(report.id)
            if not report_ref:
                # fallback for non-xmlid reports
                raise UserError("Invoice report has no external id (xmlid).")

            # Your Odoo build expects: _render_qweb_pdf(report_ref, res_ids=...)
            pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(report_ref, res_ids=[move.id])

            attachment = self.env["ir.attachment"].sudo().create({
                "name": f"{move.name}.pdf",
                "type": "binary",
                "datas": base64.b64encode(pdf_content),
                "res_model": "account.move",
                "res_id": move.id,
                "mimetype": "application/pdf",
            })

            mail_vals = {
                "subject": f"Invoice {move.name}",
                "email_to": cust_email,
                "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
                "attachment_ids": [(4, attachment.id)],
            }
            mail = self.env["mail.mail"].sudo().create(mail_vals)
            mail.send()
            emailed = True
        except Exception as e:
            emailed = False
            email_error = str(e)

        return {
            "insurance_id": insurance.id,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "emailed_to": cust_email,
            "emailed": emailed,
            "email_error": email_error,
            "employee_model_used": employee_model_used,
        }
