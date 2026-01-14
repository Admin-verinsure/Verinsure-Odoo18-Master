from odoo import fields, models

class ResUsers(models.Model):
    _inherit = "res.users"

    # Clubs the user belongs to (generic res.partner)
    x_club_ids = fields.Many2many(
        "res.partner",
        "res_users_club_rel",
        "user_id",
        "partner_id",
        string="Clubs",
    )
