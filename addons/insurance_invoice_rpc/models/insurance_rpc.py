# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
import base64

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    def _try_confirm_and_sequence(self, insurance):
        """Confirm through Cybro workflow (if available) so sequence is assigned."""
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
        """If insurance.name is still '/', try to assign a sequence with prefix INS (best-effort)."""
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
                    return {"forced_sequence": True, "sequence_id": seq.id, "sequence_name": seq.name, "new_name": nxt}
        return {"forced_sequence": False}

    def _set_cybro_invoice_link_fields(self, move_vals, insurance):
        """Cybro insurance.details has invoice_ids (one2many). Set its inverse field on account.move if present."""
        move_fields = self.env["account.move"]._fields

        # Always set our explicit link (useful for reporting)
        move_vals["insurance_details_id"] = insurance.id

        # Cybro inverse M2O is typically insurance_id
        candidates = ["insurance_id", "insurance_detail_id", "insurance_claim_id"]
        for fname in candidates:
            if fname in move_fields:
                f = move_fields[fname]
                if getattr(f, "comodel_name", None) == "insurance.details":
                    move_vals[fname] = insurance.id
                    move_vals["_cybro_link_field_used"] = fname
                    break
        return move_vals

    def _get_or_create_agent(self, emp_name: str):
        """Create agent if missing, and ensure it's linked to current user if a user_id field exists.
        Fixes Cybro visibility rules for newly created agents.
        """
        employee_model_used = None

        def ensure_user_link(rec, Model):
            if "user_id" in Model._fields:
                try:
                    if not rec.user_id:
                        rec.write({"user_id": self.env.user.id})
                        return True
                except Exception:
                    return False
            return False

        if "employee.details" in self.env:
            Emp = self.env["employee.details"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                vals = {"name": emp_name}
                if "user_id" in Emp._fields:
                    vals["user_id"] = self.env.user.id
                emp_rec = Emp.create(vals)
            else:
                ensure_user_link(emp_rec, Emp)
            employee_model_used = "employee.details"
            return emp_rec, employee_model_used

        if "hr.employee" in self.env:
            Emp = self.env["hr.employee"].sudo()
            emp_rec = Emp.search([("name", "=", emp_name)], limit=1)
            if not emp_rec:
                vals = {"name": emp_name}
                if "user_id" in Emp._fields:
                    vals["user_id"] = self.env.user.id
                emp_rec = Emp.create(vals)
            else:
                ensure_user_link(emp_rec, Emp)
            employee_model_used = "hr.employee"
            return emp_rec, employee_model_used

        raise UserError("No employee model found (employee.details/hr.employee).")

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
                partner = Partner.create({"name": cust_name, "email": cust_email, "customer_rank": 1})
            except Exception:
                partner = Partner.search([("email", "ilike", cust_email)], limit=1)
                if not partner:
                    raise
        else:
            if cust_name and partner.name != cust_name:
                partner.write({"name": cust_name})

        # Agent (create if missing + link to current user if possible)
        emp_name = (employee.get("name") or "").strip()
        if not emp_name:
            raise UserError("Payload missing employee.name")
        emp_rec, employee_model_used = self._get_or_create_agent(emp_name)

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

        # Insurance in draft (let workflow set sequence)
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

        # Product (company-safe)
        Product = self.env["product.product"].sudo()
        product = Product.search([("sale_ok", "=", True), "|", ("company_id", "=", False), ("company_id", "=", company.id)], limit=1)
        if not product:
            product = Product.create({"name": "Insurance Service", "type": "service", "sale_ok": True, "company_id": company.id})

        journal = self.env["account.journal"].sudo().search([("type", "=", "sale"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            raise UserError("No Sales Journal found for this company.")

        price_unit = float(inv.get("price_unit") or 0.0)
        qty = float(inv.get("qty") or 1.0)

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
            "invoice_line_ids": [(0, 0, {
                "product_id": product.id,
                "name": inv.get("line_name") or f"Insurance: {insurance_name}",
                "quantity": qty,
                "price_unit": price_unit,
            })],
        }
        move_vals = self._set_cybro_invoice_link_fields(move_vals, insurance)
        cybro_link_field_used = move_vals.pop("_cybro_link_field_used", None)

        move = self.env["account.move"].sudo().with_company(company).create(move_vals)
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
            "confirm_method_tried": confirm_tried,
            "confirm_method_ran": confirm_ran,
            "forced_sequence": force_seq_info,
            "cybro_link_field_used": cybro_link_field_used,
        }
