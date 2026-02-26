# -*- coding: utf-8 -*-
import json
import re
from odoo import fields, models, _
from odoo.exceptions import ValidationError

PHONE_RE = re.compile(r"^\d+$")


class InvoicePocPayload(models.Model):
    _name = "invoice.poc.payload"
    _description = "Invoice POC Payload"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    ext_id = fields.Char(required=True, index=True, tracking=True)
    payload_json = fields.Text(required=True)
    last_move_id = fields.Many2one("account.move", readonly=True, tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done"), ("error", "Error")],
        default="draft",
        tracking=True,
    )
    error_message = fields.Text(readonly=True)

    _sql_constraints = [
        ("ext_id_uniq", "unique(ext_id)", "ext_id must be unique."),
    ]

    # -----------------------------
    # Load + validation
    # -----------------------------
    def _load_payload(self):
        self.ensure_one()
        try:
            return json.loads(self.payload_json or "{}")
        except Exception as e:
            raise ValidationError(_("Invalid JSON in payload_json: %s") % str(e))

    def _validate_phone(self, phone, label):
        if phone and not PHONE_RE.match(phone):
            raise ValidationError(_("%s phone must be exactly 10 digits. Got: %s") % (label, phone))

    # -----------------------------
    # Lookups
    # -----------------------------
    def _get_currency(self, code):
        if not code:
            return self.env.company.currency_id
        cur = self.env["res.currency"].search([("name", "=", code)], limit=1)
        return cur or self.env.company.currency_id

    def _get_salesperson(self, login):
        login = (login or "").strip()
        if not login:
            return self.env.user
        user = self.env["res.users"].sudo().search([("login", "=", login)], limit=1)
        return user or self.env.user

    def _get_tax_ids_by_names(self, tax_names, company):
        if not tax_names:
            return []
        tax_ids = []
        for name in tax_names:
            tax = self.env["account.tax"].search(
                [("name", "=", name), ("company_id", "=", company.id)],
                limit=1,
            )
            if not tax:
                raise ValidationError(_("Tax not found by name: %s") % name)
            tax_ids.append(tax.id)
        return tax_ids

    # -----------------------------
    # Customer
    # -----------------------------
    def _get_or_create_partner(self, customer):
        name = (customer.get("name") or "").strip()
        email = (customer.get("email") or "").strip().lower()
        phone = (customer.get("phone") or "").strip()

        if not name:
            raise ValidationError(_("customer.name is required"))
        if not email:
            raise ValidationError(_("customer.email is required"))
        self._validate_phone(phone, "Customer")

        partner = self.env["res.partner"].search([("email", "=", email)], limit=1)
        if partner:
            vals = {}
            if name and not partner.name:
                vals["name"] = name
            if phone and not partner.phone:
                vals["phone"] = phone
            if vals:
                partner.write(vals)
            return partner

        return self.env["res.partner"].create({
            "name": name,
            "email": email,
            "phone": phone,
            "customer_rank": 1,
        })

    # -----------------------------
    # Agent (employee.details) - SEARCH BY NAME, NO EMAIL
    # -----------------------------
    def _get_or_create_employee_details(self, agent):
        """employee.details has NO email field.

        Requirement:
          1) Search agent by name first (exact match)
          2) If not found, create
          3) Phone optional (validate & store if provided)
          4) If multiple with same name, prefer matching phone (if phone provided)
        """
        name = (agent.get("name") or "").strip()
        phone = (agent.get("phone") or "").strip()

        if not name:
            raise ValidationError(_("policy.agent.name is required"))

        # validate phone only if provided
        self._validate_phone(phone, "Agent")

        Emp = self.env["employee.details"]

        rec = False
        if phone:
            rec = Emp.search([("name", "=", name), ("phone", "=", phone)], limit=1)

        if not rec:
            rec = Emp.search([("name", "=", name)], limit=1)

        if rec:
            vals = {}
            if phone and not rec.phone:
                vals["phone"] = phone
            if vals:
                rec.write(vals)
            return rec

        vals = {"name": name}
        if phone:
            vals["phone"] = phone
        return Emp.create(vals)

    # -----------------------------
    # Policy Type / Policy / Insurance
    # -----------------------------
    def _get_policy_type(self, type_name):
        """Option B: auto-create policy.type if missing."""
        if not type_name:
            return False

        pt = self.env["policy.type"].search([("name", "=", type_name)], limit=1)
        if pt:
            return pt

        # Auto-create if missing
        return self.env["policy.type"].create({"name": type_name})

    def _create_policy(self, policy_data, currency):
        pt = self._get_policy_type(policy_data.get("type_name"))

        vals = {
            "name": policy_data.get("name") or _("Policy"),
            "amount": policy_data.get("amount") or 0.0,
            "currency_id": currency.id,
        }
        if pt:
            vals["policy_type_id"] = pt.id

        return self.env["policy.details"].create(vals)

    def _validate_insurance_payment_type(self, payment_type_value):
        field = self.env["insurance.details"]._fields.get("payment_type")
        if not field:
            return False
        selection = field.selection or []
        allowed = {k for (k, _label) in selection}
        if not payment_type_value:
            return False
        if payment_type_value not in allowed:
            raise ValidationError(
                _("Invalid payment_type '%s'. Allowed: %s")
                % (payment_type_value, ", ".join(sorted(allowed)))
            )
        return payment_type_value

    def _create_insurance(self, payload, policy, partner, employee, currency):
        policy_data = payload.get("policy") or {}

        policy_number = policy_data.get("policy_number")
        if policy_number is None:
            raise ValidationError(_("policy.policy_number is required"))

        payment_type = self._validate_insurance_payment_type(policy_data.get("payment_type"))
        if not payment_type:
            raise ValidationError(_("policy.payment_type is required"))

        # REQUIRED fields in your DB: start_date, amount_installment, state
        start_date = payload.get("invoice_date") or fields.Date.today()

        # Use total invoice lines as default installment amount, fallback to policy amount
        lines = payload.get("lines") or []
        total_lines = 0.0
        for l in lines:
            total_lines += float(l.get("qty") or 1) * float(l.get("unit_price") or 0)

        amount_installment = total_lines if total_lines > 0 else float(policy_data.get("amount") or 0.0)

        # NOTE: If your insurance.details.state selection keys differ,
        # change "draft" to a valid key. You can check via:
        # env["insurance.details"]._fields["state"].selection
        state = "draft"

        vals = {
            "name": policy_data.get("name") or _("Insurance"),
            "partner_id": partner.id,
            "employee_id": employee.id,
            "policy_id": policy.id,
            "policy_number": int(policy_number),
            "policy_duration": int(policy_data.get("policy_duration") or 0),
            "currency_id": currency.id,
            "payment_type": payment_type,
            "start_date": start_date,
            "amount_installment": float(amount_installment),
            "state": state,
            # amount is optional in your DB, but OK to set
            "amount": float(policy_data.get("amount") or 0.0),
        }

        return self.env["insurance.details"].create(vals)

    # -----------------------------
    # Invoice
    # -----------------------------
    def _create_invoice(self, payload, partner, salesperson, currency, insurance):
        Move = self.env["account.move"]

        move_vals = {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_user_id": salesperson.id,
            "currency_id": currency.id,
            "insurance_id": insurance.id,  # exists in your DB
        }

        if payload.get("invoice_date"):
            move_vals["invoice_date"] = payload["invoice_date"]
        if payload.get("due_date"):
            move_vals["invoice_date_due"] = payload["due_date"]

        if payload.get("payment_term"):
            term = self.env["account.payment.term"].search([("name", "=", payload["payment_term"])], limit=1)
            if not term:
                raise ValidationError(_("Payment term not found by name: %s") % payload["payment_term"])
            move_vals["invoice_payment_term_id"] = term.id

        if payload.get("notes"):
            move_vals["narration"] = payload["notes"]

        move = Move.create(move_vals)

        lines = payload.get("lines") or []
        if not lines:
            raise ValidationError(_("Invoice lines are required"))

        cmd = []
        for l in lines:
            
            product_guid = (l.get("product_guid") or "").strip()
            if not product_guid:
                raise ValidationError("Missing product_guid in invoice line")
            
            template = self.env["product.template"].sudo().search(
                [("x_external_guid", "=", product_guid)],
                limit=1,
            )
            if not template:
                raise ValidationError(
                    _("Product not found for GUID: %s") % product_guid
                )
            
            product = template.product_variant_id
            if not product:
                raise ValidationError(
                    _("No product variant found for template with GUID: %s") % product_guid
                )
            qty = float(l.get("qty") or 1.0)
            
            cmd.append((0, 0, {
                "product_id": product.id,
                "name": product.name,
                "quantity": qty,
                "quantity": float(l.get("qty") or 1.0),
                "price_unit": float(l.get("unit_price") or 0.0),  # 🔥 Odoo-side taxes
            }))
              
        move.write({"invoice_line_ids": cmd})
        # move._recompute_dynamic_lines(recompute_all_taxes=True)          
    
        return move

    def _post_and_email(self, move):
        move.action_post()

        template = False
        try:
            template = self.env.ref("insurance_invoice_rpc.mail_template_invoice_poc", raise_if_not_found=False)
        except Exception:
            template = False

        if not template:
            template = self.env["mail.template"].search([("name", "=", "Insurance Invoice - Customer Email")], limit=1)

        if template and move.partner_id.email:
            template.send_mail(move.id, force_send=True)

    # -----------------------------
    # Public entry
    # -----------------------------
    def action_create_policy_and_invoice(self):
        for rec in self:
            try:
                payload = rec._load_payload()

                partner = rec._get_or_create_partner(payload.get("customer") or {})
                salesperson = rec._get_salesperson((payload.get("salesperson") or {}).get("login"))
                currency = rec._get_currency(payload.get("currency"))

                policy_data = payload.get("policy") or {}
                employee = rec._get_or_create_employee_details(policy_data.get("agent") or {})

                policy = rec._create_policy(policy_data, currency)
                insurance = rec._create_insurance(payload, policy, partner, employee, currency)

                move = rec._create_invoice(payload, partner, salesperson, currency, insurance)
                rec._post_and_email(move)

                rec.last_move_id = move.id
                rec.state = "done"
                rec.error_message = False
                return move

            except Exception as e:
                rec.state = "error"
                rec.error_message = str(e)
                raise
