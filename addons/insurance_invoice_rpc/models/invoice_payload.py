# -*- coding: utf-8 -*-
import itertools
import json
import re
from datetime import date, datetime
from odoo import fields, models, _
from odoo.exceptions import ValidationError




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

    # -------------------------------------------------------
    # Utilities
    # -------------------------------------------------------

    def _load_payload(self):
        self.ensure_one()
        try:
            return json.loads(self.payload_json or "{}")
        except Exception as e:
            raise ValidationError(_("Invalid JSON: %s") % str(e))

    def _validate_phone(self, phone, label):
        return True

    def _get_currency(self, code):
        if not code:
            return self.env.company.currency_id
        return (
            self.env["res.currency"].search([("name", "=", code)], limit=1)
            or self.env.company.currency_id
        )

    def _get_salesperson(self, login):
        if not login:
            return self.env.user
        return (
            self.env["res.users"]
            .sudo()
            .search([("login", "=", login)], limit=1)
            or self.env.user
        )

    def _parse_payload_date(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return fields.Date.to_date(value)
            except Exception:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
                except Exception:
                    return False
        return False

    def _get_key_variants(self, key):
        if key in (None, ""):
            return []
        raw = str(key).strip()
        if not raw:
            return []

        normalized = raw.lower()
        variants = [raw, normalized]

        snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw).lower()
        if snake not in variants:
            variants.append(snake)

        variants.append(normalized.replace("_", ""))
        variants.append(normalized.replace(" ", ""))
        variants.append(normalized.replace("-", ""))

        if normalized in {"start_date", "startdate", "start"}:
            variants += [
                "start_date", "startDate", "start",
                "start_date_text", "startDateText", "startdatetext",
                "effective_date", "effectiveDate", "effective",
                "issue_date", "issueDate", "issue",
            ]
        elif normalized in {"end_date", "enddate", "end", "expiry_date", "expirydate", "expiry", "due_date", "duedate", "due"}:
            variants += [
                "end_date", "endDate", "end",
                "end_date_text", "endDateText", "enddatetext",
                "expiry_date", "expiryDate", "expiry",
                "due_date", "dueDate", "due",
            ]
        elif normalized in {"invoice_date", "invoicedate", "invoice", "date"}:
            variants += ["invoice_date", "invoiceDate", "invoice", "date"]
        elif normalized.endswith("_date") and normalized[:-5]:
            base = normalized[:-5]
            variants += [base, f"{base}_date", f"{base}Date", f"{base}date"]
        elif normalized.endswith("date") and normalized[:-4]:
            base = normalized[:-4]
            variants += [base, f"{base}_date", f"{base}Date", f"{base}date"]

        return list(dict.fromkeys(v for v in variants if v))

    def _looks_like_date_key(self, key):
        if key in (None, ""):
            return False
        variants = {variant.lower() for variant in self._get_key_variants(key)}
        return bool(variants & {
            "start_date", "startdate", "start",
            "start_date_text", "startdatetext",
            "effective_date", "effectivedate", "effective",
            "issue_date", "issuedate", "issue",
            "end_date", "enddate", "end",
            "end_date_text", "enddatetext",
            "expiry_date", "expirydate", "expiry",
            "due_date", "duedate", "due",
            "invoice_date", "invoicedate", "invoice", "date",
        })

    def _resolve_date_from_path(self, payload, candidate):
        if not isinstance(candidate, (tuple, list)):
            return False

        path_variants = [self._get_key_variants(key) for key in candidate]
        for path in itertools.product(*path_variants):
            current = payload
            found = True
            for key in path:
                if not isinstance(current, dict):
                    found = False
                    break
                current = current.get(key)
            if not found:
                continue
            if current in (None, ""):
                continue
            parsed = self._parse_payload_date(current)
            if parsed:
                return parsed
        return False

    def _find_date_in_payload(self, payload):
        if not isinstance(payload, dict):
            return False

        for key, value in payload.items():
            if self._looks_like_date_key(key):
                parsed = self._parse_payload_date(value)
                if parsed:
                    return parsed

            if isinstance(value, dict):
                parsed = self._find_date_in_payload(value)
                if parsed:
                    return parsed
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        parsed = self._find_date_in_payload(item)
                        if parsed:
                            return parsed

        return False

    def _get_payload_date(self, payload, *candidates):
        if not isinstance(payload, dict):
            return False
        for candidate in candidates:
            if not candidate:
                continue
            if isinstance(candidate, (tuple, list)):
                parsed = self._resolve_date_from_path(payload, candidate)
                if parsed:
                    return parsed
                continue
            if isinstance(candidate, str):
                for key in self._get_key_variants(candidate):
                    value = payload.get(key)
                    if value not in (None, ""):
                        parsed = self._parse_payload_date(value)
                        if parsed:
                            return parsed

        if isinstance(payload.get("dates"), dict):
            dates_payload = payload.get("dates")
            for key in ("start_date", "startDateText", "startDate", "start"):
                value = dates_payload.get(key)
                if value not in (None, ""):
                    parsed = self._parse_payload_date(value)
                    if parsed:
                        return parsed
            for key in ("end_date", "endDateText", "endDate", "end", "expiry_date", "expiryDate"):
                value = dates_payload.get(key)
                if value not in (None, ""):
                    parsed = self._parse_payload_date(value)
                    if parsed:
                        return parsed

        return self._find_date_in_payload(payload)

    # -------------------------------------------------------
    # Partner
    # -------------------------------------------------------

    def _get_or_create_partner(self, customer):
        guid = (customer.get("external_guid") or "").strip()
        if not guid:
            raise ValidationError(_("customer.external_guid is required"))

        partner = self.env["res.partner"].search(
            [("external_guid", "=", guid),
             "|",
             ("company_id", "=", False),
             ("company_id", "=", self.env.company.id)
             ], limit=1
        )

        if not  partner:
            raise ValidationError(_("No partner found for external_guid: %s") % guid)
        return partner
            
            
        

    # -------------------------------------------------------
    # Agent
    # -------------------------------------------------------

    def _get_or_create_employee_details(self, agent):
        name = (agent.get("name") or "").strip()
        phone = (agent.get("phone") or "").strip()

        if not name:
            raise ValidationError(_("policy.agent.name is required"))

        self._validate_phone(phone, "Agent")

        Emp = self.env["employee.details"]

        rec = Emp.search(
            [("name", "=", name), ("phone", "=", phone)],
            limit=1,
        ) if phone else Emp.search([("name", "=", name)], limit=1)

        if rec:
            return rec

        return Emp.create({
            "name": name,
            "phone": phone,
        })

    # -------------------------------------------------------
    # Policy / Insurance
    # -------------------------------------------------------

    def _get_policy_type(self, type_name):
        if not type_name:
            return False
        return (
            self.env["policy.type"].search(
                [("name", "=", type_name)], limit=1
            )
            or self.env["policy.type"].create({"name": type_name})
        )

    def _create_policy(self, policy_data, currency):
        pt = self._get_policy_type(policy_data.get("type_name"))

        return self.env["policy.details"].create({
            "name": policy_data.get("name") or _("Policy"),
            "amount": policy_data.get("amount") or 0.0,
            "currency_id": currency.id,
            "policy_type_id": pt.id if pt else False,
        })

    def _create_insurance(self, payload, policy, partner, employee, currency):
        policy_data = payload.get("policy") or {}

        total_lines = sum(
            float(l.get("qty") or 1) *
            float(l.get("unit_price") or 0)
            for l in (payload.get("lines") or [])
        )

        start_date = self._get_payload_date(
            payload,
            ("start_date",),
            ("invoice_date",),
            ("policy", "start_date"),
            ("policy", "date"),
            ("invoice", "date"),
            ("invoice", "invoice_date"),
            ("policy", "effective_date"),
            ("policy", "issue_date"),
            ("policy", "expiry_date"),
        ) or fields.Date.today()

        insurance_vals = {
            "name": policy_data.get("name") or _("Insurance"),
            "partner_id": partner.id,
            "employee_id": employee.id,
            "policy_id": policy.id,
            "policy_number": int(policy_data.get("policy_number")),
            "policy_duration": int(policy_data.get("policy_duration") or 0),
            "currency_id": currency.id,
            "payment_type": policy_data.get("payment_type"),
            "start_date": start_date,
            "amount_installment": total_lines or policy_data.get("amount"),
            "state": "draft",
            "amount": policy_data.get("amount") or 0.0,
        }

        end_date = self._get_payload_date(
            payload,
            ("end_date",),
            ("policy", "end_date"),
            ("policy", "expiry_date"),
            ("invoice", "due_date"),
        )
        if end_date and "close_date" in self.env["insurance.details"]._fields:
            insurance_vals["close_date"] = end_date

        return self.env["insurance.details"].create(insurance_vals)

    # -------------------------------------------------------
    # Invoice
    # -------------------------------------------------------

    def _create_invoice(self, payload, partner, salesperson, currency, insurance):

        company = self.env.company

        journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", company.id)],
            limit=1
        )
        if not journal:
            raise ValidationError("No Sales Journal found.")

        invoice_lines = []

        for l in (payload.get("lines") or []):

            product_guid = (l.get("product_guid") or "").strip()
            if not product_guid:
                raise ValidationError("Missing product_guid")

            template = self.env["product.template"].sudo().search(
                [
                    ("x_external_guid", "=", product_guid),
                    "|",
                    ("company_id", "=", False),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )
            if not template:
                raise ValidationError(
                    _("Product not found for GUID: %s") % product_guid
                )

            product = template.product_variant_id

            invoice_lines.append((0, 0, {
                "product_id": product.id,
                "name": product.name,
                "quantity": float(l.get("qty") or 1.0),
                "price_unit": float(
                    l.get("unit_price") or product.lst_price
                ),
                # DO NOT pass tax_ids → let product sales tax apply
            }))

        if not invoice_lines:
            raise ValidationError(_("Invoice lines required."))

        move_vals = {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_user_id": salesperson.id,
            "currency_id": currency.id,
            "insurance_id": insurance.id,
            "company_id": company.id,
            "journal_id": journal.id,
            "invoice_line_ids": invoice_lines,
        }

        invoice_date = self._get_payload_date(
            payload,
            ("invoice_date",),
            ("invoice", "date"),
            ("invoice", "invoice_date"),
            ("date",),
            ("policy", "start_date"),
            ("policy", "date"),
        )
        if invoice_date:
            move_vals["invoice_date"] = invoice_date

        start_date = self._get_payload_date(
            payload,
            ("start_date",),
            ("policy", "start_date"),
            ("invoice", "start_date"),
            ("policy", "date"),
            ("invoice", "date"),
        )
        expiry_date = self._get_payload_date(
            payload,
            ("end_date",),
            ("expiry_date",),
            ("policy", "end_date"),
            ("policy", "expiry_date"),
            ("invoice", "expiry_date"),
            ("invoice", "due_date"),
        )
        if start_date:
            move_vals["insurance_start_date"] = start_date
        if expiry_date:
            move_vals["insurance_expiry_date"] = expiry_date

        return self.env["account.move"].with_company(company).create(move_vals)

    # -------------------------------------------------------
    # Post + Email
    # -------------------------------------------------------

    def _post_and_email(self, move):
        move.action_post()

        template = self.env.ref(
            "insurance_invoice_rpc.mail_template_invoice_poc",
            raise_if_not_found=False,
        )

        if template and move.partner_id.email:
            template.send_mail(move.id, force_send=True)

    # -------------------------------------------------------
    # Entry
    # -------------------------------------------------------

    def action_create_policy_and_invoice(self):
        for rec in self:
            try:
                payload = rec._load_payload()

                partner = rec._get_or_create_partner(payload.get("customer") or {})
                salesperson = rec._get_salesperson(
                    (payload.get("salesperson") or {}).get("login")
                )
                currency = rec._get_currency(payload.get("currency"))

                policy = rec._create_policy(
                    payload.get("policy") or {}, currency
                )

                insurance = rec._create_insurance(
                    payload, policy, partner,
                    rec._get_or_create_employee_details(
                        (payload.get("policy") or {}).get("agent") or {}
                    ),
                    currency,
                )

                move = rec._create_invoice(
                    payload, partner, salesperson,
                    currency, insurance
                )

                rec._post_and_email(move)

                rec.write({
                    "last_move_id": move.id,
                    "state": "done",
                    "error_message": False,
                })

                return move

            except Exception as e:
                rec.write({
                    "state": "error",
                    "error_message": str(e),
                })
                raise