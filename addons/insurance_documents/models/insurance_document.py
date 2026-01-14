from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class InsuranceDocument(models.Model):
    _name = "insurance.document"
    _description = "Insurance Document"
    _order = "create_date desc"

    name = fields.Char(string="Title", required=True)
    policy_id = fields.Many2one("insurance.details", string="Policy", index=True, ondelete="cascade")
    club_id = fields.Many2one("res.partner", string="Club", index=True)
    owner_user_id = fields.Many2one("res.users", string="Owner", default=lambda self: self.env.user, index=True)

    datas = fields.Binary(string="File", required=True, attachment=True)
    datas_fname = fields.Char(string="Filename")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # If policy is provided, inherit club from policy unless explicitly set
            if vals.get("policy_id") and not vals.get("club_id"):
                policy = self.env["insurance.details"].browse(vals["policy_id"])
                if policy.exists() and policy.x_club_id:
                    vals["club_id"] = policy.x_club_id.id

            # If user has clubs, force selecting club (directly or via policy)
            if self.env.user.x_club_ids and not vals.get("club_id"):
                raise ValidationError(_("Please select a Policy (with Club) or choose a Club for this document."))

            # Ensure owner is stamped
            vals.setdefault("owner_user_id", self.env.user.id)

        return super().create(vals_list)

    @api.constrains("policy_id", "club_id")
    def _sync_club_from_policy(self):
        for rec in self:
            if rec.policy_id and rec.policy_id.x_club_id and rec.club_id != rec.policy_id.x_club_id:
                # Keep club aligned with policy club
                rec.club_id = rec.policy_id.x_club_id
