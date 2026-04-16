from odoo import models, api

class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def create(self, vals):
        user = super().create(vals)
        if not user.share:
            group = self.env.ref('clean_access_manager.group_employee')
            user.groups_id = [(4, group.id)]
        return user
