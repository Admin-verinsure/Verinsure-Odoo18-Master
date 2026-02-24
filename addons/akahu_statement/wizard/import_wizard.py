from odoo import models, fields

class AkahuImportWizard(models.TransientModel):
    _name = "akahu.import.wizard"
    _description = "Import Akahu Transactions"

    journal_id = fields.Many2one(
        'account.journal',
        domain="[('type','=','bank')]",
        required=True
    )

    def action_import(self):
        result = self.env['akahu.statement.engine'].fetch_and_reconcile(
            self.journal_id.id
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Akahu Import Completed',
                'message': f"Created: {result['created']} | Reconciled: {result['matched']}",
                'type': 'success',
            }
        }
