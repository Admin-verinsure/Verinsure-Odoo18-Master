# -*- coding: utf-8 -*-
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

    _sql_constraints = [
        ("ext_id_unique", "unique(ext_id)", "This external reference already exists."),
    ]

    # ---------------- utilities ----------------
    @api.model
    def _digits_only(self, s):
        if not s:
            return ""
        return re.sub(r"\D+", "", str(s))

    @api.model
    def _sanitize_phone_10(self, s):
        """
        Return exactly 10 digits if possible.
        - If >=10 digits: last 10 digits
        - Else: ''
        """
        d = self._digits_only(s)
        return d[-10:] if len(d) >= 10 else ""

    @api.model
    def _coerce_policy_number(self, val):
        """
        Coerce payload policy_number to insurance.details field type.
        - If integer field → keep digits and int()
        - If char → keep string
        """
        ID = self.env['insurance.details']
        fld = ID._fields.get('policy_number')
        if not fld:
            return False
        if fld.type == 'integer':
            digits = self._digits_only(val)
            return int(digits) if digits else False
        return val or False

    # ---------------- partner/tax/account helpers ----------------
    @api.model
    def _find_partner(self, email=None, name=None, company_id=None, phone=None):
        """
        Prefer email → phone → name.
        Keep partner fields in sync with payload.
        NOTE: res.partner is usually shared (company_id False), so we do not force company_id filtering.
        """
        Partner = self.env["res.partner"].sudo()

        email = (email or "").strip().lower()
        name = (name or "").strip()
        phone = (phone or "").strip()

        partner = False
        if email:
            partner = Partner.search([("email", "=", email)], limit=1)
        if not partner and phone:
            partner = Partner.search([("phone", "=", phone)], limit=1)
        if not partner and name:
            partner = Partner.search([("name", "=", name)], limit=1)

        if not partner:
            vals = {
                "name": name or email or "Customer",
                "customer_rank": 1,
            }
            if email:
                vals["email"] = email
            if phone:
                vals["phone"] = phone
            partner = Partner.create(vals)
        else:
            upd = {}
            if email and partner.email != email:
                upd["email"] = email
            if phone and partner.phone != phone:
                upd["phone"] = phone
            if name and partner.name != name:
                upd["name"] = name
            if upd:
                partner.write(upd)

        return partner

    @api.model
    def _find_currency(self, code=None):
        return (self.env["res.currency"].sudo().search([("name", "=", code)], limit=1)
                if code else self.env.company.currency_id)

    @api.model
    def _find_journal(self, name=None, company_id=None):
        Journal = self.env["account.journal"].sudo()
        if name:
            j = Journal.search([("name", "=", name), ("company_id", "=", company_id)], limit=1)
            if j:
                return j
        return Journal.search([("type", "=", "sale"), ("company_id", "=", company_id)], limit=1)

    @api.model
    def _find_taxes(self, names=None, company_id=None):
        """Lookup taxes by name or description (supports inputs like 'GST 15%')."""
        names = names or []
        if isinstance(names, str):
            names = [names]
        names = [n for n in names if n]
        if not names:
            return [(6, 0, [])]

        Tax = self.env["account.tax"].sudo()
        # Correct domain: company AND (name in names OR description in names)
        dom = [
            "&",
            ("company_id", "=", company_id),
            "|",
            ("name", "in", names),
            ("description", "in", names),
        ]
        taxes = Tax.search(dom)
        return [(6, 0, taxes.ids)]

    @api.model
    def _fallback_income_account(self, company_id=None):
        Account = self.env["account.account"].sudo()
        # In v16+, company relation is via company_ids m2m
        acc = Account.search(
            [("account_type", "=", "income"), ("company_ids", "in", [company_id])], limit=1
        ) or Account.search([("account_type", "=", "income")], limit=1)
        if not acc:
            raise ValueError("No income account available to create invoice lines.")
        return acc

    @api.model
    def _find_payment_term(self, name=None):
        return (self.env['account.payment.term'].sudo().search([('name', '=', name)], limit=1)
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
        """Send the invoice email immediately to the payload email (preferred)."""
        target = (to_email or "").strip() or (move.partner_id.email or "").strip()
        if not target:
            # create an activity instead of failing hard
            self.env['mail.activity'].sudo().create({
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
            force_send=True,
            email_values={
                'email_to': target,
                'recipient_ids': [],
                'partner_ids': [],
                'partner_to': False,
            },
        )

    # ---------------- agent / insurance / policy helpers ----------------
    @api.model
    def _find_or_create_policy_type(self, type_name):
        """Ensure/return policy.type by name."""
        if not type_name:
            return self.env['policy.type'].browse()
        PT = self.env['policy.type'].sudo()
        rec = PT.search([('name', '=', type_name)], limit=1)
        return rec or PT.create({'name': type_name})

    @api.model
    def _find_or_create_employee(self, person, company_id):
        """
        Ensure employee.details WITHOUT assuming fields exist.

        Strategy:
          1) Find/Create res.partner using email/phone/name
          2) Link/find employee.details via x_partner_id (preferred) or partner_id (if exists)
          3) Only search/write fields that exist on employee.details
        Returns: (partner, emp_recordset_or_empty)
        """
        person = person or {}
        name = (person.get("name") or "").strip() or "Customer"
        email = (person.get("email") or "").strip().lower()
        phone10 = self._sanitize_phone_10(person.get("phone"))

        partner = self._find_partner(
            email=email or None,
            name=name,
            company_id=company_id,
            phone=phone10 or None,
        )

        if "employee.details" not in self.env:
            return partner, self.env["employee.details"].browse()

        ED = self.env["employee.details"].sudo()

        def has(field_name):
            return field_name in ED._fields

        link_field = "x_partner_id" if has("x_partner_id") else ("partner_id" if has("partner_id") else None)

        emp = False
        if link_field:
            emp = ED.search([(link_field, "=", partner.id)], limit=1)

        if not emp and has("email") and email:
            emp = ED.search([("email", "=", email)], limit=1)
        if not emp and has("phone") and phone10:
            emp = ED.search([("phone", "=", phone10)], limit=1)
        if not emp and has("name") and name:
            emp = ED.search([("name", "=", name)], limit=1)

        if not emp:
            vals = {}
            if has("name"):
                vals["name"] = name
            if has("email") and email:
                vals["email"] = email
            if has("phone") and phone10:
                vals["phone"] = phone10
            if has("company_id") and company_id:
                vals["company_id"] = company_id
            if link_field:
                vals[link_field] = partner.id

            emp = ED.create(vals) if vals else ED.browse()
        else:
            if link_field and not getattr(emp, link_field, False):
                try:
                    emp.write({link_field: partner.id})
                except Exception:
                    pass

        return partner, emp

    @api.model
    def _find_or_create_agent(self, agent_payload, company_id):
        """
        Ensure employee.details for agent WITHOUT assuming fields exist.
        Returns: employee.details recordset (or empty browse)
        """
        if "employee.details" not in self.env:
            return self.env["employee.details"].browse()

        ED = self.env["employee.details"].sudo()
        if not agent_payload:
            return ED.browse()

        name = (agent_payload.get("name") or "").strip() or "Agent"
        email = (agent_payload.get("email") or "").strip().lower()
        phone10 = self._sanitize_phone_10(agent_payload.get("phone"))

        def has(field_name):
            return field_name in ED._fields

        link_field = "x_partner_id" if has("x_partner_id") else ("partner_id" if has("partner_id") else None)

        # Optional: create partner for agent too (helps linking if link field exists)
        partner = self._find_partner(
            email=email or None,
            name=name,
            company_id=company_id,
            phone=phone10 or None,
        )

        agent = False
        if link_field:
            agent = ED.search([(link_field, "=", partner.id)], limit=1)

        if not agent and has("email") and email:
            agent = ED.search([("email", "=", email)], limit=1)
        if not agent and has("phone") and phone10:
            agent = ED.search([("phone", "=", phone10)], limit=1)
        if not agent and has("name") and name:
            agent = ED.search([("name", "=", name)], limit=1)

        if not agent:
            vals = {}
            if has("name"):
                vals["name"] = name
            if has("email") and email:
                vals["email"] = email
            if has("phone") and phone10:
                vals["phone"] = phone10
            if has("company_id") and company_id:
                vals["company_id"] = company_id
            if link_field:
                vals[link_field] = partner.id

            agent = ED.create(vals) if vals else ED.browse()
        else:
            if link_field and not getattr(agent, link_field, False):
                try:
                    agent.write({link_field: partner.id})
                except Exception:
                    pass

        return agent

    @api.model
    def _find_or_create_policy(self, payload_policy, partner, emp):
        """Ensure policy.details (+ insurance.details) exists/linked.

        Agent linking is best-effort and supports either:
          - policy.details.agent_id / insurance.details.agent_id (if those exist), OR
          - policy.details.x_agent_id / insurance.details.x_agent_id (from this module)
        """
        PD = self.env['policy.details'].sudo()
        ID = self.env['insurance.details'].sudo()

        p = payload_policy or {}
        ptype = self._find_or_create_policy_type(p.get('type_name'))

        agent = self._find_or_create_agent(p.get('agent'), company_id=self.env.user.company_id.id)

        pd_agent_field = 'agent_id' if 'agent_id' in PD._fields else ('x_agent_id' if 'x_agent_id' in PD._fields else None)
        id_agent_field = 'agent_id' if 'agent_id' in ID._fields else ('x_agent_id' if 'x_agent_id' in ID._fields else None)

        # Policy
        pol_name = p.get('name') or p.get('policy_no') or 'Policy'
        dom = [('name', '=', pol_name)]
        if ptype:
            dom.append(('policy_type_id', '=', ptype.id))
        pol = PD.search(dom, limit=1)
        if not pol:
            pol_vals = {
                'name': pol_name,
                'policy_type_id': ptype.id if ptype else False,
            }
            if p.get('amount') is not None and 'amount' in PD._fields:
                pol_vals['amount'] = p['amount']
            if pd_agent_field and agent:
                pol_vals[pd_agent_field] = agent.id
            pol = PD.create(pol_vals)
        else:
            if pd_agent_field and agent and not getattr(pol, pd_agent_field, False):
                try:
                    pol.sudo().write({pd_agent_field: agent.id})
                except Exception:
                    pass

        # Insurance
        ins_dom = [('policy_id', '=', pol.id)]
        if 'partner_id' in ID._fields:
            ins_dom.append(('partner_id', '=', partner.id))
        ins = ID.search(ins_dom, limit=1)

        if not ins:
            policy_number_val = self._coerce_policy_number(p.get('policy_number'))
            ins_vals = {
                'policy_id': pol.id,
            }
            if 'partner_id' in ID._fields:
                ins_vals['partner_id'] = partner.id
            if 'employee_id' in ID._fields and emp:
                ins_vals['employee_id'] = emp.id
            if 'payment_type' in ID._fields:
                ins_vals['payment_type'] = p.get('payment_type') or 'fixed'
            if 'policy_duration' in ID._fields:
                ins_vals['policy_duration'] = p.get('policy_duration') or 12
            if policy_number_val and 'policy_number' in ID._fields:
                ins_vals['policy_number'] = policy_number_val
            if id_agent_field and agent:
                ins_vals[id_agent_field] = agent.id

            ins = ID.create(ins_vals)

            if hasattr(ins, 'action_confirm_insurance'):
                try:
                    ins.action_confirm_insurance()
                except Exception:
                    pass
        else:
            to_write = {}
            policy_number_val = self._coerce_policy_number(p.get('policy_number'))
            if policy_number_val and 'policy_number' in ID._fields and getattr(ins, 'policy_number', None) in (False, 0, '', None):
                to_write['policy_number'] = policy_number_val
            if id_agent_field and agent and not getattr(ins, id_agent_field, False):
                to_write[id_agent_field] = agent.id
            if to_write:
                try:
                    ins.sudo().write(to_write)
                except Exception:
                    pass

        return pol, ins

    def _create_invoice_linked_to_insurance(
        self, *, company, partner, salesperson, line_cmds, narration_html, data, insurance
    ):
        """
        Create & post invoice and link to insurance (preferred).
        Assumes account.move has M2O 'insurance_id' → insurance.details.
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

        # link insurance if field exists on account.move
        if insurance and 'insurance_id' in self.env['account.move']._fields:
            move_vals["insurance_id"] = insurance.id
            move_vals["invoice_origin"] = getattr(insurance, 'name', False) or (data.get("ref") or "API")

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

        move = self.env["account.move"].sudo().with_context(
            default_move_type="out_invoice",
            allowed_company_ids=[company.id],
        ).create(move_vals)

        move.action_post()
        return move

    # ---------------- handy serializer (optional) ----------------
    @api.model
    def _move_to_payload(self, move):
        return {
            "id": move.id,
            "name": move.name,
            "state": move.state,
            "company": move.company_id.name,
            "company_id": move.company_id.id,
            "partner_id": move.partner_id.id,
            "partner_name": move.partner_id.display_name,
            "currency": move.currency_id.name,
            "amount_untaxed": move.amount_untaxed,
            "amount_tax": move.amount_tax,
            "amount_total": move.amount_total,
            "invoice_date": move.invoice_date and str(move.invoice_date) or None,
            "due_date": move.invoice_date_due and str(move.invoice_date_due) or None,
            "payment_term": move.invoice_payment_term_id and move.invoice_payment_term_id.name or None,
            "payment_reference": move.payment_reference or None,
            "ref": move.ref or None,
            "invoice_user_id": move.invoice_user_id and move.invoice_user_id.id or None,
            "invoice_user": move.invoice_user_id and move.invoice_user_id.login or None,
            "backend_url": f"/odoo/action-account.action_move_out_invoice_type?res_id={move.id}&cids={move.company_id.id}",
            "lines": [
                {
                    "name": l.name,
                    "quantity": l.quantity,
                    "price_unit": l.price_unit,
                    "taxes": [t.name for t in l.tax_ids],
                    "subtotal": l.price_subtotal,
                }
                for l in move.invoice_line_ids
            ],
        }

    # ---------------- main (policy-first) ----------------
    def action_create_policy_and_invoice(self):
        """
        Policy-first flow:
        1) ensure Policy (+ Insurance) from payload.policy (with agent if provided)
        2) ensure Customer/Employee
        3) create & post invoice linked to insurance
        4) email to payload email (if provided)
        """
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")

        # Company & default salesperson
        company = self.env.user.company_id
        ICP = self.env['ir.config_parameter'].sudo()
        default_login = ICP.get_param('invoice_poc.default_salesperson_login', default='admin@verinsure.online')
        salesperson = self.env['res.users'].sudo().search([('login', '=', default_login)], limit=1) or self.env.user

        # Payload override for salesperson
        sp = (data.get("salesperson") or {})
        if sp.get("login"):
            salesperson = self.env['res.users'].sudo().search([('login', '=', sp["login"])], limit=1) or salesperson
        elif sp.get("id"):
            salesperson = self.env['res.users'].sudo().browse(sp["id"]).exists() or salesperson

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

        # Policy + Insurance (+ Agent)
        policy_payload = data.get("policy") or {}
        policy, insurance = self._find_or_create_policy(policy_payload, partner, emp)

        # Create invoice linked to insurance
        move = self._create_invoice_linked_to_insurance(
            company=company,
            partner=partner,
            salesperson=salesperson,
            line_cmds=line_cmds,
            narration_html=narration_html,
            data=data,
            insurance=insurance,
        )

        # Email
        try:
            self._send_invoice_email(move, to_email=customer.get("email"))
        except Exception as e:
            move.message_post(body=f"Immediate email send failed: {e}")

        self.sudo().write({"move_id": move.id, "state": "posted"})
        return move

    # ---------------- legacy entrypoint ----------------
    def action_create_and_post_invoice(self):
        """
        If payload contains 'policy', use policy-first flow.
        Else, create a plain customer invoice.
        """
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")
        if data.get('policy'):
            return self.action_create_policy_and_invoice()

        company = self.env.user.company_id
        ICP = self.env['ir.config_parameter'].sudo()
        default_login = ICP.get_param('invoice_poc.default_salesperson_login', default='admin@verinsure.online')
        salesperson = self.env['res.users'].sudo().search([('login', '=', default_login)], limit=1) or self.env.user

        sp = (data.get("salesperson") or {})
        if sp.get("login"):
            salesperson = self.env['res.users'].sudo().search([('login', '=', sp["login"])], limit=1) or salesperson
        elif sp.get("id"):
            salesperson = self.env['res.users'].sudo().browse(sp["id"]).exists() or salesperson

        customer = data.get("customer", {}) or {}
        if customer.get("phone"):
            customer = dict(customer)
            customer["phone"] = self._sanitize_phone_10(customer["phone"])

        partner = self._find_partner(
            email=customer.get("email"),
            name=customer.get("name"),
            company_id=company.id,
            phone=customer.get("phone"),
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

        move = self.env["account.move"].sudo().with_context(
            default_move_type="out_invoice",
            allowed_company_ids=[company.id],
        ).create(move_vals)

        move.action_post()
        try:
            self._send_invoice_email(move, to_email=customer.get("email"))
        except Exception as e:
            move.message_post(body=f"Immediate email send failed: {e}")

        self.sudo().write({"move_id": move.id, "state": "posted"})
        return move
