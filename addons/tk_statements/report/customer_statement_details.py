# -*- coding: utf-8 -*-
from odoo import models, api


class CustomerStatementPDFReport(models.AbstractModel):
    """
    Abstract model that bridges the QWeb PDF engine to the wizard's
    _get_statement_data() helper.  All business logic lives in the wizard;
    this class only fetches and forwards the data.
    """
    _name = 'report.tk_statements.customer_report_template'
    _description = 'Customer Statement PDF Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        """
        Called by Odoo's report engine.  `data` carries {'wizard_id': int}.
        We load the wizard and delegate to its shared data builder.
        """
        wizard_id = (data or {}).get('wizard_id')
        if not wizard_id:
            # Fallback: if called directly from docids (binding context)
            wizard_id = docids[0] if docids else None

        wizard = self.env['customer.statement.wizard'].browse(wizard_id)
        if not wizard.exists():
            return {}

        return wizard._get_statement_data()
