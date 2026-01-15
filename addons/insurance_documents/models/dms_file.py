from odoo import api, models

class DmsFile(models.Model):
    _inherit = "dms.file"

    @api.model_create_multi
    def create(self, vals_list):
        # Auto-link files created from the policy smart button
        ctx = self.env.context
        def_res_model = ctx.get("default_res_model")
        def_res_id = ctx.get("default_res_id")

        for vals in vals_list:
            if def_res_model and not vals.get("res_model"):
                vals["res_model"] = def_res_model
            if def_res_id and not vals.get("res_id"):
                vals["res_id"] = def_res_id

        return super().create(vals_list)
