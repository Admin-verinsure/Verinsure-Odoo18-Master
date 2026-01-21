from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import json

class FormBuilderField(models.Model):
    _inherit = 'form.builder.field'

    # ---- Dynamic dropdown source ----
    is_dynamic_options = fields.Boolean(
        string="Dynamic Options (DB)",
        help="When enabled, dropdown/radio/checkbox options are loaded from an Odoo model."
    )

    dynamic_model_id = fields.Many2one(
        'ir.model',
        string="Source Model",
        help="Odoo model that provides options (e.g. club.club, res.partner)."
    )

    dynamic_domain = fields.Char(
        string="Domain",
        help="Optional Odoo domain (python-like list) as text. Example: [('active','=',True)]"
    )

    dynamic_label_field_id = fields.Many2one(
        'ir.model.fields',
        string="Label Field",
        domain="[('model_id', '=', dynamic_model_id), ('ttype', 'in', ['char', 'text', 'selection'])]",
        help="Field to show as option label."
    )

    dynamic_value_field_id = fields.Many2one(
        'ir.model.fields',
        string="Value Field",
        domain="[('model_id', '=', dynamic_model_id), ('ttype', 'in', ['integer', 'many2one', 'char'])]",
        help="Field used as the stored value. Typically 'id' or an external code."
    )

    dynamic_limit = fields.Integer(string="Limit", default=200)

    @api.constrains('is_dynamic_options', 'field_type', 'dynamic_model_id')
    def _check_dynamic_options_compatibility(self):
        for rec in self:
            if rec.is_dynamic_options:
                if rec.field_type not in ('select', 'radio', 'checkbox'):
                    raise ValidationError(_("Dynamic Options can be used only with Select/Radio/Checkbox field types."))
                if not rec.dynamic_model_id:
                    raise ValidationError(_("Please select a Source Model for dynamic options."))

    def _get_dynamic_domain(self):
        """Safely parse domain string to python list."""
        self.ensure_one()
        if not self.dynamic_domain:
            return []
        try:
            # domain is stored as python-literal list string. Example: [('active','=',True)]
            return json.loads(self.dynamic_domain) if self.dynamic_domain.strip().startswith('[') and self.dynamic_domain.strip().endswith(']') and '"' in self.dynamic_domain else eval(self.dynamic_domain, {'__builtins__': {}})
        except Exception:
            # fall back to empty domain to avoid breaking public rendering
            return []

    def get_dynamic_options(self):
        """Helper used by controller and server-side rendering."""
        self.ensure_one()
        if not self.is_dynamic_options or not self.dynamic_model_id:
            return []

        model = self.dynamic_model_id.model
        label_field = (self.dynamic_label_field_id.name or 'name') if self.dynamic_label_field_id else 'name'
        value_field = (self.dynamic_value_field_id.name or 'id') if self.dynamic_value_field_id else 'id'

        domain = self._get_dynamic_domain()
        records = self.env[model].sudo().search(domain, limit=self.dynamic_limit)

        options = []
        for r in records:
            options.append({
                'value': str(getattr(r, value_field) if value_field != 'id' else r.id),
                'label': str(getattr(r, label_field) if hasattr(r, label_field) else (r.display_name or r.name)),
            })
        return options
