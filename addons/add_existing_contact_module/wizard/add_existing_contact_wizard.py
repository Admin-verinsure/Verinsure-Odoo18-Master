
from odoo import models, fields, api


class AddExistingContactWizard(models.TransientModel):
    _name = 'add.existing.contact.wizard'
    _description = 'Add Existing Contact Wizard'

    partner_id = fields.Many2one('res.partner', string='Parent Contact')
    contact_ids = fields.Many2many('res.partner', string='Existing Contacts')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('default_partner_id'):
            res['partner_id'] = self.env.context.get('default_partner_id')
        return res

    def action_add_contacts(self):
        self.ensure_one()

        contacts = self.contact_ids.filtered(
            lambda c: c.id != self.partner_id.id
        )

        contacts.write({
            'parent_id': self.partner_id.id
        })

        return {'type': 'ir.actions.act_window_close'}
