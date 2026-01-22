from odoo import api, fields, models


class SmartFormSelectFieldWizard(models.TransientModel):
    _name = "smart.form.field.select.wizard"
    _description = "Configure Select Field"

    field_id = fields.Many2one("smart.form.field", required=True, ondelete="cascade")

    option_values = fields.Text(
        string="Options",
        help="One option per line. Use 'value|label' or just 'label'.",
    )

    is_dynamic = fields.Boolean(string="Dynamic Options (DB)")
    option_model_id = fields.Many2one("ir.model", string="Source Model")
    model_name = fields.Char(string="Model Name", compute="_compute_model_name", readonly=True)
    option_domain = fields.Char(string="Domain", default="[('active','=',True)]")
    option_label_field = fields.Many2one(
        "ir.model.fields",
        string="Label Field",
        domain="[('model_id','=',option_model_id)]",
    )
    option_value_field = fields.Many2one(
        "ir.model.fields",
        string="Value Field",
        domain="[('model_id','=',option_model_id)]",
    )
    option_limit = fields.Integer(default=10000)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        field_id = self.env.context.get("default_field_id")
        if field_id:
            f = self.env["smart.form.field"].browse(field_id)
            res.update({
                "field_id": f.id,
                "option_values": f.option_values or False,
                "is_dynamic": (f.option_source == "model"),
                "option_model_id": f.option_model_id.id if f.option_model_id else False,
                "option_domain": f.option_domain or "[('active','=',True)]",
                "option_label_field": f.option_label_field.id if f.option_label_field else False,
                "option_value_field": f.option_value_field.id if f.option_value_field else False,
                "option_limit": f.option_limit or 10000,
            })
        return res

    def action_save(self):
        self.ensure_one()
        self.field_id.write({
            "option_values": self.option_values or False,
            "option_source": "model" if self.is_dynamic else "manual",
            "option_model_id": self.option_model_id.id if self.is_dynamic and self.option_model_id else False,
            "option_domain": self.option_domain if self.is_dynamic else False,
            "option_label_field": self.option_label_field.id if self.is_dynamic and self.option_label_field else False,
            "option_value_field": self.option_value_field.id if self.is_dynamic and self.option_value_field else False,
            "option_limit": self.option_limit if self.is_dynamic else 10000,
        })
        return {"type": "ir.actions.act_window_close"}

@api.depends("option_model_id")
def _compute_model_name(self):
    for rec in self:
        rec.model_name = rec.option_model_id.model or ""
