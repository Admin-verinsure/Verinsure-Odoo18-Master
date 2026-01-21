from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class FormBranchRule(models.Model):
    _name = 'form.builder.branch.rule'
    _description = 'Form Branching Rule'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    form_id = fields.Many2one('form.builder', required=True, ondelete='cascade')
    trigger_field_id = fields.Many2one(
        'form.builder.field',
        required=True,
        domain="[('form_id', '=', form_id)]",
        help="User answer for this field will decide which form to show next."
    )

    operator = fields.Selection([
        ('=', '='),
        ('!=', '!='),
        ('in', 'in'),
        ('not in', 'not in'),
        ('contains', 'contains'),
    ], default='=', required=True)

    value_text = fields.Char(string="Match Value", help="Value to match. For 'in' use comma-separated values.")

    target_form_id = fields.Many2one(
        'form.builder',
        string="Target Form",
        required=True,
        help="Form to display when this rule matches."
    )

    fallback_form_id = fields.Many2one(
        'form.builder',
        string="Fallback Form",
        help="Optional fallback when no rule matches. If empty, current form continues."
    )

    @api.constrains('form_id', 'target_form_id')
    def _check_target_not_same(self):
        for rec in self:
            if rec.form_id and rec.target_form_id and rec.form_id.id == rec.target_form_id.id:
                raise ValidationError(_("Target Form must be different from the source form."))
