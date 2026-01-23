from odoo import api, fields, models
from odoo.tools.safe_eval import safe_eval


class SmartFormField(models.Model):
    _rec_name = "label"
    _name = "smart.form.field"
    _description = "Smart Form Field"
    _order = "sequence, id"

    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Technical Name", help="Optional. Used as HTML name; if empty, field_<id> is used.")
    label = fields.Char(required=True)
    required = fields.Boolean(default=False)

    field_type = fields.Selection([
        ("text", "Text"),
        ("textarea", "Textarea"),
        ("select", "Select"),
        ("radio", "Radio"),
        ("checkbox", "Checkbox"),
        ("file", "File Upload"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("number", "Numeric"),
        ("subheading", "Sub Heading"),
    ], default="text", required=True)

    # Options
    option_source = fields.Selection([
        ("manual", "Manual"),
        ("model", "From Database (Model)"),
    ], default="manual")

    option_values = fields.Text(string="Manual Options", help="One option per line. Use 'value|label' or just 'label'.")

    option_model_id = fields.Many2one("ir.model", string="Source Model")
    option_domain = fields.Char(string="Domain", help="Python domain, e.g. [('active','=',True)]")
    option_label_field = fields.Many2one(
        "ir.model.fields",
        string="Label Field",
        domain="[('model_id','=',option_model_id),('ttype','in',('char','text','html'))]",
    )
    option_value_field = fields.Many2one(
        "ir.model.fields",
        string="Value Field",
        domain="[('model_id','=',option_model_id)]",
    )
    option_limit = fields.Integer(default=10000)

    def _parse_manual_options(self):
        self.ensure_one()
        out = []
        if not self.option_values:
            return out
        for line in self.option_values.splitlines():
            line = (line or "").strip()
            if not line:
                continue
            if "|" in line:
                v, l = line.split("|", 1)
                out.append({"value": v.strip(), "label": l.strip()})
            else:
                out.append({"value": line, "label": line})
        return out

    def get_options(self):
        """Return a list of {value,label} for this field."""
        self.ensure_one()

        if self.field_type not in ("select", "radio", "checkbox"):
            return []

        # Dynamic options from a model
        if self.option_source == "model" and self.option_model_id:
            model = self.option_model_id.model
            domain = []
            if self.option_domain:
                try:
                    domain = safe_eval(self.option_domain, {"uid": self.env.uid})
                except Exception:
                    domain = []

            label_field = self.option_label_field.name if self.option_label_field else "name"
            value_field = self.option_value_field.name if self.option_value_field else "id"

            limit = min(self.option_limit or 10000, 10000)
            recs = self.env[model].sudo().search(domain, limit=limit)
            res = []
            for r in recs:
                label = getattr(r, label_field, False) or r.display_name
                value = getattr(r, value_field, False)
                if value_field == "id":
                    value = r.id
                res.append({"value": value, "label": str(label)})
            return res

        # Manual options
        return self._parse_manual_options()

    def action_open_select_config(self):
        """Open the select field configuration wizard."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Configure Select Field",
            "res_model": "smart.form.field.select.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_field_id": self.id},
        }
