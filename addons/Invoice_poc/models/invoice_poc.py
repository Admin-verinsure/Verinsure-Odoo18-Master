# invoice_poc/models/invoice_poc.py
from odoo import models, fields, api
import json
import re

class InvoicePocPayload(models.Model):
    _name = "invoice.poc.payload"
    _description = "Stored payloads for invoice POC"

    ext_id = fields.Char(index=True)
    payload_json = fields.Text(required=True)

    move_id = fields.Many2one("account.move", string="Created Invoice")
    state = fields.Selection(
        [("new", "New"), ("posted", "Posted"), ("error", "Error")],
        default="new", required=True
    )
    error_message = fields.Text()

    # ---------------------- NEW: small helper ----------------------
    @api.model
    def _coerce_html(self, txt):
        """
        Ensure narration is valid HTML:
        - If txt already looks like HTML, return as-is.
        - Else wrap in <p> and keep line breaks with <br/>.
        """
        if not txt:
            return False
        # crude HTML detector: any angle bracket tag-like pattern
        if re.search(r"<[^>]+>", txt):
            return txt
        esc = (txt or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        esc = esc.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
        return f"<p>{esc}</p>"

    @api.model
    def _find_partner(self, email=None, name=None):
        Partner = self.env["res.partner"]
        if email and name:
            dom = ["|", ("email", "=", email), ("name", "=", name)]
        elif email:
            dom = [("email", "=", email)]
        elif name:
            dom = [("name", "=", name)]
        else:
            raise ValueError("Provide partner email or name")
        partner = Partner.search(dom, limit=1)
        if not partner:
            partner = Partner.create({
                "name": name or email,
                "email": email,
                "customer_rank": 1,
            })
        return partner

    @api.model
    def _find_currency(self, code="INR"):
        return self.env["res.currency"].search([("name", "=", code)], limit=1)

    @api.model
    def _find_journal(self, name=None):
        Journal = self.env["account.journal"]
        company_id = self.env.user.company_id.id
        if name:
            j = Journal.search([
                ("name", "=", name),
                ("company_id", "=", company_id),
            ], limit=1)
            if j:
                return j
        return Journal.search([
            ("type", "=", "sale"),
            ("company_id", "=", company_id),
        ], limit=1)

    @api.model
    def _find_taxes(self, names=None):
        names = names or []
        if not names:
            return [(6, 0, [])]
        taxes = self.env["account.tax"].search([("name", "in", names)])
        return [(6, 0, taxes.ids)]

    @api.model
    def _fallback_income_account(self):
        return self.env["account.account"].search(
            [("account_type", "=", "income")], limit=1
        )

    @api.model
    def _find_payment_term(self, name=None):
        if not name:
            return self.env['account.payment.term'].browse()
        return self.env['account.payment.term'].search([('name', '=', name)], limit=1)

    def action_create_and_post_invoice(self):
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")
        company_id = self.env.user.company_id.id

        customer = data.get("customer", {}) or {}
        partner = self._find_partner(
            email=customer.get("email"),
            name=customer.get("name"),
        )
        currency = self._find_currency(data.get("currency") or "INR")
        journal = self._find_journal(data.get("journal"))
        payment_term = self._find_payment_term(data.get("payment_term"))

        lines_in = data.get("lines") or []
        if not lines_in:
            raise ValueError("At least one line is required")

        income_acct = self._fallback_income_account()

        line_cmds = []
        for l in lines_in:
            line_cmds.append((0, 0, {
                "name": l.get("description") or l.get("name") or "Item",
                "quantity": float(l.get("qty") or 1.0),
                "price_unit": float(l.get("unit_price") or 0.0),
                "tax_ids": self._find_taxes(l.get("tax_names")),
                "account_id": income_acct.id,
            }))

        move_vals = {
            "move_type": "out_invoice",
            "company_id": company_id,
            "partner_id": partner.id,
            "journal_id": journal.id if journal else False,
            "currency_id": currency.id if currency else False,
            "invoice_user_id": self.env.user.id,
            "invoice_line_ids": line_cmds,
        }

        # ---------------------- UPDATED: narration sources ----------------------
        # Prefer explicit HTML, then note/terms (plain text OK), all coerced to HTML
        terms_html = data.get("terms_html") or data.get("note") or data.get("terms")
        if terms_html:
            move_vals["narration"] = self._coerce_html(terms_html)

        # Optional header/printing fields
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
            allowed_company_ids=[company_id],
        ).create(move_vals)

        move.action_post()
        self.write({"move_id": move.id, "state": "posted"})
        return move
