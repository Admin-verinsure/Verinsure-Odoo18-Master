from odoo import fields, models

class SmartFormBranchRule(models.Model):
    _name = "smart.form.branch.rule"
    _description = "Smart Form Branch Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    trigger_field_id = fields.Many2one("smart.form.field", required=True, ondelete="cascade",
                                       domain="[('form_id','=',form_id)]")
    operator = fields.Selection([
        ("=", "="),
        ("!=", "!="),
        ("contains", "contains"),
        ("in", "in (comma-separated)"),
        ("not in", "not in (comma-separated)"),
    ], default="=")
    value_text = fields.Char(string="Match Value", help="For 'in', use comma-separated values.")
    target_form_id = fields.Many2one("smart.form", string="Target Form", required=True)
    fallback_form_id = fields.Many2one("smart.form", string="Fallback Form")
