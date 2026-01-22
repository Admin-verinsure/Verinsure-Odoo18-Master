from odoo import api, fields, models
import secrets

class SmartForm(models.Model):
    _name = "smart.form"
    _description = "Smart Form"
    _order = "id desc"

    name = fields.Char(required=True)
    token = fields.Char(index=True, readonly=True, copy=False, default=lambda self: secrets.token_urlsafe(16))
    active = fields.Boolean(default=True)

    field_ids = fields.One2many("smart.form.field", "form_id", string="Fields", copy=True)
    submission_ids = fields.One2many("smart.form.submission", "form_id", string="Submissions", readonly=True)
    branch_rule_ids = fields.One2many("smart.form.branch.rule", "form_id", string="Branch Rules", copy=True)

    submission_count = fields.Integer(compute="_compute_submission_count")

    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids)

    def action_open_public(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.token}",
            "target": "new",
        }

    def action_open_preview(self):
        # Preview is same as public but with ?preview=1
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.token}?preview=1",
            "target": "new",
        }

    def action_view_submissions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Submissions",
            "res_model": "smart.form.submission",
            "view_mode": "list,form",
            "domain": [("form_id", "=", self.id)],
            "context": {"default_form_id": self.id},
        }
