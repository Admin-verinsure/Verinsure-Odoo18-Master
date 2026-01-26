
from odoo import models, fields

class SmartFormSubmission(models.Model):
    _name = "smart.form.submission"
    _description = "Smart Form Submission"

    form_id = fields.Many2one("smart.form", required=True)
    partner_id = fields.Many2one("res.partner", string="Partner")

    first_name = fields.Char(string="First Name")
    last_name = fields.Char(string="Last Name")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")

    data_source = fields.Selection(
        [
            ("partner", "Fetched from Partner"),
            ("form", "Submitted via Form"),
        ],
        string="Data Source",
    )

    data_json = fields.Text(string="Raw Data")
    ip = fields.Char()
    user_agent = fields.Char()
