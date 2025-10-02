# invoice_poc/models/invoice_poc.py
from odoo import models, fields, api
import json

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

    # ---------- helpers ----------
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
        """Use an existing SALE journal in the current user's company (no auto-create)."""
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
    taxes = self.env['account.tax'].with_context(active_test=False).search([
        ('name', 'in', names),
        ('company_id', '=', self.env.user.company_id.id),
        ('type_tax_use', 'in', ['sale','none']),
    ])
    return [(6, 0, taxes.ids)]
    @api.model
    def _fallback_income_account(self):
        return self.env["account.account"].search(
            [("account_type", "=", "income")], limit=1
        )

    @api.model
    def _find_payment_term(self, name=None):
        """Resolve payment term by exact name (e.g., 'Immediate', '30 Days')."""
        if not name:
            return self.env['account.payment.term'].browse()
        return self.env['account.payment.term'].search([('name', '=', name)], limit=1)

    # ---------- main action ----------
    def action_create_and_post_invoice(self):
        """Create + post an out_invoice from stored JSON payload (UI-like)."""
        self.ensure_one()
        data = json.loads(self.payload_json or "{}")

        # Match UI company & salesperson
        company_id = self.env.user.company_id.id

        # Header
        customer = data.get("customer", {}) or {}
        partner = self._find_partner(
            email=customer.get("email"),
            name=customer.get("name"),
        )
        currency = self._find_currency(data.get("currency") or "INR")
        journal = self._find_journal(data.get("journal"))
        payment_term = self._find_payment_term(data.get("payment_term"))

        # Lines
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
            "company_id": company_id,                       # ensure right company
            "partner_id": partner.id,
            "journal_id": journal.id if journal else False, # existing sale journal
            "currency_id": currency.id if currency else False,
            "invoice_user_id": self.env.user.id,            # shows under “My Invoices”
            "invoice_line_ids": line_cmds,
        }
        # Optional header/printing fields (to satisfy your template)
        if data.get("ref"):
            move_vals["ref"] = data["ref"]                            # Customer Reference
        if data.get("invoice_date"):
            move_vals["invoice_date"] = data["invoice_date"]
        if data.get("due_date"):
            move_vals["invoice_date_due"] = data["due_date"]          # Due Date block
        if data.get("note"):
            move_vals["narration"] = data["note"]                     # Terms & Conditions block
        if data.get("payment_reference"):
            move_vals["payment_reference"] = data["payment_reference"]# Payment Communication
        if payment_term:
            move_vals["invoice_payment_term_id"] = payment_term.id    # Payment Term block

        # Create with the same context the UI action uses
        move = self.env["account.move"].with_context(
            default_move_type="out_invoice",
            allowed_company_ids=[company_id],
        ).create(move_vals)

        move.action_post()  # same as Confirm button
        self.write({"move_id": move.id, "state": "posted"})
        return move
