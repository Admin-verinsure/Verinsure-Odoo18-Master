from odoo import models, fields

class SmoothFormSubmission(models.Model):
    _name = "smooth.form.submission"
    _description = "Smooth Form Submission"
    _order = "create_date desc"

    form_id = fields.Many2one("smooth.form", required=True, ondelete="cascade")
    token = fields.Char(index=True)
    data_json = fields.Json(string="Data")
    ip = fields.Char()
    user_agent = fields.Char()
