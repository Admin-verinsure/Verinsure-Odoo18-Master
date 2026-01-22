from odoo import fields, models

class SmartFormSubmission(models.Model):
    _name = "smart.form.submission"
    _description = "Smart Form Submission"
    _order = "create_date desc, id desc"

    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    data_json = fields.Text(string="Submitted Data (JSON)", readonly=True)
