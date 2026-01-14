
from odoo import fields, models

class ResUsers(models.Model):
    _inherit = "res.users"

    x_club_ids = fields.Many2many(
        "res.partner",
        "res_users_club_rel",
        "user_id",
        "partner_id",
        string="Clubs",
    )
