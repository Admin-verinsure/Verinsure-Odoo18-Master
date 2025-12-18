# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models
from odoo.exceptions import UserError

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload: dict):
        """Create/Update customer+employee, create insurance.details, create+post invoice, email PDF.

        Expected payload (minimum):
        {
          "customer": {"name": "...", "email": "..."},
          "employee": {"name": "..."},
          "policy": {"id": 1},
          "policy_number": 100200,
          "policy_duration": 12,
          "payment_type": "fixed",
          "currency": "AUD",
          "invoice": {"price_unit": 1000.0, "qty": 1, "line_name": "Insurance Premium"}
        }
        """

        payload = payload or {}
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

        # Company context
        company = self.env.company

        # 1) Partner
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("email", "=", cust_email)], limit=1)
        partner_vals = {
            "name": cust_name,
            "email": cust_email,
            "phone": customer.get("phone"),
            "mobile": customer.get("mobile"),
            "vat": customer.get("gst"),
            "customer_rank": 1,
        }
        if partner:
            # keep existing values when payload is empty
            partner.write({k: v for k, v in partner_vals.items() if v})
        else:
            partner = Partner.create(partner_vals)

        # 2) Employee
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")
        Employee = self.env["employee.details"].sudo()
        emp_rec = Employee.search([("name", "=", emp_name)], limit=1)
        if not emp_rec:
            # fallback to hr.employee if employee.details is not meant to be created
            try:
                HrEmp = self.env["hr.employee"].sudo()
                hr_emp = HrEmp.search([("name", "=", emp_name)], limit=1)
                if hr_emp:
                    # If you need mapping between hr.employee and employee.details in your custom module,
                    # adjust this. For now, create employee.details.
                    pass
            except Exception:
                pass
            emp_rec = Employee.create({"name": emp_name})

        # 3) Policy
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
                raise UserError(f"Policy not found by name: {policy_name}")

        # 4) Currency
        currency_code = (payload.get("currency") or "").strip() or company.currency_id.name
        currency = self.env["res.currency"].sudo().search([("name", "=", currency_code)], limit=1)
        if not currency:
            raise UserError(f"Currency not found: {currency_code}")

        # 5) Create insurance.details (fulfill NOT NULL columns)
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

        # 6) Create invoice (company-safe product selection)
        journal = self.env["account.journal"].sudo().search(
            [("type", "=", "sale"), ("company_id", "=", company.id)],
            limit=1,
        )
        if not journal:
            raise UserError("No Sales Journal found for current company.")

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)
        line_name = inv.get("line_name") or "Insurance Premium"

        Product = self.env["product.product"].sudo()

        product = None
        product_id = inv.get("product_id")
        if product_id:
            p = Product.browse(int(product_id))
            if p.exists():
                # Ensure company compatibility
                if not p.company_id or p.company_id.id == company.id:
                    product = p
                else:
                    raise UserError(
                        f"Product (id={p.id}) belongs to another company ({p.company_id.display_name})."
                    )

        if not product:
            # Prefer shared products (company_id is False) or products in current company
            product = Product.search(
                [("sale_ok", "=", True), "|", ("company_id", "=", False), ("company_id", "=", company.id)],
                limit=1,
            )

        if not product:
            # Create a safe service product in current company
            uom_unit = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
            product = Product.create({
                "name": "Insurance Service",
                "type": "service",
                "sale_ok": True,
                "purchase_ok": False,
                "company_id": company.id,
                "uom_id": uom_unit.id if uom_unit else False,
                "uom_po_id": uom_unit.id if uom_unit else False,
            })

        move = self.env["account.move"].sudo().create({
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "currency_id": currency.id,
            "company_id": company.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "insurance_details_id": insurance.id,
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": line_name,
                "quantity": qty,
                "price_unit": price_unit,
            })],
        })

        # Post invoice
        move.action_post()

        emailed = False
        email_error = None

        # 7) Render PDF + email
        try:
            report = self.env.ref("account.account_invoices", raise_if_not_found=False)
            if not report:
                report = self.env["ir.actions.report"].sudo().search(
                    [("model", "=", "account.move"), ("report_type", "=", "qweb-pdf")],
                    limit=1,
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

            mail = self.env["mail.mail"].sudo().create({
                "subject": f"Invoice {move.name}",
                "email_to": cust_email,
                "body_html": f"<p>Hello {partner.name},</p><p>Please find your invoice attached.</p>",
                "attachment_ids": [(4, attachment.id)],
            })
            mail.send()
            emailed = True
        except Exception as e:
            # Do not fail the whole transaction if email isn't configured
            email_error = str(e)

        return {
            "insurance_id": insurance.id,
            "invoice_id": move.id,
            "invoice_name": move.name,
            "emailed_to": cust_email,
            "emailed": emailed,
            "email_error": email_error,
        }
