from odoo import models, fields, api
import json
import re

# ──────────────────────────────────────────────────────────────────────────────
# Hard-coded defaults
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_TERMS = [
    "By placing an order with Not 4 Profit you agree to these terms and conditions in addition to the terms set out in any Long Term Customer Relationship Agreement.",
    "All development orders are subject to availability of the development team.",
    "Product/Services descriptions are high level and subject to detailed management through our Helpdesk and Project Management system.",
    "Estimated delivery of development is subject to delays that occur due to unforeseen circumstances.",
    "Not4Profit is not liable for any loss, damage, or costs incurred due to project delivery delays.",
    "For inquiries, assistance, or concerns, please contact our customer service team via the provided channels.",
    "Not4Profit respects your privacy. Personal and payment information is collected and used solely for order processing and communication purposes. We do not share customer information with third parties except as required for order fulfillment.",
    "All content, including images, text, and designs are either open source licensed under the GPL or provided by you.",
    "These terms and conditions are governed by the laws of the jurisdiction in which Not4Profit operates.",
    "Not4Profit reserves the right to modify these terms and conditions at any time. Any changes will be effective upon posting on our website.",
    "By ordering and receiving Not4Profit services you agree to abide by these terms and conditions.",
]

DEFAULT_NOTES_HTML = (
    "<p>Verinsure provides the support for RAWCS.org but will be a subcontractor to Not4Profit online.</p>"
    "<p>RAWCS will be contracting Four Way Test Limited - the details for that company are:</p>"
    "<ul>"
    "<li>(a) its shares are owned by the Rotary Club of Auckland Foundation</li>"
    "<li>(b) it is a NZ Company 595123 NZBN: 942903882521</li>"
    "<li>(c) it was Incorporated: 01 Jul 1993</li>"
    "<li>(d) has other sources of income from regular charitable events</li>"
    "<li>(e) operates the Not4Profit Foundation and manages the source code</li>"
    "<li>(f) is itself a registered charity.</li>"
    "</ul>"
)


class InvoicePocPayload(models.Model):
    _name = "invoice.poc.payload"
    _description = "Stored payloads for invoice POC"

    # INPUT container
    ext_id = fields.Char(index=True)
    payload_json = fields.Text(required=True)

    # Trace
    move_id = fields.Many2one("account.move", string="Created Invoice", ondelete="set null")
    state = fields.Selection(
        [("new", "New"), ("posted", "Posted"), ("error", "Error")],
        default="new", required=True
    )
    error_message = fields.Text()

    # Idempotency on external reference
    _sql_constraints = [
        ("ext_id_unique", "unique(ext_id)", "This external reference already exists."),
    ]

    # ---------------- small utils ----------------
    @api.model
    def _digits_only(self, s):
        if not s:
            return ""
        return re.sub(r"\D+", "", str(s))

    @api.model
    def _sanitize_phone_10(self, s):
        """Return last 10 digits if available, else empty."""
        d = self._digits_only(s)
        return d[-10:] if len(d) >= 10 else (d if len(d) == 10 else "")

    @api.model
    def _coerce_policy_number(self, val):
        """
        Coerce payload policy_number to the correct field type on insurance.details.
        - If field is Integer: keep digits only, convert to int, else return False.
        - If field is Char: return original string.
        """
        ID = self.env['insurance.details']
        fld = ID._fields.get('policy_number')
        if not fld:
            return False
        if fld.type == 'integer':
            digits = self._digits_only(val)
            return int(digits) if digits else False
        # Char or anything else: store as-is (string)
        return val or False

    # ---------------- Odoo finders ----------------
    @api.model
    def _find_partner(self, email=None, name=None, company_id=None):
        """Prefer payload email; keep partner email/name in sync with payload."""
        Partner = self.env["res.partner"]
        if email:
            dom = [("email", "=", email)]
        elif name:
            dom = [("name", "=", name)]
        else:
            raise ValueError("Provide partner email or name")

        dom = ["&", ("company_id", "in", [False, company_id])] + dom
        partner = Partner.search(dom, limit=1)
        if not partner:
            partner = Partner.create({
                "name": name or email,
                "email": email,
                "customer_rank": 1,
                "company_id": company_id,
            })
        else:
            vals = {}
            if email and partner.email != email:
                vals["email"] = email
            if name and partner.name != name:
                vals["name"] = name
            if vals:
                partner.sudo().write(vals)
        return partner

    @api.model
    def _find_currency(self, code=None):
        return (self.env["res.currency"].search([("name", "=", code)], limit=1)
                if code else self.env.company.currency_id)

    @api.model
    def _find_journal(self, name=None, company_id=None):
        Journal = self.env["account.journal"]
        if name:
            j = Journal.search([("name", "=", name), ("company_id", "=", company_id)], limit=1)
            if j:
                return j
        return Journal.search([("type", "=", "sale"), ("company_id", "=", company_id)], limit=1)

    @api.model
    def _find_taxes(self, names=None, company_id=None):
        """
        Lookup taxes by name OR description to support inputs like 'GST 15%'.
        Handles DBs with/without company_id on account.tax and fixes domain grouping.
        """
        names = names or []
        if isinstance(names, str):
            names = [names]
        if not names:
            return [(6, 0, [])]

        Tax = self.env["account.tax"]
        dom = ["|", ("name", "in", names), ("description", "in", names)]
        # gate company_id only if the field exists
        if "company_id" in Tax._fields and company_id:
            dom = ["&", ("company_id", "=", company_id)] + dom
        taxes = Tax.search(dom)
        return [(6, 0, taxes.ids)]

    @api.model
    def _fallback_income_account(self, company_id=None):
        """
        Find an income account for the given company.
        Works for schemas with either 'company_ids' (M2M) or 'company_id' (M2O).
        """
        Account = self.env["account.account"]
        dom = [("account_type", "=", "income")]

        if "company_ids" in Account._fields:
            if company_id:
                dom.append(("company_ids", "in", [company_id]))
        elif "company_id" in Account._fields:
            if company_id:
                dom.append(("company_id", "=", company_id))

        acc = Account.search(dom, limit=1)
        if not acc:
            acc = Account.search([("account_type", "=", "income")], limit=1)
        if not acc:
            raise ValueError("No income account available to create invoice lines.")
        return acc

    @api.model
    def _find_payment_term(self, name=None):
        return (self.env['account.payment.term'].search([('name', '=', name)], limit=1)
                if name else self.env['account.payment.term'].browse())

    @api.model
    def _build_narration_html(self, data):
        """Build HTML (Terms + Notes). Payload overrides default."""
        terms_list = data.get("terms") or DEFAULT_TERMS
        notes_html = (data.get("notes") or data.get("note") or DEFAULT_NOTES_HTML)
        if isinstance(notes_html, str):
            notes_html = notes_html.strip()

        parts = []
        if terms_list:
            li = "".join(f"<li>{t}</li>" for t in terms_list if t)
            parts.append("<h4>Terms &amp; Conditions</h4>")
            parts.append(f"<ul>{li}</ul>")
        if notes_html:
            parts.append("<h4>Notes</h4>")
            parts.append(notes_html)

        return "".join(parts) if parts else False

    def _send_invoice_email(self, move, to_email=None):
        """
        Send the invoice email immediately to the *payload* email (preferred).
        Clear partner recipients to avoid MissingError on stale/forbidden partners.
        """
        target = (to_email or "").strip() or (move.partner_id.email or "").strip()
        if not target:
            self.env['mail.activity'].create({
                'res_model_id': self.env['ir.model']._get_id('account.move'),
                'res_id': move.id,
                'res_name': move.name,
                'user_id': self.env.user.id,
                'summary': 'Missing customer email',
                'note': 'Email not sent: no email in payload and partner has no email.',
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            })
            return

        template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
        if not template:
            move.message_post(body=f"Invoice posted; email to {target} not sent (template missing).")
            return

        template.sudo().send_mail(
            move.id,
            force_send=True,  # send now (requires valid outgoing mail server)
            email_values={
                'email_to': target,
                'recipient_ids': [],  # clear partner recipients
                'partner_ids': [],    # extra safety
                'partner_to': False,  # ignore template partner_to
                # 'email_from': move.company_id.email or self.env.user.email_formatted,
            },
        )

    # ---------------- insurance/policy helpers ----------------
    @api.model
    def _find_or_create_policy_type(self, type_name):
        """Ensure/return policy.type by name (adjust model if your technical name differs)."""
        if not type_name:
            return self.env['policy.type'].browse()
        PT = self.env['policy.type']
        rec = PT.search([('name', '=', type_name)], limit=1)
        return rec or PT.create({'name': type_name})

    @api.model
    def _find_or_create_employee(self, customer, company_id):
        """
        Ensure an employee.details for the insured person.
        enforces exactly-10-digit phone (as your module validates).
        """
        ED = self.env['employee.details']
        partner = self._find_partner(
            email=customer.get('email'),
            name=customer.get('name'),
            company_id=company_id,
        )
        emp = ED.search([('partner_id', '=', partner.id)], limit=1)
        if not emp:
            phone10 = self._sanitize_phone_10(customer.get('phone'))
            vals = {
                'name': customer.get('name') or partner.name,
                'partner_id': partner.id,
                'email': customer.get('email') or partner.email,
                **({'phone': phone10} if phone10 else {}),
            }
            emp = ED.create(vals)
        return partner, emp

    @api.model
    def _find_or_create_policy(self, payload_policy, partner, emp):
        """
        Ensure policy.details (+ insurance.details) exists/linked.
        Adjust field names if your model differs.
        """
        PD = self.env['policy.details']
        ID = self.env['insurance.details']

        p = payload_policy or {}
        ptype = self._find_or_create_policy_type(p.get('type_name'))

        dom = []
        if p.get('policy_no'):
            dom.append(('policy_no', '=', p['policy_no']))
        if ptype:
            dom.append(('policy_type_id', '=', ptype.id))

        pol = PD.search(dom or [], limit=1)
        if not pol:
            pol_vals = {
                'name': p.get('name') or p.get('policy_no') or 'Policy',
                'policy_no': p.get('policy_no'),
                'policy_type_id': ptype.id if ptype else False,
                'partner_id': partner.id,
                'employee_id': emp.id if emp else False,
                'start_date': p.get('start_date'),
                'end_date': p.get('end_date'),
                'sum_insured': p.get('sum_insured'),
                'premium': p.get('premium'),
                'insurer': p.get('insurer'),
                'amount': p.get('amount'),
            }
            pol = PD.create({k: v for k, v in pol_vals.items() if v is not None})

        policy_number_val = self._coerce_policy_number(p.get('policy_number'))
        ins = ID.search([('policy_id', '=', pol.id)], limit=1)
        if not ins:
            ins_vals = {
                'policy_id': pol.id,
                'partner_id': partner.id,
                'employee_id': emp.id if emp else False,
                **({'policy_number': policy_number_val} if policy_number_val else {}),
                **({'policy_duration': p.get('policy_duration')} if p.get('policy_duration') else {}),
                **({'payment_type': p.get('payment_type')} if p.get('payment_type') else {}),
            }
            ins = ID.create(ins_vals)
        else:
            if policy_number_val:
                try:
                    ins.sudo().write({'policy_number': policy_number_val})
                except Exception:
                    pass
        return pol, ins

    def _create_invoice_linked_to_policy(self, company, partner, salesperson, line_cmds, narration_html, data, policy, insurance):
        """
        Create & post invoice and link to insurance (primary) and policy (if the field exists).
        """
        currency = self._find_currency(data.get("currency"))
        journal = self._find_journal(data.get("journal"), company_id=company.id)
        if not journal:
            raise ValueError("No SALE journal found for this company.")
        payment_term = self._find_payment_term(data.get("payment_term"))

        move_vals = {
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "journal_id": journal.id,
            "currency_id": currency.id if currency else False,
            "invoice_user_id": salesperson.id,
            "invoice_line_ids": line_cmds,
            "narration": narration_html or False,
        }

        # Link to insurance/policy if the fields exist
        Move = self.env['account.move']
        if 'insurance_id' in Move._fields and insurance:
            move_vals["insurance_id"] = insurance.id
        if 'policy_id' in Move._fields and policy:
            move_vals["policy_id"] = policy.id

        # header extras
        if data.get("ref"):
            move_vals["ref"] = data["ref"]
        if data.get("invoice_date"):
            move_vals["invoice_date"] = data["invoice_date"]
        if data.get("due_date"):
            move_vals["invoice_date_due"] = data["due_date"]
        if data.get("payment_reference"):
            move_vals["payment_reference"] = data["payment_reference"]
        if payment_term:
            move_vals["invoice_payment_term_id"] = payment_term.id

        # Traceability back to the policy/insurance
        if 'invoice_origin' in Move._fields:
            origin_bits = []
            if policy:
                origin_bits.append(f"Policy:{policy.name or policy.id}")
            if insurance and getattr(insurance, 'policy_number', False):
                origin_bits.append(f"PolicyNo:{insurance.policy_number}")
            if origin_bits:
                move_vals['invoice_origin'] = " | ".join(origin_bits)

        move = Move.with_context(
            default_move_type="out_invoice",
            allowed_company_ids=[company.id],
        ).create(move_vals)

        move.action_post()
        return move

    # ---------------- main (policy-first) ----------------
    def action_create_policy_and_invoice(self):
        """
        Policy-first flow:
        1) ensure Policy (+ Insurance) from payload.policy
        2) ensure Customer/Employee (phone sanitized to 10 digits)
        3) create & post invoice linked to insurance/policy
        4) email to payload email (if provided)
        """
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")

        # Company & default salesperson
        company = self.env.user.company_id
        ICP = self.env['ir.config_parameter'].sudo()
        default_login = ICP.get_param('invoice_poc.default_salesperson_login', default='admin@verinsure.online')
        salesperson = self.env['res.users'].search([('login', '=', default_login)], limit=1) or self.env.user

        # Payload override for salesperson
        sp = (data.get("salesperson") or {})
        if sp.get("login"):
            salesperson = self.env['res.users'].search([('login', '=', sp["login"])], limit=1) or salesperson
        elif sp.get("id"):
            salesperson = self.env['res.users'].browse(sp["id"]).exists() or salesperson

        # Customer/Employee
        customer = data.get("customer", {}) or {}
        if customer.get("phone"):
            customer = dict(customer)
            customer["phone"] = self._sanitize_phone_10(customer["phone"])
        partner, emp = self._find_or_create_employee(customer, company.id)

        # Lines
        lines_in = data.get("lines") or []
        if not lines_in:
            raise ValueError("At least one line is required")
        income_acct = self._fallback_income_account(company_id=company.id)

        line_cmds = []
        for l in lines_in:
            line_cmds.append((0, 0, {
                "name": l.get("description") or l.get("name") or "Item",
                "quantity": float(l.get("qty") or 1.0),
                "price_unit": float(l.get("unit_price") or 0.0),
                "tax_ids": self._find_taxes(l.get("tax_names"), company_id=company.id),
                "account_id": income_acct.id,
            }))

        # Narration (Terms + Notes)
        narration_html = self._build_narration_html(data)

        # Policy + Insurance
        policy_payload = data.get("policy") or {}
        policy, insurance = self._find_or_create_policy(policy_payload, partner, emp)

        # Create invoice linked to policy/insurance
        move = self._create_invoice_linked_to_policy(
            company=company,
            partner=partner,
            salesperson=salesperson,
            line_cmds=line_cmds,
            narration_html=narration_html,
            data=data,
            policy=policy,
            insurance=insurance,
        )

        # Email
        try:
            self._send_invoice_email(move, to_email=customer.get("email"))
        except Exception as e:
            move.message_post(body=f"Immediate email send failed: {e}")

        self.write({"move_id": move.id, "state": "posted"})
        return move

    # ---------------- legacy entrypoint (kept for compatibility) ----------------
    def action_create_and_post_invoice(self):
        """
        Backward compatible:
        - If payload contains 'policy', use policy-first flow.
        - Else, behave like the previous invoice-only flow.
        """
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")
        if data.get('policy'):
            return self.action_create_policy_and_invoice()

        # Invoice-only fallback (minimal)
        company = self.env.user.company_id
        ICP = self.env['ir.config_parameter'].sudo()
        default_login = ICP.get_param('invoice_poc.default_salesperson_login', default='admin@verinsure.online')
        salesperson = self.env['res.users'].search([('login', '=', default_login)], limit=1) or self.env.user

        sp = (data.get("salesperson") or {})
        if sp.get("login"):
            salesperson = self.env['res.users'].search([('login', '=', sp["login"])], limit=1) or salesperson
        elif sp.get("id"):
            salesperson = self.env['res.users'].browse(sp["id"]).exists() or salesperson

        customer = data.get("customer", {}) or {}
        if customer.get("phone"):
            customer = dict(customer)
            customer["phone"] = self._sanitize_phone_10(customer["phone"])
        partner = self._find_partner(
            email=customer.get("email"),
            name=customer.get("name"),
            company_id=company.id,
        )
        currency = self._find_currency(data.get("currency"))
        journal = self._find_journal(data.get("journal"), company_id=company.id)
        if not journal:
            raise ValueError("No SALE journal found for this company.")
        payment_term = self._find_payment_term(data.get("payment_term"))

        lines_in = data.get("lines") or []
        if not lines_in:
            raise ValueError("At least one line is required")
        income_acct = self._fallback_income_account(company_id=company.id)

        line_cmds = []
        for l in lines_in:
            line_cmds.append((0, 0, {
                "name": l.get("description") or l.get("name") or "Item",
                "quantity": float(l.get("qty") or 1.0),
                "price_unit": float(l.get("unit_price") or 0.0),
                "tax_ids": self._find_taxes(l.get("tax_names"), company_id=company.id),
                "account_id": income_acct.id,
            }))

        narration_html = self._build_narration_html(data)

        move_vals = {
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "journal_id": journal.id,
            "currency_id": currency.id if currency else False,
            "invoice_user_id": salesperson.id,
            "invoice_line_ids": line_cmds,
            "narration": narration_html or False,
        }
        if data.get("ref"):
            move_vals["ref"] = data["ref"]
        if data.get("invoice_date"):
            move_vals["invoice_date"] = data["invoice_date"]
        if data.get("due_date"):
            move_vals["invoice_date_due"] = data["due_date"]
        if data.get("payment_reference"):
            move_vals["payment_reference"] = data["payment_reference"]
        if payment_term:
            move_vals["invoice_payment_term_id"] = payment_term.id

        move = self.env["account.move"].with_context(
            default_move_type="out_invoice",
            allowed_company_ids=[company.id],
        ).create(move_vals)

        move.action_post()
        try:
            self._send_invoice_email(move, to_email=customer.get("email"))
        except Exception as e:
            move.message_post(body=f"Immediate email send failed: {e}")

        self.write({"move_id": move.id, "state": "posted"})
        return move
