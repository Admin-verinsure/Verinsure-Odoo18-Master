from odoo import fields, models

class SmartFormBranchRule(models.Model):
    _name = "smart.form.branch.rule"
    _description = "Smart Form Branch Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    trigger_field_id = fields.Many2one("smart.form.field", required=True, domain="[('form_id','=',form_id)]")
    operator = fields.Selection([
        ("=", "="),
        ("!=", "!="),
        ("contains", "contains"),
        ("in", "in"),
        ("not in", "not in"),
    ], default="=", required=True)
    value_text = fields.Char(string="Value")
    target_form_id = fields.Many2one("smart.form", string="Target Form")
    fallback_form_id = fields.Many2one("smart.form", string="Fallback Form")

