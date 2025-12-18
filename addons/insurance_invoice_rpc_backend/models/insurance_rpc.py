# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models
from odoo.exceptions import UserError

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload):
        """Create/Update customer + employee, create insurance.details, create+post invoice and email PDF.

        Expected payload keys (minimum):
          customer: {name, email, phone?}
          employee: {name, external_id?}
          policy: {id}  (or {name})
          policy_number: int
          policy_duration: int
          payment_type: str
          currency: str (e.g. AUD)
          invoice: {price_unit, qty, product_id?, line_name?}
        """
        if not isinstance(payload, dict):
            raise UserError("Payload must be a dict")

        customer = payload.get("customer") or {}
        employee = payload.get("employee") or {}
        policy = payload.get("policy") or {}
        inv = payload.get("invoice") or {}

        cust_name = (customer.get("name") or "").strip()
        cust_email = (customer.get("email") or "").strip()
        if not cust_name:
            raise UserError("Payload missing customer.name")
        if not cust_email:
            raise UserError("Payload missing customer.email")

        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "=", cust_email)], limit=1)
        vals_partner = {
            "name": cust_name,
            "email": cust_email,
            "phone": customer.get("phone") or False,
            "mobile": customer.get("mobile") or False,
            "vat": customer.get("gst") or False,
            "customer_rank": 1,
        }
        if not partner:
            partner = Partner.create(vals_partner)
        else:
            # update only provided fields
            update = {}
            for k, v in vals_partner.items():
                if v not in (None, False, ""):
                    update[k] = v
            if update:
                partner.write(update)

        # Employee: prefer employee.details, fallback hr.employee
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        emp_model = None
        EmpDetails = self.env.get("employee.details")
        if EmpDetails:
            emp_model = "employee.details"
            Emp = self.env[emp_model].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                emp_rec = Emp.create({"name": emp_name})
        else:
            emp_model = "hr.employee"
            Emp = self.env[emp_model].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                emp_rec = Emp.create({"name": emp_name})

        # Policy: policy_details table => model likely policy.details
        Policy = self.env.get("policy.details")
        if not Policy:
            raise UserError("Model policy.details not found. Ensure policy module from insurance_management_cybro is installed.")
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

        currency_code = (payload.get("currency") or "AUD").strip()
        currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            raise UserError(f"Currency not found: {currency_code}")

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

        journal = self.env["account.journal"].sudo().search(
            [("type", "=", "sale"), ("company_id", "=", self.env.company.id)],
            limit=1
        )
        if not journal:
            raise UserError("No Sales Journal found.")

        product_id = inv.get("product_id")
        if product_id:
            product = self.env["product.product"].sudo().browse(int(product_id))
        else:
            product = self.env["product.product"].sudo().search([("sale_ok", "=", True)], limit=1)
        if not product or not product.exists():
            raise UserError("No valid product found for invoice line.")

        price_unit = float(inv.get("price_unit") or 0.0)
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

        # Render PDF
        report = self.env.ref("account.account_invoices", raise_if_not_found=False)
        if not report:
            report = self.env["ir.actions.report"].sudo().search(
                [("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")],
                limit=1
            )
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

        # Email
        email_to = cust_email
        mail_vals = {
            "subject": f"Invoice {move.name}",
            "email_to": email_to,
            "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
            "attachment_ids": [(4, attachment.id)],
        }
        mailed = False
        email_error = False
        try:
            mail = self.env["mail.mail"].sudo().create(mail_vals)
            mail.send()
            mailed = True
        except Exception as e:
            email_error = str(e)

        return {
            "insurance_id": insurance.id,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "emailed_to": email_to,
            "emailed": mailed,
            "email_error": email_error,
        }
