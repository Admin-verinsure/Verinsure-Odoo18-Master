# invoice_poc/models/invoice_poc.py
from odoo import models, fields, api
import json

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

    # ---------- helpers ----------
    @api.model
    def _find_partner(self, email=None, name=None):
        Partner = self.env["res.partner"]
        dom = []
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
            # Create a minimal customer if not found (handy for POC)
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
        if name:
            j = Journal.search([("name", "=", name)], limit=1)
            if j:
                return j
        j = Journal.search([("type", "=", "sale")], limit=1)
        if not j:
            # Create a simple Sales journal if none exists (POC convenience)
            j = Journal.create({
                "name": "Sales",
                "code": "SAJ",
                "type": "sale",
                "company_id": self.env.company.id,
            })
        return j

    @api.model
    def _find_taxes(self, names=None):
        names = names or []
        if not names:
            return [(6, 0, [])]
        taxes = self.env["account.tax"].search([("name", "in", names)])
        return [(6, 0, taxes.ids)]

    @api.model
    def _fallback_income_account(self):
        return self.env["account.account"].search([("account_type", "=", "income")], limit=1)

    # ---------- main action ----------
    def action_create_and_post_invoice(self):
        """Create + post an out_invoice from stored JSON payload."""
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")

        # Header bits
        customer = data.get("customer", {}) or {}
        partner = self._find_partner(
            email=customer.get("email"),
            name=customer.get("name"),
        )
        currency = self._find_currency(data.get("currency") or "INR")
        journal = self._find_journal(data.get("journal"))

        # Lines
        lines_in = data.get("lines") or []
        if not lines_in:
            raise ValueError("At least one line is required")
        income_acct = self._fallback_income_account()

        line_cmds = []
        for l in lines_in:
            taxes_cmd = self._find_taxes(l.get("tax_names"))
            line_vals = {
                "name": l.get("description") or l.get("name") or "Item",
                "quantity": float(l.get("qty") or 1.0),
                "price_unit": float(l.get("unit_price") or 0.0),
                "tax_ids": taxes_cmd,
                # For POC we use account-based lines (no product required)
                "account_id": income_acct.id,
            }
            line_cmds.append((0, 0, line_vals))

        move_vals = {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "journal_id": journal.id,
            "currency_id": currency.id if currency else False,
            "invoice_line_ids": line_cmds,
        }
        if data.get("ref"):
            move_vals["ref"] = data["ref"]
        if data.get("invoice_date"):
            move_vals["invoice_date"] = data["invoice_date"]
        if data.get("due_date"):
            move_vals["invoice_date_due"] = data["due_date"]
        if data.get("note"):
            move_vals["narration"] = data["note"]

        move = self.env["account.move"].create(move_vals)
        move.action_post()

        self.write({"move_id": move.id, "state": "posted"})
        return move
