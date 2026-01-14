from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class InsuranceDocument(models.Model):
    _name = "insurance.document"
    _description = "Insurance Document"
    _order = "create_date desc"

    name = fields.Char(string="Title", required=True)
    policy_id = fields.Many2one("insurance.details", string="Policy", index=True, ondelete="cascade")
    club_id = fields.Many2one("res.partner", string="Club", index=True)
    owner_user_id = fields.Many2one(
        "res.users",
        string="Owner",
        default=lambda self: self.env.user,
        index=True,
        readonly=True,
    )

    datas = fields.Binary(string="File", required=True, attachment=True)
    datas_fname = fields.Char(string="Filename")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("owner_user_id", self.env.user.id)

            policy_id = vals.get("policy_id")
            if policy_id and not vals.get("club_id"):
                policy = self.env["insurance.details"].browse(policy_id)
                if policy.exists() and getattr(policy, "x_club_id", False):
                    vals["club_id"] = policy.x_club_id.id

            if self.env.user.x_club_ids and not vals.get("club_id"):
                raise ValidationError(_("Please select a Policy (with Club) or choose a Club for this document."))

        return super().create(vals_list)
