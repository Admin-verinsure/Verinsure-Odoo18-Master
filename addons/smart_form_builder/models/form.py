from odoo import api, fields, models
import secrets

class SmartForm(models.Model):
    _name = "smart.form"
    _description = "Smart Form"
    _order = "id desc"

    name = fields.Char(required=True)
    share_token = fields.Char(readonly=True, index=True, copy=False)
    active = fields.Boolean(default=True)

    field_ids = fields.One2many("smart.form.field", "form_id", string="Fields", copy=True)
    branch_rule_ids = fields.One2many("smart.form.branch.rule", "form_id", string="Branch Rules", copy=True)
    submission_ids = fields.One2many("smart.form.submission", "form_id", string="Submissions", readonly=True)

    submission_count = fields.Integer(compute="_compute_submission_count")

    @api.depends("submission_ids")
    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("share_token"):
                vals["share_token"] = secrets.token_urlsafe(16)
        return super().create(vals_list)

    def action_open_public(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.share_token}",
            "target": "new",
        }

    def action_open_preview(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/preview/{self.id}",
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
