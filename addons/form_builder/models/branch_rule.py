from odoo import models, fields

class SmoothFormBranchRule(models.Model):
    _name = "smooth.form.branch.rule"
    _description = "Smooth Form Branch Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    form_id = fields.Many2one("smooth.form", required=True, ondelete="cascade")
    trigger_field_id = fields.Many2one("smooth.form.field", required=True, domain="[('form_id','=',form_id)]")
    operator = fields.Selection([
        ("=","Equals"),
        ("!=","Not Equals"),
        ("contains","Contains"),
        ("in","In (comma list)"),
        ("not in","Not In (comma list)")
    ], default="=", required=True)
    value_text = fields.Char(string="Match Value", required=True)
    target_form_id = fields.Many2one("smooth.form", string="Target Form")
    fallback_form_id = fields.Many2one("smooth.form", string="Fallback Form")
