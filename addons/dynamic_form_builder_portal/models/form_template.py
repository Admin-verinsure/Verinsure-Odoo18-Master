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

    step_ids = fields.One2many("x_form.step", "template_id", string="Sections", copy=True)

    # All questions (across sections). Works because x_form.question.template_id is store=True.
    question_ids = fields.One2many("x_form.question", "template_id", string="Questions")

    # Default section for quick question creation in UI
    default_step_id = fields.Many2one(
        "x_form.step",
        compute="_compute_default_step_id",
        help="Default section used when creating questions from the builder UI.",
    )

    portal_intro = fields.Html(string="Portal Intro", help="Shown on portal start page.")
    portal_success = fields.Html(string="Portal Success Message", help="Shown after submission.")

    @api.depends("step_ids")
    def _compute_default_step_id(self):
        for rec in self:
            # choose first by sequence/id
            rec.default_step_id = rec.step_ids.sorted(lambda s: (s.sequence, s.id))[:1].id

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        # Google-Forms-like: always create a default "Main" section
        Step = self.env["x_form.step"].sudo()
        for rec in records:
            if not rec.step_ids:
                Step.create({
                    "template_id": rec.id,
                    "name": "Main",
                    "code": "MAIN",
                    "sequence": 1,
                })
        return records

    def action_new_version(self):
        for rec in self:
            rec.version += 1
            rec.message_post(body=_("Template version increased to %s") % rec.version)


class XFormStep(models.Model):
    _name = "x_form.step"
    _description = "Dynamic Form Section"
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

    # Optional: show/hide section based on conditions (structured)
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

    def unlink(self):
        # Prevent deleting the default "Main" section (optional but helps non-tech users)
        for rec in self:
            if rec.code == "MAIN":
                raise ValidationError(_("You cannot delete the default 'Main' section."))
        return super().unlink()


class XFormQuestion(models.Model):
    _name = "x_form.question"
    _description = "Dynamic Form Question"
    _order = "sequence, id"

    step_id = fields.Many2one("x_form.step", required=True, ondelete="cascade")

    # store=True is crucial so Template.question_ids can work
    template_id = fields.Many2one(
        related="step_id.template_id",
        store=True,
        index=True,
        readonly=True,
    )

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
                raise ValidationError(
                    _("Please add at least one option for the question: %s") % (rec.label or "")
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("key") and vals.get("label"):
                key = vals["label"].strip().lower().replace(" ", "_")
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

    # Can belong to a section or a question
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
                raise ValidationError(_("A condition must be attached to exactly one: a Section or a Question."))
