from odoo import api, fields, models

class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    x_insurance_doc = fields.Boolean(string="Insurance Document", index=True, default=False)
    x_club_id = fields.Many2one("res.partner", string="Club", index=True)
    x_owner_user_id = fields.Many2one("res.users", string="Owner", index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("x_insurance_doc"):
                vals.setdefault("x_owner_user_id", self.env.user.id)

            if vals.get("x_insurance_doc") and vals.get("res_model") == "insurance.details" and vals.get("res_id"):
                policy = self.env["insurance.details"].browse(vals["res_id"])
                if policy.exists():
                    vals.setdefault("x_club_id", policy.x_club_id.id or False)

        return super().create(vals_list)
