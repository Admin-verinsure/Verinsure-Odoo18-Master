
from odoo import models, fields, api


class AddExistingContactWizard(models.TransientModel):
    _name = 'add.existing.contact.wizard'
    _description = 'Add Existing Contact Wizard'

    partner_id = fields.Many2one('res.partner', string='Parent Contact', readonly=True)
    contact_ids = fields.Many2many(
        'res.partner',
        relation='add_existing_contact_wizard_partner_rel',
        column1='wizard_id',
        column2='partner_id',
        string='Existing Contacts',
        domain="[('id', '!=', partner_id), ('parent_id', '=', False), ('is_company', '=', False)]",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('default_partner_id'):
            res['partner_id'] = self.env.context.get('default_partner_id')
        return res

    def action_add_contacts(self):
        self.ensure_one()

        if not self.partner_id:
            return {'type': 'ir.actions.act_window_close'}

        contacts = self.contact_ids.filtered(
            lambda c: c.id != self.partner_id.id and not c.parent_id
        )

        contacts.write({
            'parent_id': self.partner_id.id
        })

        return {'type': 'ir.actions.act_window_close'}
