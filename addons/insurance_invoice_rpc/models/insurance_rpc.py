# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
import base64

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    def _cybro_confirm_insurance(self, insurance):
        """Try common confirm methods used by custom modules. Return True if a method ran."""
        for method in ("action_confirm", "button_confirm", "confirm", "action_validate"):
            if hasattr(insurance, method):
                try:
                    getattr(insurance, method)()
                    return True
                except Exception:
                    continue
        return False

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

        # Partner
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "ilike", cust_email)], limit=1)
        if not partner:
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
            vals = {}
            if cust_name and partner.name != cust_name:
                vals["name"] = cust_name
            if customer.get("phone") and partner.phone != customer.get("phone"):
                vals["phone"] = customer.get("phone")
            if customer.get("mobile") and partner.mobile != customer.get("mobile"):
                vals["mobile"] = customer.get("mobile")
            if vals:
                partner.write(vals)

        # Employee
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        employee_model_used = None
        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1) or Emp.create({"name": emp_name})
            employee_model_used = "employee.details"
        elif "hr.employee" in self.env:
            Emp = self.env["hr.employee"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1) or Emp.create({"name": emp_name})
            employee_model_used = "hr.employee"
        else:
            raise UserError("No employee model found (employee.details/hr.employee).")

        # Policy
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

        # Currency
        currency_code = (payload.get("currency") or "AUD").strip()
        currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            raise UserError(f"Currency not found: {currency_code}")

        # Insurance: create in draft so Cybro confirm assigns INS/xxx
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

        # Confirm using workflow
        if target_state in ("confirmed", "confirm", "validated", "posted"):
            ran = self._cybro_confirm_insurance(insurance)
            if not ran and "state" in insurance._fields:
                insurance.write({"state": "confirmed"})

        insurance_name = insurance.name  # should now be INS/xxx if workflow ran

        # Product (company-safe)
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
            product = Product.create({
                "name": "Insurance Service",
                "type": "service",
                "sale_ok": True,
                "purchase_ok": False,
                "company_id": company.id,
            })

        journal = self.env["account.journal"].sudo().search([("type", "=", "sale"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            raise UserError("No Sales Journal found for this company.")

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)

        move = self.env["account.move"].sudo().with_company(company).create({
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "invoice_user_id": self.env.user.id,
            "invoice_origin": insurance_name,   # Cybro Invoices tab uses this
            "ref": insurance_name,
            "insurance_details_id": insurance.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": inv.get("line_name") or f"Insurance: {insurance_name}",
                "quantity": qty,
                "price_unit": price_unit,
            })],
        })
        move.action_post()

        # PDF + email
        emailed = False
        email_error = None
        try:
            report = self.env["ir.actions.report"].sudo().search(
                [("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")],
                limit=1
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
        }
