from odoo import models, fields

class DynamicFormSubmission(models.Model):
    _name = "dynamic.form.submission"
    _description = "Dynamic Form Submission"

    form_id = fields.Many2one("dynamic.form", ondelete="cascade")
    submitted_data = fields.Json()