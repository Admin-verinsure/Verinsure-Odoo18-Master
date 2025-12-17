# -*- coding: utf-8 -*-
import json
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import AccessError


class PortalDynamicForms(http.Controller):

    @http.route(["/my/forms"], type="http", auth="user", website=True)
    def my_forms(self, **kw):
        templates = request.env["x_form.template"].sudo().search([("active", "=", True)])
        submissions = request.env["x_form.submission"].search([("partner_id", "=", request.env.user.partner_id.id)], limit=50)
        return request.render("dynamic_form_builder_portal.portal_my_forms", {
            "templates": templates,
            "submissions": submissions,
        })

    @http.route(["/my/forms/start"], type="http", auth="user", website=True, methods=["GET"])
    def start_form(self, template_id=None, **kw):
        if not template_id:
            return request.redirect("/my/forms")
        template = request.env["x_form.template"].sudo().browse(int(template_id))
        if not template.exists():
            return request.redirect("/my/forms")
        submission = request.env["x_form.submission"].create({
            "template_id": template.id,
            "partner_id": request.env.user.partner_id.id,
        })
        return request.redirect(f"/my/forms/{submission.id}")

    @http.route(["/my/forms/<int:submission_id>"], type="http", auth="user", website=True)
    def fill_form(self, submission_id, **kw):
        submission = request.env["x_form.submission"].browse(submission_id)
        submission.check_access_rights("read")
        submission.check_access_rule("read")

        steps = submission.get_visible_steps()

        # Answers map (question_id -> best value string/list)
        answers = {}
        # normal answers
        for ans in submission.answer_ids:
            answers[ans.question_id.id] = ans.get_value()
        # sensitive answers
        for ans in submission.sensitive_answer_ids:
            answers[ans.question_id.id] = ans.get_value()

        # visible questions map
        visible_questions = {}
        condition_json = {}
        for st in steps:
            for q in st.question_ids.sorted("sequence"):
                visible = submission.is_question_visible(q)
                visible_questions[q.id] = visible
                # Provide condition lines for JS
                conds = []
                for c in q.condition_ids:
                    conds.append({
                        "depends_on_question_id": c.depends_on_question_id.id,
                        "operator": c.operator,
                        "value": c.value or "",
                    })
                if conds:
                    condition_json[q.id] = json.dumps({
                        "logic": q.condition_logic,
                        "conditions": conds,
                    })

        return request.render("dynamic_form_builder_portal.portal_form_fill", {
            "submission": submission,
            "steps": steps,
            "answers": answers,
            "visible_questions": visible_questions,
            "condition_json": condition_json,
        })

    @http.route(["/my/forms/<int:submission_id>/submit"], type="http", auth="user", website=True, methods=["POST"])
    def submit_form(self, submission_id, **kw):
        submission = request.env["x_form.submission"].browse(submission_id)
        submission.check_access_rights("write")
        submission.check_access_rule("write")
        if submission.state != "draft":
            return request.redirect(f"/my/forms/{submission.id}")

        submission.action_submit()

        if submission.template_id.portal_success:
            # Render same page with success message at top
            return request.render("portal.portal_layout", {
                "title": submission.template_id.name,
                "breadcrumbs_searchbar": True,
                "body": submission.template_id.portal_success,
            })
        return request.redirect("/my/forms")

    # JSON endpoint for autosave
    @http.route(["/my/forms/<int:submission_id>/autosave"], type="json", auth="user", website=True, csrf=True)
    def autosave(self, submission_id, question_id, value=None, value_list=None, **kw):
        submission = request.env["x_form.submission"].browse(submission_id)
        submission.check_access_rights("write")
        submission.check_access_rule("write")
        if submission.state != "draft":
            return {"ok": False, "error": "Submission is not editable."}

        question = request.env["x_form.question"].sudo().browse(int(question_id))
        if not question.exists():
            return {"ok": False, "error": "Invalid question."}

        # Determine model to store based on step sensitivity
        AnswerModel = request.env["x_form.sensitive.answer"] if question.step_id.is_sensitive else request.env["x_form.answer"]

        ans = AnswerModel.search([("submission_id", "=", submission.id), ("question_id", "=", question.id)], limit=1)
        if not ans:
            ans = AnswerModel.create({"submission_id": submission.id, "question_id": question.id})

        # Set value by type
        t = question.field_type
        vals = {}
        if t in ("char", "email", "phone", "signature"):
            vals["value_char"] = value or False
        elif t == "text":
            vals["value_text"] = value or False
        elif t == "date":
            vals["value_date"] = value or False
        elif t == "integer":
            vals["value_int"] = int(value) if value not in (None, "", False) else False
        elif t == "float":
            vals["value_float"] = float(value) if value not in (None, "", False) else False
        elif t == "bool":
            vals["value_bool"] = bool(value)
        elif t == "selection":
            vals["value_option_id"] = int(value) if value else False
        elif t == "multiselect":
            vals["value_option_ids"] = [(6, 0, [int(x) for x in (value_list or [])])]
        ans.write(vals)

        return {"ok": True}

