import json
from odoo import http
from odoo.http import request

class SmoothFormController(http.Controller):

    @http.route("/smooth_form/<string:token>", type="http", auth="public", website=True)
    def smooth_form(self, token, **kw):
        form = request.env["smooth.form"].sudo().search([("token","=",token),("active","=",True)], limit=1)
        if not form:
            return request.not_found()
        return request.render("smooth_form_builder.smooth_form_page", {"form": form})

    @http.route("/smooth_form/preview/<int:form_id>", type="http", auth="user", website=True)
    def smooth_form_preview(self, form_id, **kw):
        form = request.env["smooth.form"].sudo().browse(form_id)
        if not form.exists():
            return request.not_found()
        return request.render("smooth_form_builder.smooth_form_page", {"form": form, "is_preview": True})

    @http.route("/smooth_form/options/<int:field_id>", type="http", auth="public", website=True, csrf=False)
    def smooth_form_options(self, field_id, token=None, **kw):
        Field = request.env["smooth.form.field"].sudo()
        field = Field.browse(field_id)
        if not field.exists():
            return request.make_response(json.dumps({"success": False, "options": []}), headers=[("Content-Type","application/json")])

        if token:
            form = request.env["smooth.form"].sudo().search([("token","=",token)], limit=1)
            if not form or field.form_id.id != form.id:
                return request.make_response(json.dumps({"success": False, "options": []}), headers=[("Content-Type","application/json")])

        opts = field.get_options()
        return request.make_response(json.dumps({"success": True, "options": opts}), headers=[("Content-Type","application/json")])

    @http.route("/smooth_form/branch/<string:token>", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def smooth_form_branch(self, token, **kw):
        form = request.env["smooth.form"].sudo().search([("token","=",token)], limit=1)
        if not form:
            return request.make_response(json.dumps({"success": False, "next_token": None}), headers=[("Content-Type","application/json")])
        payload = request.get_json_data(silent=True) or {}
        answers = payload.get("answers") or {}

        rules = request.env["smooth.form.branch.rule"].sudo().search([("form_id","=",form.id)], order="sequence,id")

        def _match(rule, val):
            v = (val or "").strip() if isinstance(val, str) else val
            want = (rule.value_text or "").strip()
            if rule.operator in ("in","not in"):
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
            k = str(r.trigger_field_id.id)
            if k in answers and _match(r, answers.get(k)):
                next_form = r.target_form_id
                break
        if not next_form:
            next_form = rules[:1].fallback_form_id if rules else None

        return request.make_response(
            json.dumps({"success": True, "next_token": next_form.token if next_form else None}),
            headers=[("Content-Type","application/json")]
        )

    @http.route("/smooth_form/submit/<string:token>", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def smooth_form_submit(self, token, **post):
        form = request.env["smooth.form"].sudo().search([("token","=",token),("active","=",True)], limit=1)
        if not form:
            return request.not_found()

        data = {}
        for f in form.field_ids:
            key = f"field_{f.id}"
            if f.field_type == "checkbox":
                val = "true" if key in post else ""
            else:
                val = post.get(key, "")
            data[str(f.id)] = val or ""

        request.env["smooth.form.submission"].sudo().create({
            "form_id": form.id,
            "token": token,
            "data_json": data,
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent"),
        })

        return request.render("smooth_form_builder.smooth_form_thanks", {"form": form})
