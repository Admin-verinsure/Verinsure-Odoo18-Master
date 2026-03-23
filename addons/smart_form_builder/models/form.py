from odoo import api, fields, models
import secrets


class SmartForm(models.Model):
    _name = "smart.form"
    _description = "Smart Form"
    _order = "id desc"

    name = fields.Char(required=True)
    token = fields.Char(index=True, readonly=True, copy=False,
                        default=lambda self: secrets.token_urlsafe(16))
    active = fields.Boolean(default=True)
    target_model_id = fields.Many2one(
        "ir.model", string="Target Model",
        help="Optional. If set, each submission will create a new record in this model. "
             "Form field Technical Name must match a field on the model; "
             "non-matching fields are ignored.")

    field_ids = fields.One2many("smart.form.field", "form_id", string="Fields", copy=True)
    submission_ids = fields.One2many("smart.form.submission", "form_id",
                                     string="Submissions", readonly=True)
    branch_rule_ids = fields.One2many("smart.form.branch.rule", "form_id",
                                      string="Branch Rules", copy=True)
    logic_rule_ids = fields.One2many("smart.form.logic.rule", "form_id",
                                     string="Logic Rules", copy=True)

    submission_count = fields.Integer(compute="_compute_submission_count")

    # Human-readable label of the field marked as key — shown on the form list
    key_field_label = fields.Char(
        string="Key Field",
        compute="_compute_key_field_label",
        store=False,
    )

    def _compute_submission_count(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids)

    def _compute_key_field_label(self):
        for rec in self:
            key = rec.field_ids.filtered("is_key_field")[:1]
            rec.key_field_label = key.label if key else ""

    def action_open_public(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/smart_form/{self.token}",
            "target": "new",
        }

    def action_open_preview(self):
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

    def action_open_table_view(self):
        """Open the HTML submissions table in a new browser tab."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/smart_form/table/%d" % self.id,
            "target": "new",
        }
