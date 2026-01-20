from odoo import models, fields

class DynamicForm(models.Model):
    _name = "dynamic.form"
    _description = "Dynamic Form"

    name = fields.Char(required=True)
    field_ids = fields.One2many("dynamic.form.field", "form_id", string="Fields")