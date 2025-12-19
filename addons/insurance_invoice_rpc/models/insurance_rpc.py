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

        company = self.env.company

        # ---- Partner ----
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "ilike", cust_email)], limit=1)
        if not partner:
            partner = Partner.create({
                "name": cust_name,
                "email": cust_email,
                "phone": customer.get("phone"),
                "mobile": customer.get("mobile"),
                "customer_rank": 1,
            })

        # ---- Employee ----
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
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
                raise UserError("Invalid policy.id")
        else:
            policy_name = policy.get("name")
            policy_rec = Policy.search([("name", "=", policy_name)], limit=1)
            if not policy_rec:
                raise UserError(f"Policy not found: {policy_name}")

        # ---- Currency ----
        currency = self.env["res.currency"].sudo().search(
            [("name", "=", payload.get("currency") or "AUD")], limit=1
        )
        if not currency:
            raise UserError("Currency not found")

        # ---- CREATE INSURANCE ----
        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp_rec.id,
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "currency_id": currency.id,
            "policy_number": int(payload.get("policy_number") or 0),
            "name": payload.get("name") or f"{partner.name} - {policy_rec.name}",
            "payment_type": payload.get("payment_type") or "fixed",
            "start_date": payload.get("start_date") or fields.Date.context_today(self),

            # 🔥 FORCE CONFIRMED → UI VISIBILITY
            "state": "confirmed",
        }

        insurance = self.sudo().create(insurance_vals)

        # ---- Product ----
        Product = self.env["product.product"].sudo()
        product = Product.search([
            ("sale_ok", "=", True),
            "|", ("company_id", "=", False), ("company_id", "=", company.id)
        ], limit=1)

        if not product:
            product = Product.create({
                "name": "Insurance Service",
                "type": "service",
                "sale_ok": True,
                "company_id": company.id,
            })

        # ---- Journal ----
        journal = self.env["account.journal"].sudo().search(
            [("type", "=", "sale"), ("company_id", "=", company.id)], limit=1
        )
        if not journal:
            raise UserError("No Sales Journal found")

        # ---- Invoice ----
        move = self.env["account.move"].sudo().with_company(company).create({
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "invoice_user_id": self.env.user.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": f"Insurance: {insurance.name}",
                "quantity": float(inv.get("qty") or 1.0),
                "price_unit": float(inv.get("price_unit") or 0.0),
            })],
        })

        move.action_post()

        # 🔥 LINK INVOICE TO INSURANCE (UI + SMART BUTTONS)
        insurance.write({
            "invoice_ids": [(4, move.id)]
        })

        # ---- Email (unchanged) ----
        emailed = False
        email_error = None
        try:
            report = self.env["ir.actions.report"].sudo().search(
                [("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")],
                limit=1
            )
            ext = report.get_external_id()
            report_ref = ext.get(report.id)
            pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(
                report_ref, res_ids=[move.id]
            )

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
                "body_html": f"<p>Hello {partner.name},</p>",
                "attachment_ids": [(4, attachment.id)],
            })
            mail.send()
            emailed = True
        except Exception as e:
            email_error = str(e)

        return {
            "insurance_id": insurance.id,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "emailed": emailed,
            "email_error": email_error,
        }
