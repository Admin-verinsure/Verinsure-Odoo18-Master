from odoo import api, fields, models

class DmsFile(models.Model):
    _inherit = "dms.file"

    x_policy_id = fields.Many2one("insurance.details", string="Insurance Policy", index=True)

    @api.model_create_multi
    def create(self, vals_list):
        ctx = self.env.context
        policy_id = ctx.get("default_x_policy_id") or ctx.get("x_policy_id")
        # Sometimes DMS upload uses default_res_model/default_res_id; support it only if model matches
        if not policy_id and ctx.get("default_res_model") == "insurance.details":
            policy_id = ctx.get("default_res_id")

        for vals in vals_list:
            if policy_id and not vals.get("x_policy_id"):
                vals["x_policy_id"] = int(policy_id)

            # Sync generic linkage
            if vals.get("x_policy_id"):
                vals.setdefault("res_model", "insurance.details")
                vals.setdefault("res_id", vals["x_policy_id"])

        return super().create(vals_list)

    def write(self, vals):
        if "x_policy_id" in vals and vals.get("x_policy_id"):
            vals.setdefault("res_model", "insurance.details")
            vals.setdefault("res_id", vals["x_policy_id"])
        return super().write(vals)
