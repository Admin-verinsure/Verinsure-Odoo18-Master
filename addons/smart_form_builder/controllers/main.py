import json
from odoo import http
from odoo.http import request

class SmartFormController(http.Controller):

    @http.route("/smart_form/<string:token>", type="http", auth="public", website=True)
    def public_form(self, token, **kw):
        form = request.env["smart.form"].sudo().search([("share_token", "=", token), ("active", "=", True)], limit=1)
        if not form:
            return request.not_found()
        return request.render("smart_form_builder.smart_form_public", {"form": form, "is_preview": False})

    @http.route("/smart_form/preview/<int:form_id>", type="http", auth="user", website=True)
    def preview_form(self, form_id, **kw):
        form = request.env["smart.form"].sudo().browse(form_id)
        if not form.exists():
            return request.not_found()
        return request.render("smart_form_builder.smart_form_public", {"form": form, "is_preview": True})

    @http.route("/smart_form/submit", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def submit(self, **post):
        token = post.get("token")
        form = request.env["smart.form"].sudo().search([("share_token", "=", token), ("active", "=", True)], limit=1)
        if not form:
            return request.not_found()

        data = {}
        for f in form.field_ids:
            key = f"field_{f.id}"
            if f.field_type == "checkbox":
                data[str(f.id)] = "true" if post.get(key) else ""
            else:
                data[str(f.id)] = post.get(key, "")
        request.env["smart.form.submission"].sudo().create({
            "form_id": form.id,
            "data_json": json.dumps(data, ensure_ascii=False),
        })
        return request.render("smart_form_builder.smart_form_thanks", {"form": form})

    @http.route("/smart_form/options/<int:field_id>", type="http", auth="public", website=True, csrf=False)
    def options(self, field_id, token=None, **kw):
        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(json.dumps({"success": False, "options": []}),
                                         headers=[("Content-Type", "application/json")])

        if token:
            form = request.env["smart.form"].sudo().search([("share_token", "=", token)], limit=1)
            if not form or field.form_id.id != form.id:
                return request.make_response(json.dumps({"success": False, "options": []}),
                                             headers=[("Content-Type", "application/json")])

        if field.option_source != "model":
            return request.make_response(json.dumps({"success": True, "options": field.get_manual_options()}),
                                         headers=[("Content-Type", "application/json")])

        opts = field.get_dynamic_options()
        return request.make_response(json.dumps({"success": True, "options": opts}),
                                     headers=[("Content-Type", "application/json")])

    @http.route("/smart_form/branch/<string:token>", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def branch(self, token, **kw):
        form = request.env["smart.form"].sudo().search([("share_token", "=", token)], limit=1)
        if not form:
            return request.make_response(json.dumps({"success": False, "next_token": None}),
                                         headers=[("Content-Type", "application/json")])

        try:
            payload = request.get_json_data(silent=True) or {}
        except Exception:
            payload = {}
        answers = payload.get("answers") or {}

        rules = request.env["smart.form.branch.rule"].sudo().search([("form_id", "=", form.id)], order="sequence,id")

        def _match(rule, val):
            v = (val or "").strip() if isinstance(val, str) else val
            want = (rule.value_text or "").strip()
            if rule.operator in ("in", "not in"):
                wanted = [x.strip() for x in want.split(",") if x.strip()]
                ok = str(v) in wanted
                return ok if rule.operator == "in" else (not ok)
            if rule.operator == "contains":
                return want in str(v)
            if rule.operator == "!=":
                return str(v) != want
            return str(v) == want

        next_form = None
        for r in rules:
            key = str(r.trigger_field_id.id)
            if key in answers and _match(r, answers.get(key)):
                next_form = r.target_form_id
                break

        if not next_form and rules and rules[0].fallback_form_id:
            next_form = rules[0].fallback_form_id

        next_token = next_form.share_token if next_form else None
        return request.make_response(json.dumps({"success": True, "next_token": next_token}),
                                     headers=[("Content-Type", "application/json")])
