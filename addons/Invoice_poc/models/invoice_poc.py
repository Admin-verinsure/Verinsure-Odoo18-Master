# invoice_poc/models/invoice_poc.py
# ──────────────────────────────────────────────────────────────────────────────
# This model stores an external JSON payload and turns it into a posted
# customer invoice (account.move with move_type='out_invoice').
# The method action_create_and_post_invoice() is the entrypoint that:
#   1) Parses payload_json
#   2) Resolves partner/currency/journal/payment term
#   3) Builds invoice lines from the payload
#   4) Creates  the invoice,
# ──────────────────────────────────────────────────────────────────────────────

from odoo import models, fields, api
import json

class InvoicePocPayload(models.Model):
    _name = "invoice.poc.payload"                 # Technical model name
    _description = "Stored payloads for invoice POC"

    # ============== INPUT container  ==============
    ext_id = fields.Char(index=True)              # Optional external reference (for idempotency/tracing)
    payload_json = fields.Text(required=True)     # Raw JSON string that contains the invoice data

    # ============== Trace/Result ==============
    move_id = fields.Many2one(                    # The created invoice (account.move)
        "account.move",
        string="Created Invoice"
    )
    state = fields.Selection(                     # Lifecycle of this payload processing
        [("new", "New"), ("posted", "Posted"), ("error", "Error")],
        default="new",
        required=True
    )
    error_message = fields.Text()                 # If something fails, store message here

    # -------------------------------------------------------------------------
    # Helpers to resolve Odoo records used by the invoice
    # -------------------------------------------------------------------------

    @api.model
    def _find_partner(self, email=None, name=None):
        """Find or create the invoice partner (customer)."""
        Partner = self.env["res.partner"]
        # Build a domain (search filter) depending on what the payload provided
        if email and name:
            dom = ["|", ("email", "=", email), ("name", "=", name)]
        elif email:
            dom = [("email", "=", email)]
        elif name:
            dom = [("name", "=", name)]
        else:
            # We need at least one of email/name to identify a customer
            raise ValueError("Provide partner email or name")

        partner = Partner.search(dom, limit=1)    # Try to find an existing partner
        if not partner:
            # For a POC we can auto-create a minimal customer if missing
            partner = Partner.create({
                "name": name or email,
                "email": email,
                "customer_rank": 1,               # Mark as a customer
            })
        return partner

    @api.model
    def _find_currency(self, code="INR"):
        """Resolve currency (e.g., 'INR', 'USD')."""
        return self.env["res.currency"].search([("name", "=", code)], limit=1)

    @api.model
    def _find_journal(self, name=None):
        """
        Resolve a SALE journal in the current user company.
        If a 'name' is provided, try that first (still in same company).
        We do NOT auto-create here—mirrors normal UI behavior.
        """
        Journal = self.env["account.journal"]
        company_id = self.env.user.company_id.id

        if name:
            j = Journal.search([
                ("name", "=", name),
                ("company_id", "=", company_id),
            ], limit=1)
            if j:
                return j

        # Fall back to any SALE journal of the same company
        return Journal.search([
            ("type", "=", "sale"),
            ("company_id", "=", company_id),
        ], limit=1)

    @api.model
    def _find_taxes(self, names=None):
        """
        Resolve tax names (list of strings) to a many2many command for line.tax_ids.
        If you need company scoping or inactive taxes, enhance this search.
        """
        names = names or []
        if not names:
            return [(6, 0, [])]                   # Set empty m2m (no taxes)
        taxes = self.env["account.tax"].search([("name", "in", names)])
        return [(6, 0, taxes.ids)]               # (6,0,ids) = replace with these IDs

    @api.model
    def _fallback_income_account(self):
        """Provide an income account when we don't use products (POC simplification)."""
        return self.env["account.account"].search(
            [("account_type", "=", "income")], limit=1
        )

    @api.model
    def _find_payment_term(self, name=None):
        """Resolve payment term by exact name (e.g., 'Immediate', '30 Days')."""
        if not name:
            return self.env['account.payment.term'].browse()  # Empty recordset if none given
        return self.env['account.payment.term'].search([('name', '=', name)], limit=1)

    # -------------------------------------------------------------------------
    # Main: turn the stored JSON into a posted customer invoice
    # -------------------------------------------------------------------------
    def action_create_and_post_invoice(self):
        """
        Create + post an out_invoice from stored JSON payload (UI-like).
        Steps:
          1) Parse JSON
          2) Resolve header objects (partner/currency/journal/payment term)
          3) Build invoice line commands
          4) Create account.move with UI-like context
          5) Post (Confirm) the invoice
          6) Link back and mark as posted
        """
        self.ensure_one()                          # Sanity: run on exactly one payload record

        # 1) Parse external JSON input into a dict
        data = json.loads(self.payload_json or "{}")

        # Use the same company as the current user (mirrors UI behavior)
        company_id = self.env.user.company_id.id

        # 2) HEADER: resolve partner/currency/journal/payment term using helpers
        customer = data.get("customer", {}) or {}  # e.g. {"name": "...", "email": "..."}
        partner = self._find_partner(
            email=customer.get("email"),
            name=customer.get("name"),
        )
        currency = self._find_currency(data.get("currency") or "INR")
        journal = self._find_journal(data.get("journal"))
        payment_term = self._find_payment_term(data.get("payment_term"))

        # 3) LINES: payload must contain at least one entry
        lines_in = data.get("lines") or []
        if not lines_in:
            raise ValueError("At least one line is required")

        income_acct = self._fallback_income_account()  # single lookup reused for all lines

        # Build Odoo one2many commands for invoice_line_ids
        line_cmds = []
        for l in lines_in:
            line_cmds.append((0, 0, {                 # (0, 0, values) = create new line with these values
                "name": l.get("description") or l.get("name") or "Item",
                "quantity": float(l.get("qty") or 1.0),
                "price_unit": float(l.get("unit_price") or 0.0),
                "tax_ids": self._find_taxes(l.get("tax_names")),  # many2many command for taxes
                "account_id": income_acct.id,                     # account-based lines (no product needed)
            }))

        # 4) Assemble the account.move vals like the UI would
        move_vals = {
            "move_type": "out_invoice",               # Customer invoice
            "company_id": company_id,                 # Ensure it belongs to current company
            "partner_id": partner.id,                 # Customer
            "journal_id": journal.id if journal else False,
            "currency_id": currency.id if currency else False,
            "invoice_user_id": self.env.user.id,      # Salesperson (shows under “My Invoices”)
            "invoice_line_ids": line_cmds,            # Lines we built above
        }

        # Optional header/printing fields (only set if present in payload)
        if data.get("ref"):
            move_vals["ref"] = data["ref"]                           # Customer Reference
        if data.get("invoice_date"):
            move_vals["invoice_date"] = data["invoice_date"]         # Invoice Date
        if data.get("due_date"):
            move_vals["invoice_date_due"] = data["due_date"]         # Due Date (printed in report)
        if data.get("note"):
            move_vals["narration"] = data["note"]                    # Terms & Conditions (your template reads this)
        if data.get("payment_reference"):
            move_vals["payment_reference"] = data["payment_reference"]  # Payment Communication
        if payment_term:
            move_vals["invoice_payment_term_id"] = payment_term.id   # Payment Term (and details) on report

        # 5) Create the invoice with UI-like context and post it
        move = self.env["account.move"].with_context(
            default_move_type="out_invoice",          # Same default as the Accounting > Invoices action
            allowed_company_ids=[company_id],         # Ensure proper multi-company visibility
        ).create(move_vals)

        move.action_post()                            # Equivalent to the UI "Confirm" button

        # 6) Link invoice back to this payload and flip state
        self.write({"move_id": move.id, "state": "posted"})
        return move                                    # Allow caller (shell/API) to inspect the created move
