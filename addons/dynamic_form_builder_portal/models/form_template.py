# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class XFormTemplate(models.Model):
    _name = "x_form.template"
    _description = "Dynamic Form Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    version = fields.Integer(default=1, tracking=True)
    description = fields.Html()

    step_ids = fields.One2many("x_form.step", "template_id", string="Steps", copy=True)

    portal_intro = fields.Html(string="Portal Intro", help="Shown on portal start page.")
    portal_success = fields.Html(string="Portal Success Message", help="Shown after submission.")


step_count = fields.Integer(compute="_compute_counts", string="Sections", store=False)
question_count = fields.Integer(compute="_compute_counts", string="Questions", store=False)
submission_count = fields.Integer(compute="_compute_counts", string="Submissions", store=False)

def _compute_counts(self):
    Question = self.env["x_form.question"]
    Submission = self.env["x_form.submission"]
    for rec in self:
        rec.step_count = len(rec.step_ids)
        rec.question_count = Question.search_count([("template_id", "=", rec.id)])
        rec.submission_count = Submission.search_count([("template_id", "=", rec.id)])

@api.model_create_multi
def create(self, vals_list):
    recs = super().create(vals_list)
    # Ensure every template has at least one default section (Google-Forms style)
    for rec in recs:
        if not rec.step_ids:
            self.env["x_form.step"].create({
                "template_id": rec.id,
                "name": _("Main"),
                "code": "1",
                "sequence": 10,
            })
    return recs

def action_open_sections(self):
    self.ensure_one()
    return {
        "type": "ir.actions.act_window",
        "name": _("Sections"),
        "res_model": "x_form.step",
        "view_mode": "list,form",
        "domain": [("template_id", "=", self.id)],
        "context": {"default_template_id": self.id},
    }

def action_open_questions(self):
    self.ensure_one()
    return {
        "type": "ir.actions.act_window",
        "name": _("Questions"),
        "res_model": "x_form.question",
        "view_mode": "list,form",
        "domain": [("template_id", "=", self.id)],
        "context": {"default_template_id": self.id},
    }

def action_open_submissions(self):
    self.ensure_one()
    return {
        "type": "ir.actions.act_window",
        "name": _("Submissions"),
        "res_model": "x_form.submission",
        "view_mode": "list,form",
        "domain": [("template_id", "=", self.id)],
        "context": {"default_template_id": self.id},
    }


    def action_new_version(self):
        for rec in self:
            rec.version += 1
            rec.message_post(body=_("Template version increased to %s") % rec.version)


class XFormStep(models.Model):
    _name = "x_form.step"
    _description = "Dynamic Form Step/Section"
    _order = "sequence, id"

    template_id = fields.Many2one("x_form.template", required=True, ondelete="cascade")
    name = fields.Char(required=True)
    code = fields.Char(help="Optional code like 1A, 1B, 2C", index=True)
    sequence = fields.Integer(default=10)
    is_sensitive = fields.Boolean(
        string="Sensitive Section",
        help="Answers will be stored separately with stricter access control (e.g., criminal history).",
    )

    question_ids = fields.One2many("x_form.question", "step_id", string="Questions", copy=True)

    # Optional: show/hide step based on conditions (structured)
    condition_ids = fields.One2many("x_form.condition", "step_id", string="Visibility Conditions", copy=True)
    condition_logic = fields.Selection([("all", "ALL conditions"), ("any", "ANY condition")], default="all")

    def name_get(self):
        res = []
        for rec in self:
            name = rec.name
            if rec.code:
                name = f"[{rec.code}] {name}"
            res.append((rec.id, name))
        return res


class XFormQuestion(models.Model):
    _name = "x_form.question"
    _description = "Dynamic Form Question"
    _order = "sequence, id"

    step_id = fields.Many2one("x_form.step", required=True, ondelete="cascade")
    template_id = fields.Many2one(related="step_id.template_id", store=True, index=True)

    sequence = fields.Integer(default=10)
    label = fields.Char(required=True)
    help = fields.Char()
    key = fields.Char(
        string="Key",
        help="Technical key for integrations (optional). Auto-generated if empty.",
        index=True,
    )

    field_type = fields.Selection(
        [
            ("char", "Short Text"),
            ("text", "Long Text"),
            ("date", "Date"),
            ("integer", "Integer"),
            ("float", "Decimal"),
            ("bool", "Yes/No"),
            ("selection", "Single Choice"),
            ("multiselect", "Multiple Choice"),
            ("email", "Email"),
            ("phone", "Phone"),
            ("signature", "Typed Signature"),
            ("file", "File Upload"),
        ],
        default="char",
        required=True,
    )

    required = fields.Boolean(default=False)
    placeholder = fields.Char()
    validation_regex = fields.Char(help="Optional Python/JS regex pattern for client validation.")
    min_value = fields.Float()
    max_value = fields.Float()

    option_ids = fields.One2many("x_form.question.option", "question_id", string="Options", copy=True)

    # Conditions for question visibility
    condition_ids = fields.One2many("x_form.condition", "question_id", string="Visibility Conditions", copy=True)
    condition_logic = fields.Selection([("all", "ALL conditions"), ("any", "ANY condition")], default="all")

    @api.constrains("field_type", "option_ids")
    def _check_options(self):
        for rec in self:
            if rec.field_type in ("selection", "multiselect") and not rec.option_ids:
                raise ValidationError(_("Please add options for selection/multiselect question: %s") % rec.label)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("key") and vals.get("label"):
                key = vals["label"].strip().lower()
                key = key.replace(" ", "_")
                key = "".join(ch for ch in key if ch.isalnum() or ch == "_")
                vals["key"] = key[:60]
        return super().create(vals_list)


class XFormQuestionOption(models.Model):
    _name = "x_form.question.option"
    _description = "Question Option"
    _order = "sequence, id"

    question_id = fields.Many2one("x_form.question", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True)
    value = fields.Char(help="Optional explicit value; label used if empty.")


class XFormCondition(models.Model):
    _name = "x_form.condition"
    _description = "Visibility Condition (Structured)"

    # Can belong to a step or a question
    step_id = fields.Many2one("x_form.step", ondelete="cascade")
    question_id = fields.Many2one("x_form.question", ondelete="cascade")

    depends_on_question_id = fields.Many2one(
        "x_form.question",
        required=True,
        domain="[('template_id', '=', template_id)]",
    )
    template_id = fields.Many2one(
        "x_form.template",
        compute="_compute_template_id",
        store=True,
    )

    operator = fields.Selection(
        [
            ("eq", "Equals"),
            ("neq", "Not Equals"),
            ("contains", "Contains"),
            ("in", "In (comma-separated)"),
            ("truthy", "Is True/Yes"),
            ("falsy", "Is False/No"),
        ],
        default="eq",
        required=True,
    )
    value = fields.Char(help="Comparison value (text). For 'in', provide comma-separated values.")

    @api.depends("step_id.template_id", "question_id.template_id")
    def _compute_template_id(self):
        for rec in self:
            rec.template_id = rec.step_id.template_id or rec.question_id.template_id

    @api.constrains("step_id", "question_id")
    def _check_parent(self):
        for rec in self:
            if bool(rec.step_id) == bool(rec.question_id):
                raise ValidationError(_("A condition must be attached to exactly one: a Step or a Question."))
