from odoo import models, fields
import secrets

class SmoothForm(models.Model):
    _name = "smooth.form"
    _description = "Smooth Form"
    _order = "id desc"

    name = fields.Char(required=True)
    token = fields.Char(index=True, readonly=True, copy=False, default=lambda self: secrets.token_urlsafe(16))
    active = fields.Boolean(default=True)

    field_ids = fields.One2many("smooth.form.field", "form_id", string="Fields", copy=True)
    branch_rule_ids = fields.One2many("smooth.form.branch.rule", "form_id", string="Branch Rules", copy=True)

    submission_count = fields.Integer(compute="_compute_submission_count")

    def _compute_submission_count(self):
        Sub = self.env["smooth.form.submission"]
        for r in self:
            r.submission_count = Sub.search_count([("form_id","=",r.id)])

    def action_open_public(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smooth_form/{self.token}",
            "target": "new",
        }

    def action_open_preview(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smooth_form/preview/{self.id}",
            "target": "new",
        }

    def action_view_submissions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Submissions",
            "res_model": "smooth.form.submission",
            "view_mode": "list,form",
            "domain": [("form_id","=",self.id)],
        }
