from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SmartFormModelMap(models.Model):
    _name = "smart.form.model.map"
    _description = "Smart Form Target Model Field Mapping"
    _order = "sequence, id"

    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)

    form_field_id = fields.Many2one("smart.form.field", string="Form Field", required=True, ondelete="cascade")

    model_id = fields.Many2one(related="form_id.target_model_id", store=True, readonly=True)
    model_field_id = fields.Many2one(
        "ir.model.fields",
        string="Model Field",
        required=True,
        ondelete="restrict",
        domain="[('model_id', '=', model_id), ('store', '=', True), ('readonly', '=', False)]",
    )

    @api.constrains("form_id", "model_field_id")
    def _check_model_selected(self):
        for rec in self:
            if rec.form_id.store_in_model and not rec.form_id.target_model_id:
                raise ValidationError("Select a Target Model before configuring field mappings.")
