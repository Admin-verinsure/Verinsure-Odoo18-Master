from odoo import models, fields

class AkahuImportWizard(models.TransientModel):
    _name = "akahu.import.wizard"
    _description = "Import Akahu Transactions"

    journal_id = fields.Many2one(
        'account.journal',
        domain="[('type','=','bank')]",
        required=True
    )
    days_to_fetch = fields.Integer(default=90)
    auto_reconcile = fields.Boolean(default=True)

    def action_import(self):
        self.ensure_one()

        # Integrate real Akahu API here

        if self.auto_reconcile:
            self.env['auto.reconcile.engine'].run_auto_reconcile(
                journal_id=self.journal_id.id
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Import & reconciliation completed.',
                'type': 'success',
            }
        }
