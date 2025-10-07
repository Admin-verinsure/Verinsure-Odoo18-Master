from odoo import models, fields, api
import json

# ──────────────────────────────────────────────────────────────────────────────
# Hard-coded defaults (used when payload doesn't provide overrides)
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
    move_id = fields.Many2one("account.move", string="Created Invoice")
    state = fields.Selection(
        [("new", "New"), ("posted", "Posted"), ("error", "Error")],
        default="new", required=True
    )
    error_message = fields.Text()

    # ---------------- helpers ----------------
    
    @api.model
    def _find_partner(self, email=None, name=None, company_id=None):
        Partner = self.env["res.partner"]
        if email and name:
            dom = ["|", ("email", "=", email), ("name", "=", name)]
        elif email:
            dom = [("email", "=", email)]
        elif name:
            dom = [("name", "=", name)]
        else:
            raise ValueError("Provide partner email or name")

        # Prefer same-company or shared partner
        dom = ["&", ("company_id", "in", [False, company_id])] + dom
        partner = Partner.search(dom, limit=1)
        if not partner:
            partner = Partner.create({
                "name": name or email,
                "email": email,
                "customer_rank": 1,
                "company_id": company_id,  # ensure company consistency
            })
        return partner

    @api.model
    def _find_currency(self, code=None):
        # If payload didn't say, use company currency
        if not code:
            return self.env.company.currency_id
        return self.env["res.currency"].search([("name", "=", code)], limit=1) or self.env.company.currency_id

    @api.model
    def _find_journal(self, name=None, company_id=None):
        Journal = self.env["account.journal"]
        if name:
            j = Journal.search([
                ("name", "=", name),
                ("company_id", "=", company_id),
            ], limit=1)
            if j:
                return j
        j = Journal.search([
            ("type", "=", "sale"),
            ("company_id", "=", company_id),
        ], limit=1)
        return j

    @api.model
    def _find_taxes(self, names=None, company_id=None):
        names = names or []
        if not names:
            return [(6, 0, [])]
        taxes = self.env["account.tax"].search([
            ("name", "in", names),
            ("company_id", "=", company_id),
        ])
        return [(6, 0, taxes.ids)]

    @api.model
    def _fallback_income_account(self, company_id=None):
        # Prefer an account allowed in this company via company_ids, else any income
        acc = self.env["account.account"].search(
            [("account_type", "=", "income"), ("company_ids", "in", [company_id])],
            limit=1
        ) or self.env["account.account"].search([("account_type", "=", "income")], limit=1)
        if not acc:
            raise ValueError("No income account available to create invoice lines.")
        return acc

    @api.model
    def _find_payment_term(self, name=None):
        if not name:
            return self.env['account.payment.term'].browse()
        return self.env['account.payment.term'].search([('name', '=', name)], limit=1)

    @api.model
    def _build_narration_html(self, data):
        """
        Build HTML for Terms & Conditions + Notes (printed via o.narration in your QWeb).
        Uses payload overrides if provided, otherwise the defaults above.
        """
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

    # ---------------- main ----------------
    def action_create_and_post_invoice(self):
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")

        # Target company & default salesperson (configurable via system parameter)
        company = self.env.user.company_id
        ICP = self.env['ir.config_parameter'].sudo()
        default_login = ICP.get_param('invoice_poc.default_salesperson_login', default='admin@verinsure.online')
        salesperson = self.env['res.users'].search([('login', '=', default_login)], limit=1) or self.env.user

        # Optional payload override for salesperson
        sp = (data.get("salesperson") or {})
        if sp.get("login"):
            salesperson = self.env['res.users'].search([('login', '=', sp["login"])], limit=1) or salesperson
        elif sp.get("id"):
            salesperson = self.env['res.users'].browse(sp["id"]).exists() or salesperson

        # Header
        customer = data.get("customer", {}) or {}
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

        # Narration (Terms + Notes) with defaults/overrides
        narration_html = self._build_narration_html(data)

        move_vals = {
            "move_type": "out_invoice",
            "company_id": company.id,
            "partner_id": partner.id,
            "journal_id": journal.id,
            "currency_id": currency.id if currency else False,
            "invoice_user_id": salesperson.id,      # permanent: set salesperson
            "invoice_line_ids": line_cmds,
            "narration": narration_html or False,   # permanent: always set Terms + Notes
        }
        # Optional print fields
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
            allowed_company_ids=[company.id],      # UI-like visibility
        ).create(move_vals)

        move.action_post()
        self.write({"move_id": move.id, "state": "posted"})
        return move
