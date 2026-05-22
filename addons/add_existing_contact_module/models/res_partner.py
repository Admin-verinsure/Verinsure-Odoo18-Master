
from odoo import models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_open_add_existing_contact_wizard(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Existing Contact',
            'res_model': 'add.existing.contact.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
            }
        }
