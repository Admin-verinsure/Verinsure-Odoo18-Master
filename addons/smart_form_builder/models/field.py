from odoo import api, fields, models
from odoo.tools.safe_eval import safe_eval

class SmartFormField(models.Model):
    _name = "smart.form.field"
    _description = "Smart Form Field"
    _order = "sequence, id"

    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True)
    help = fields.Char()
    required = fields.Boolean(default=False)

    field_type = fields.Selection([
        ("char", "Text"),
        ("text", "Long Text"),
        ("select", "Dropdown"),
        ("radio", "Radio"),
        ("checkbox", "Checkbox"),
    ], required=True, default="char")

    # Options
    option_source = fields.Selection([
        ("manual", "Manual"),
        ("model", "From Database (Model)"),
    ], default="manual")

    option_values = fields.Text(help="One option per line. For value|label use value|label.")

    option_model_id = fields.Many2one("ir.model", string="Source Model")
    option_domain = fields.Char(string="Domain", help="Example: [('active','=',True)]")
    option_label_field = fields.Char(string="Label Field", default="name")
    option_value_field = fields.Char(string="Value Field", default="id")
    option_limit = fields.Integer(default=200)

    def _parse_domain(self):
        self.ensure_one()
        if not self.option_domain:
            return []
        try:
            return safe_eval(self.option_domain, {"uid": self.env.uid})
        except Exception:
            return []

    def get_dynamic_options(self):
        self.ensure_one()
        if self.option_source != "model" or not self.option_model_id:
            return []
        model_name = self.option_model_id.model
        domain = self._parse_domain()
        limit = self.option_limit or 200

        label_field = (self.option_label_field or "name").strip()
        value_field = (self.option_value_field or "id").strip()

        Model = self.env[model_name].sudo()
        recs = Model.search(domain, limit=limit)

        opts = []
        for r in recs:
            label = getattr(r, label_field, False)
            if label is False:
                label = r.display_name
            value = getattr(r, value_field, False)
            if value_field == "id":
                value = r.id
            opts.append({"value": value, "label": str(label)})
        return opts

    def get_manual_options(self):
        self.ensure_one()
        if not self.option_values:
            return []
        opts = []
        for line in (self.option_values or "").splitlines():
            line = (line or "").strip()
            if not line:
                continue
            if "|" in line:
                value, label = line.split("|", 1)
                opts.append({"value": value.strip(), "label": label.strip()})
            else:
                opts.append({"value": line, "label": line})
        return opts

    def get_options(self):
        self.ensure_one()
        if self.option_source == "model":
            return self.get_dynamic_options()
        return self.get_manual_options()
