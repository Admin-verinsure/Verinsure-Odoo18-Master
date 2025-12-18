# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models
from odoo.exceptions import UserError

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload):
        """Create/Update partner + employee, create insurance.details, create+post invoice, email PDF.

        Call via XML-RPC: model='insurance.details', method='rpc_create_insurance_invoice_and_email', args=[payload_dict]
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

        # 1) Partner: match by email
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "=", cust_email)], limit=1)
        partner_vals = {
            "name": cust_name,
            "email": cust_email,
            "phone": customer.get("phone") or False,
            "mobile": customer.get("mobile") or False,
            "vat": customer.get("gst") or False,
            "customer_rank": 1,
        }
        if partner:
            # don't overwrite with empty
            write_vals = {k: v for k, v in partner_vals.items() if v not in (None, False, "")}
            partner.write(write_vals)
        else:
            partner = Partner.create(partner_vals)

        # 2) Employee: prefer employee.details, fallback hr.employee
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        EmpDetails = self.env["employee.details"].sudo()
        emp = EmpDetails.search([("name", "=", emp_name)], limit=1)
        if not emp:
            emp = EmpDetails.create({"name": emp_name})

        # 3) Policy: use policy.id or policy.name against policy.details
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

        # 4) Currency by code (e.g., AUD). Fallback to company currency.
        currency_code = (payload.get("currency") or "").strip()
        currency = None
        if currency_code:
            currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            currency = self.env.company.currency_id
        if not currency:
            raise UserError("Currency not found and company currency missing")

        # 5) Insurance required NOT NULL fields
        policy_number = payload.get("policy_number")
        if policy_number in (None, "", False):
            policy_number = 0

        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp.id,
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "currency_id": currency.id,
            "policy_number": int(policy_number),
            "name": payload.get("name") or f"{partner.name} - {policy_rec.name}",
            "payment_type": payload.get("payment_type") or "fixed",
            "state": payload.get("state") or "draft",
            "start_date": payload.get("start_date") or fields.Date.context_today(self),
        }

        insurance = self.sudo().create(insurance_vals)

        # 6) Invoice
        journal = self.env["account.journal"].sudo().search([
            ("type", "=", "sale"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError("No Sales Journal found.")

        product_id = inv.get("product_id")
        if product_id:
            product = self.env["product.product"].sudo().browse(int(product_id))
        else:
            product = self.env["product.product"].sudo().search([("sale_ok", "=", True)], limit=1)
        if not product or not product.exists():
            raise UserError("No valid product found for invoice line.")

        qty = float(inv.get("qty") or 1.0)
        price_unit = float(inv.get("price_unit") or 0.0)

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

        # 7) Render PDF + email
        # Try standard invoice report; if not found, fallback to any account.move qweb-pdf report.
        report = self.env.ref("account.account_invoices", raise_if_not_found=False)
        if not report:
            report = self.env["ir.actions.report"].sudo().search([
                ("model", "=", "account.move"),
                ("report_type", "=", "qweb-pdf"),
            ], limit=1)
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

        # Use mail.mail directly; if outgoing server missing, this will queue/fail.
        mail_vals = {
            "subject": f"Invoice {move.name}",
            "email_to": cust_email,
            "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
            "attachment_ids": [(4, attachment.id)],
        }
        mail = self.env["mail.mail"].sudo().create(mail_vals)

        emailed = True
        email_error = ""
        try:
            mail.send()
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
        }
