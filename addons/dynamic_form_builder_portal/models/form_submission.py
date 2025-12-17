# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class XFormSubmission(models.Model):
    _name = "x_form.submission"
    _description = "Dynamic Form Submission"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(default="/", copy=False, readonly=True)
    template_id = fields.Many2one("x_form.template", required=True, ondelete="restrict", tracking=True)
    template_version = fields.Integer(related="template_id.version", store=True)

    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("under_review", "Under Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        tracking=True,
    )

    current_step_id = fields.Many2one("x_form.step", tracking=True)
    answer_ids = fields.One2many("x_form.answer", "submission_id", string="Answers", copy=False)
    sensitive_answer_ids = fields.One2many("x_form.sensitive.answer", "submission_id", string="Sensitive Answers", copy=False)

    submitted_on = fields.Datetime(readonly=True)
    reviewed_on = fields.Datetime(readonly=True)

    def _next_sequence(self):
        return self.env["ir.sequence"].next_by_code("x_form.submission") or "/"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self._next_sequence()
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            rec._validate_required()
            rec.state = "submitted"
            rec.submitted_on = fields.Datetime.now()
            rec.message_post(body=_("Submission submitted by %s") % (rec.partner_id.display_name,))

    def action_under_review(self):
        self.write({"state": "under_review", "reviewed_on": fields.Datetime.now()})

    def action_approve(self):
        self.write({"state": "approved", "reviewed_on": fields.Datetime.now()})

    def action_reject(self):
        self.write({"state": "rejected", "reviewed_on": fields.Datetime.now()})

    def _answers_map(self):
        """Returns dict: question_id -> python value (best effort)."""
        mapping = {}
        for ans in self.answer_ids:
            mapping[ans.question_id.id] = ans.get_value()
        for ans in self.sensitive_answer_ids:
            mapping[ans.question_id.id] = ans.get_value()
        return mapping

    def _is_condition_met(self, cond, answers_map):
        qid = cond.depends_on_question_id.id
        val = answers_map.get(qid)
        op = cond.operator
        target = (cond.value or "").strip()

        if op == "truthy":
            return bool(val) is True
        if op == "falsy":
            return bool(val) is False

        # Normalize to string for comparisons
        sval = "" if val is None else str(val)

        if op == "eq":
            return sval == target
        if op == "neq":
            return sval != target
        if op == "contains":
            return target.lower() in sval.lower()
        if op == "in":
            items = [x.strip() for x in target.split(",") if x.strip()]
            return sval in items
        return False

    def is_step_visible(self, step):
        answers_map = self._answers_map()
        conds = step.condition_ids
        if not conds:
            return True
        results = [self._is_condition_met(c, answers_map) for c in conds]
        return all(results) if step.condition_logic == "all" else any(results)

    def is_question_visible(self, question):
        answers_map = self._answers_map()
        conds = question.condition_ids
        if not conds:
            return True
        results = [self._is_condition_met(c, answers_map) for c in conds]
        return all(results) if question.condition_logic == "all" else any(results)

    def get_visible_steps(self):
        steps = self.template_id.step_ids.sorted("sequence")
        return steps.filtered(lambda s: self.is_step_visible(s))

    def _validate_required(self):
        """Server-side required validation for all visible required questions."""
        for rec in self:
            answers_map = rec._answers_map()
            for step in rec.get_visible_steps():
                for q in step.question_ids.sorted("sequence"):
                    if not rec.is_question_visible(q):
                        continue
                    if not q.required:
                        continue
                    # Required: must have non-empty answer
                    val = answers_map.get(q.id)
                    if q.field_type == "bool":
                        if val is None:
                            raise ValidationError(_("%s is required.") % q.label)
                    else:
                        if val in (None, "", [], False):
                            raise ValidationError(_("%s is required.") % q.label)


class XFormAnswer(models.Model):
    _name = "x_form.answer"
    _description = "Dynamic Form Answer"
    _order = "question_id"

    submission_id = fields.Many2one("x_form.submission", required=True, ondelete="cascade")
    question_id = fields.Many2one("x_form.question", required=True, ondelete="restrict")
    step_id = fields.Many2one(related="question_id.step_id", store=True)

    value_char = fields.Char()
    value_text = fields.Text()
    value_date = fields.Date()
    value_int = fields.Integer()
    value_float = fields.Float()
    value_bool = fields.Boolean()
    value_option_id = fields.Many2one("x_form.question.option")
    value_option_ids = fields.Many2many("x_form.question.option", string="Multiple Options")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")

    _sql_constraints = [
        ("uniq_submission_question", "unique(submission_id, question_id)", "Answer already exists for this question."),
    ]

    def get_value(self):
        self.ensure_one()
        t = self.question_id.field_type
        if t in ("char", "email", "phone", "signature"):
            return self.value_char
        if t == "text":
            return self.value_text
        if t == "date":
            return self.value_date
        if t == "integer":
            return self.value_int
        if t == "float":
            return self.value_float
        if t == "bool":
            return self.value_bool if self.value_bool in (True, False) else None
        if t == "selection":
            return self.value_option_id.value or self.value_option_id.label if self.value_option_id else None
        if t == "multiselect":
            return [(o.value or o.label) for o in self.value_option_ids]
        if t == "file":
            return [a.id for a in self.attachment_ids]
        return None

    def set_value(self, raw):
        self.ensure_one()
        t = self.question_id.field_type
        vals = {}
        if t in ("char", "email", "phone", "signature"):
            vals["value_char"] = raw or False
        elif t == "text":
            vals["value_text"] = raw or False
        elif t == "date":
            vals["value_date"] = raw or False
        elif t == "integer":
            vals["value_int"] = int(raw) if raw not in (None, "", False) else False
        elif t == "float":
            vals["value_float"] = float(raw) if raw not in (None, "", False) else False
        elif t == "bool":
            vals["value_bool"] = bool(raw) if raw not in (None, "", False) else False
        elif t == "selection":
            vals["value_option_id"] = int(raw) if raw else False
        elif t == "multiselect":
            vals["value_option_ids"] = [(6, 0, [int(x) for x in (raw or [])])]
        self.write(vals)


class XFormSensitiveAnswer(models.Model):
    _name = "x_form.sensitive.answer"
    _description = "Dynamic Form Sensitive Answer (restricted)"

    submission_id = fields.Many2one("x_form.submission", required=True, ondelete="cascade")
    question_id = fields.Many2one("x_form.question", required=True, ondelete="restrict")
    step_id = fields.Many2one(related="question_id.step_id", store=True)

    value_char = fields.Char()
    value_text = fields.Text()
    value_date = fields.Date()
    value_int = fields.Integer()
    value_float = fields.Float()
    value_bool = fields.Boolean()
    value_option_id = fields.Many2one("x_form.question.option")
    value_option_ids = fields.Many2many("x_form.question.option", string="Multiple Options")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")

    _sql_constraints = [
        ("uniq_submission_question_sensitive", "unique(submission_id, question_id)", "Answer already exists for this question."),
    ]

    def get_value(self):
        self.ensure_one()
        # same as normal answer
        t = self.question_id.field_type
        if t in ("char", "email", "phone", "signature"):
            return self.value_char
        if t == "text":
            return self.value_text
        if t == "date":
            return self.value_date
        if t == "integer":
            return self.value_int
        if t == "float":
            return self.value_float
        if t == "bool":
            return self.value_bool if self.value_bool in (True, False) else None
        if t == "selection":
            return self.value_option_id.value or self.value_option_id.label if self.value_option_id else None
        if t == "multiselect":
            return [(o.value or o.label) for o in self.value_option_ids]
        if t == "file":
            return [a.id for a in self.attachment_ids]
        return None
