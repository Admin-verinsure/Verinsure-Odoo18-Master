from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class InsuranceDocument(models.Model):
    _name = "insurance.document"
    _description = "Insurance Document"
    _order = "create_date desc"

    name = fields.Char(string="Title", required=True)
    policy_id = fields.Many2one("insurance.details", string="Policy", index=True, ondelete="cascade")
    club_id = fields.Many2one("res.partner", string="Club", index=True)
    owner_user_id = fields.Many2one("res.users", string="Owner", default=lambda self: self.env.user, index=True, readonly=True)

    datas = fields.Binary(string="File", required=True, attachment=True)
    datas_fname = fields.Char(string="Filename")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Stamp owner
            vals.setdefault("owner_user_id", self.env.user.id)

            # Inherit club from policy if not provided
            policy_id = vals.get("policy_id")
            if policy_id and not vals.get("club_id"):
                policy = self.env["insurance.details"].browse(policy_id)
                if policy.exists() and policy.x_club_id:
                    vals["club_id"] = policy.x_club_id.id

            # If user belongs to clubs, require a club (directly or via policy)
            if self.env.user.x_club_ids and not vals.get("club_id"):
                raise ValidationError(_("Please select a Policy (with Club) or choose a Club for this document."))

        return super().create(vals_list)

    def write(self, vals):
        # If policy changes and club not explicitly set, sync club from policy
        if "policy_id" in vals and "club_id" not in vals:
            policy = self.env["insurance.details"].browse(vals.get("policy_id")) if vals.get("policy_id") else False
            if policy and policy.exists() and policy.x_club_id:
                vals["club_id"] = policy.x_club_id.id
            else:
                # If policy cleared and user has clubs, keep existing club (don't blank it automatically)
                pass

        # If user has clubs, prevent saving without club
        if "club_id" in vals and not vals.get("club_id") and self.env.user.x_club_ids:
            raise ValidationError(_("Club is required for users associated with a club."))

        return super().write(vals)
