from odoo import fields, models
import json

class SmartFormSubmission(models.Model):
    _name = "smart.form.submission"
    _description = "Smart Form Submission"
    _order = "create_date desc"

    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    data_json = fields.Text(string="Data (JSON)", readonly=True)
    ip = fields.Char(readonly=True)
    user_agent = fields.Char(readonly=True)

    def data(self):
        for rec in self:
            try:
                return json.loads(rec.data_json or "{}")
            except Exception:
                return {}


from odoo import models, fields

class SmartFormSubmission(models.Model):
    _inherit = "smart.form.submission"

    partner_id = fields.Many2one("res.partner", string="Partner")
    first_name = fields.Char(string="First Name")
    last_name = fields.Char(string="Last Name")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")
