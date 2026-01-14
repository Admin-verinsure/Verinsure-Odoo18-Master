from odoo import fields, models

class ResUsers(models.Model):
    _inherit = "res.users"

    # A user can belong to multiple clubs (we use res.partner as a generic club entity)
    x_club_ids = fields.Many2many(
        "res.partner",
        "res_users_club_rel",
        "user_id",
        "partner_id",
        string="Clubs",
    )
