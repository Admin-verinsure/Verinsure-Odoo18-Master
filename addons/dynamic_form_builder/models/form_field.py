from odoo import models, fields
import ast

class DynamicFormField(models.Model):
    _name = "dynamic.form.field"
    _description = "Dynamic Form Field"

    form_id = fields.Many2one("dynamic.form", required=True, ondelete="cascade")
    label = fields.Char(required=True)
    field_type = fields.Selection([
        ("char", "Text"),
        ("select", "Dropdown"),
    ], required=True)

    option_source = fields.Selection([
        ("manual", "Manual"),
        ("model", "From Model"),
    ], default="manual")

    option_values = fields.Text("Options (Manual)")
    option_model_id = fields.Many2one("ir.model", string="Source Model")
    option_domain = fields.Char(default="[]")
    option_label_field = fields.Char(default="name")
    option_value_field = fields.Char(default="id")

    def get_select_options(self):
        self.ensure_one()

        if self.option_source == "manual":
            return [
                {"value": v.strip(), "label": v.strip()}
                for v in (self.option_values or "").split("\n")
                if v.strip()
            ]

        if self.option_source == "model" and self.option_model_id:
            domain = ast.literal_eval(self.option_domain or "[]")
            records = self.env[self.option_model_id.model].sudo().search(domain)
            return [
                {
                    "value": getattr(r, self.option_value_field),
                    "label": getattr(r, self.option_label_field),
                }
                for r in records
            ]
        return []