from odoo import models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_open_customer_statement(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Customer Statement',
            'res_model': 'customer.statement.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id}
        }
