from odoo import fields, models

class SmartFormLogicRule(models.Model):
    _name = "smart.form.logic.rule"
    _description = "Smart Form Logic Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    trigger_field_id = fields.Many2one("smart.form.field", required=True, domain="[('form_id','=',form_id)]")
    operator = fields.Selection([
        ("=", "="),
        ("!=", "!="),
        (">", ">"),
        (">=", ">="),
        ("<", "<"),
        ("<=", "<="),
        ("contains", "contains"),
        ("in", "in"),
        ("not in", "not in"),
    ], default="=", required=True)
    value_text = fields.Char(string="Value")
    action = fields.Selection([
        ("show", "Show"),
        ("hide", "Hide"),
        ("require", "Make Required"),
        ("unrequire", "Make Optional"),
    ], default="show", required=True)
    target_field_id = fields.Many2one("smart.form.field", required=True, domain="[('form_id','=',form_id)]")
