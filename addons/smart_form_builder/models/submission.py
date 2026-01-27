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

    target_model = fields.Char(string='Target Model', readonly=True)
    target_res_id = fields.Integer(string='Target Record ID', readonly=True)

    def data(self):
        for rec in self:
            try:
                return json.loads(rec.data_json or "{}")
            except Exception:
                return {}
