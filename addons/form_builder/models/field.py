from odoo import models, fields
from odoo.tools.safe_eval import safe_eval

class SmoothFormField(models.Model):
    _name = "smooth.form.field"
    _description = "Smooth Form Field"
    _order = "sequence, id"

    form_id = fields.Many2one("smooth.form", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True)

    field_type = fields.Selection([
        ("text","Text"),
        ("number","Number"),
        ("date","Date"),
        ("textarea","Textarea"),
        ("select","Select"),
        ("radio","Radio"),
        ("checkbox","Checkbox"),
    ], default="text", required=True)

    required = fields.Boolean(default=False)

    option_source = fields.Selection([("manual","Manual"),("model","From Model")], default="manual")
    option_values = fields.Text(help="One option per line. For 'value|label' format, use value|label")
    option_model_id = fields.Many2one("ir.model", string="Source Model")
    option_domain = fields.Char(string="Domain", help="Example: [('active','=',True)]")
    option_label_field = fields.Char(string="Label Field", default="name")
    option_value_field = fields.Char(string="Value Field", default="id")
    option_limit = fields.Integer(string="Limit", default=200)

    def _parse_manual_options(self):
        opts = []
        for line in (self.option_values or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                v, l = line.split("|", 1)
                opts.append({"value": v.strip(), "label": l.strip()})
            else:
                opts.append({"value": line, "label": line})
        return opts

    def get_options(self):
        self.ensure_one()
        if self.field_type not in ("select","radio","checkbox"):
            return []
        if self.option_source == "manual" or not self.option_model_id:
            return self._parse_manual_options()

        model = self.option_model_id.model
        dom = []
        if self.option_domain:
            try:
                dom = safe_eval(self.option_domain, {"uid": self.env.uid})
            except Exception:
                dom = []
        label_f = (self.option_label_field or "name").strip()
        value_f = (self.option_value_field or "id").strip()
        limit = self.option_limit or 200

        recs = self.env[model].sudo().search(dom, limit=limit)
        opts = []
        for r in recs:
            label = getattr(r, label_f, False)
            if label is False:
                label = r.display_name
            val = getattr(r, value_f, False)
            if value_f == "id":
                val = r.id
            opts.append({"value": val, "label": label})
        return opts
