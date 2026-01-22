from odoo import api, fields, models
import json

class SmartFormSubmission(models.Model):
    _name = "smart.form.submission"
    _description = "Smart Form Submission"
    _order = "create_date desc"

    form_id = fields.Many2one("smart.form", required=True, ondelete="cascade")
    data_json = fields.Text(string="Data (JSON)", readonly=True)
    ip = fields.Char(readonly=True)
    user_agent = fields.Char(readonly=True)

attachment_ids = fields.Many2many(
    "ir.attachment",
    compute="_compute_attachment_ids",
    string="Attachments",
    readonly=True,
)

@api.depends("id")
def _compute_attachment_ids(self):
    Attachment = self.env["ir.attachment"].sudo()
    for rec in self:
        if not rec.id:
            rec.attachment_ids = False
            continue
        rec.attachment_ids = Attachment.search([
            ("res_model", "=", "smart.form.submission"),
            ("res_id", "=", rec.id),
        ])


    def data(self):
        for rec in self:
            try:
                return json.loads(rec.data_json or "{}")
            except Exception:
                return {}
