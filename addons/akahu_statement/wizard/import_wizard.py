from odoo import models, fields

class AkahuImportWizard(models.TransientModel):
    _name = "akahu.import.wizard"
    _description = "Import Akahu Transactions"

    journal_id = fields.Many2one(
        'account.journal',
        domain="[('type','=','bank')]",
        required=True
    )

    auto_reconcile = fields.Boolean(default=True)

    def action_import(self):
        result = self.env['akahu.engine'].fetch_and_reconcile(
            self.journal_id.id,
            self.auto_reconcile
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Akahu Import Completed',
                'message': f"Created: {result['created']} | Auto Reconciled: {result['matched']}",
                'type': 'success',
            }
        }
