# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models
from odoo.exceptions import UserError

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    @api.model
    def _rpc_pick_company_safe_product(self, company, line_name):
        Product = self.env["product.product"].sudo().with_company(company)
        product = Product.search([
            ("sale_ok", "=", True),
            "|", ("company_id", "=", False), ("company_id", "=", company.id),
        ], limit=1)
        if product:
            return product

        # Create safe service product
        tmpl = self.env["product.template"].sudo().with_company(company).create({
            "name": line_name or "Insurance Service",
            "type": "service",
            "sale_ok": True,
            "purchase_ok": False,
            "company_id": company.id,
        })
        return tmpl.product_variant_id

    @api.model
    def _rpc_find_or_create_partner(self, customer):
        Partner = self.env["res.partner"].sudo()
        email = (customer.get("email") or "").strip()
        name = (customer.get("name") or "").strip() or email or "Customer"
        if not email:
            raise UserError("Payload missing customer.email")

        # Case-insensitive match
        partner = Partner.search([("email", "=ilike", email)], limit=1)
        if partner:
            # Don't write email again (your duplicate_email module may block writes)
            vals = {}
            if name and partner.name != name:
                vals["name"] = name
            phone = customer.get("phone")
            if phone and partner.phone != phone:
                vals["phone"] = phone
            mobile = customer.get("mobile")
            if mobile and partner.mobile != mobile:
                vals["mobile"] = mobile
            gst = customer.get("gst") or customer.get("vat")
            if gst and partner.vat != gst:
                vals["vat"] = gst
            if vals:
                partner.write(vals)
            if partner.customer_rank < 1:
                partner.write({"customer_rank": 1})
            return partner

        # Create new partner
        try:
            return Partner.create({
                "name": name,
                "email": email,
                "phone": customer.get("phone"),
                "mobile": customer.get("mobile"),
                "vat": customer.get("gst") or customer.get("vat"),
                "customer_rank": 1,
            })
        except Exception:
            # In case custom validation blocks due to duplicates, re-search and reuse
            partner = Partner.search([("email", "=ilike", email)], limit=1)
            if partner:
                return partner
            raise

    @api.model
    def _rpc_find_or_create_employee(self, employee):
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")

        # Prefer employee_details table (your custom)
        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            rec = Emp.search([("name", "=", emp_name)], limit=1)
            if rec:
                return rec, "employee.details"
            return Emp.create({"name": emp_name}), "employee.details"

        # Fallback hr.employee
        Emp = self.env["hr.employee"].sudo()
        rec = Emp.search([("name", "=", emp_name)], limit=1)
        if rec:
            return rec, "hr.employee"
        return Emp.create({"name": emp_name}), "hr.employee"

    @api.model
    def _rpc_get_policy(self, policy):
        Policy = self.env["policy.details"].sudo()
        pol_id = policy.get("id")
        if pol_id:
            rec = Policy.browse(int(pol_id))
            if not rec.exists():
                raise UserError(f"Invalid policy.id: {pol_id}")
            return rec
        name = (policy.get("name") or "").strip()
        if not name:
            raise UserError("Payload missing policy.id or policy.name")
        rec = Policy.search([("name", "=", name)], limit=1)
        if not rec:
            raise UserError(f"Policy not found: {name}")
        return rec

    @api.model
    def _rpc_get_currency(self, code):
        code = (code or "AUD").strip()
        cur = self.env["res.currency"].sudo().search([("name", "=", code)], limit=1)
        if not cur:
            raise UserError(f"Currency not found: {code}")
        return cur

    @api.model
    def _rpc_get_invoice_report(self):
        # Try common invoice report xmlids across versions/localizations
        xmlids = [
            "account.account_invoices",     # older
            "account.report_invoice",       # common report action
            "account.account_invoices_without_payment",  # sometimes exists
        ]
        for xid in xmlids:
            rep = self.env.ref(xid, raise_if_not_found=False)
            if rep and rep._name == "ir.actions.report":
                return rep
        # fallback: any qweb-pdf report for account.move
        rep = self.env["ir.actions.report"].sudo().search([
            ("model", "=", "account.move"),
            ("report_type", "=", "qweb-pdf"),
        ], limit=1)
        return rep

    @api.model
    def rpc_create_insurance_invoice_and_email(self, payload):
        payload = payload or {}
        customer = payload.get("customer") or {}
        employee = payload.get("employee") or {}
        policy = payload.get("policy") or {}
        inv = payload.get("invoice") or {}

        partner = self._rpc_find_or_create_partner(customer)
        emp_rec, emp_model = self._rpc_find_or_create_employee(employee)
        policy_rec = self._rpc_get_policy(policy)
        currency = self._rpc_get_currency(payload.get("currency"))

        # Ensure NOT NULL required fields for insurance_details
        insurance_vals = {
            "partner_id": partner.id,
            "employee_id": emp_rec.id,  # your insurance_details column expects int; employee_details id matches
            "policy_id": policy_rec.id,
            "policy_duration": int(payload.get("policy_duration") or 12),
            "currency_id": currency.id,
            "policy_number": int(payload.get("policy_number") or 0),
            "name": payload.get("name") or f"{partner.name} - {policy_rec.name}",
            "payment_type": payload.get("payment_type") or "fixed",
            "state": payload.get("state") or "draft",
            "start_date": payload.get("start_date") or fields.Date.context_today(self),
        }

        insurance = self.sudo().create(insurance_vals)

        company = self.env.company
        journal = self.env["account.journal"].sudo().with_company(company).search([
            ("type", "=", "sale"),
            ("company_id", "=", company.id),
        ], limit=1)
        if not journal:
            raise UserError("No Sales Journal found for current company.")

        # product handling
        product_id = inv.get("product_id")
        line_name = inv.get("line_name") or "Insurance Premium"
        if product_id:
            product = self.env["product.product"].sudo().browse(int(product_id))
            if not product.exists():
                raise UserError(f"Invalid invoice.product_id: {product_id}")
            if product.company_id and product.company_id.id != company.id:
                raise UserError("Provided product_id belongs to another company.")
        else:
            product = self._rpc_pick_company_safe_product(company, line_name)

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)

        move = self.env["account.move"].sudo().with_company(company).create({
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
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

        move.action_post()

        emailed = False
        email_error = None
        try:
            report = self._rpc_get_invoice_report()
            if not report:
                raise UserError("Invoice PDF report not found.")
            # IMPORTANT: in Odoo 18 the signature expects report_ref if called on model.
            # Calling on record with keyword avoids confusion.
            pdf_content, _ = report._render_qweb_pdf(res_ids=[move.id])

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
                "email_to": partner.email,
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
            "invoice_id": move.id,
            "invoice_name": move.name,
            "emailed_to": partner.email,
            "emailed": emailed,
            "email_error": email_error,
            "employee_model_used": emp_model,
        }
