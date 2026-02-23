from odoo import models, fields
import csv
import base64
import io

class BankImportWizard(models.TransientModel):
    _name = "bank.import.wizard"
    _description = "Bank Import Wizard"

    journal_id = fields.Many2one("account.journal", required=True)
    file = fields.Binary(required=True)
    filename = fields.Char()

    def action_import(self):
        data = base64.b64decode(self.file)
        file = io.StringIO(data.decode("utf-8"))
        reader = csv.DictReader(file)

        for row in reader:
            amount = float(row.get("amount", 0.0))
            partner_name = row.get("partner")

            partner = self.env["res.partner"].search(
                [("name", "=", partner_name)],
                limit=1,
            )

            self.env["account.bank.statement.line"].create({
                "date": row.get("date"),
                "payment_ref": row.get("reference"),
                "amount": amount,
                "partner_id": partner.id if partner else False,
                "journal_id": self.journal_id.id,
            })

        return {"type": "ir.actions.act_window_close"}
