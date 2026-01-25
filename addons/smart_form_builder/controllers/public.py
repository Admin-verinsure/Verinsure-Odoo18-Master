import json
import base64

from odoo import http
from odoo.http import request


class SmartFormPublic(http.Controller):

    @http.route("/smart_form/<string:token>", type="http", auth="public", website=True, sitemap=False)
    def smart_form_page(self, token, **kw):
        form = request.env["smart.form"].sudo().search([("token", "=", token), ("active", "=", True)], limit=1)
        if not form:
            return request.not_found()

        rules = []
        if hasattr(form, "logic_rule_ids"):
            for r in form.logic_rule_ids.sudo():
                rules.append({
                    "trigger": r.trigger_field_id.id,
                    "op": r.operator,
                    "value": r.value_text or "",
                    "action": r.action,
                    "target": r.target_field_id.id,
                })

        return request.render("smart_form_builder.smart_form_page", {
            "form": form,
            "rules_json": json.dumps(rules),
        })

    @http.route("/smart_form/options/<int:field_id>", type="http", auth="public", website=True, csrf=False)
    def smart_form_options(self, field_id, token=None, **kw):
        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(json.dumps({"success": False, "options": []}),
                                         [("Content-Type", "application/json")])

        if token:
            form = request.env["smart.form"].sudo().search([("token", "=", token)], limit=1)
            if not form or field.form_id.id != form.id:
                return request.make_response(json.dumps({"success": False, "options": []}),
                                             [("Content-Type", "application/json")])

        return request.make_response(json.dumps({"success": True, "options": field.get_options()}),
                                     [("Content-Type", "application/json")])

    @http.route("/smart_form/branching/<string:token>", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def smart_form_branching(self, token, **kw):
        form = request.env["smart.form"].sudo().search([("token", "=", token), ("active", "=", True)], limit=1)
        if not form:
            return request.make_response(json.dumps({"success": False, "next_token": None}),
                                         [("Content-Type", "application/json")])

        try:
            payload = request.get_json_data(silent=True) or {}
        except Exception:
            payload = {}
        answers = payload.get("answers") or {}

        rules = request.env["smart.form.branch.rule"].sudo().search([("form_id", "=", form.id)], order="sequence,id")

        def _vals(v):
            if isinstance(v, dict):
                out = []
                if v.get("value") not in (None, ""):
                    out.append(str(v.get("value")).strip())
                if v.get("label") not in (None, ""):
                    out.append(str(v.get("label")).strip())
                return out
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        def _match(rule, val):
            vals = _vals(val)
            want = (rule.value_text or "").strip()

            if rule.operator in ("in", "not in"):
                wanted = [x.strip() for x in want.split(",") if x.strip()]
                ok = any(v in wanted for v in vals)
                return ok if rule.operator == "in" else (not ok)
            if rule.operator == "contains":
                return any(want in v for v in vals)
            if rule.operator == "!=":
                return all(v != want for v in vals)
            return any(v == want for v in vals)

        next_form = None
        for r in rules:
            key = str(r.trigger_field_id.id)
            if key in answers and _match(r, answers.get(key)):
                next_form = r.target_form_id
                break

        if not next_form and rules and rules[0].fallback_form_id:
            next_form = rules[0].fallback_form_id

        return request.make_response(json.dumps({
            "success": True,
            "next_token": next_form.token if next_form else None
        }), [("Content-Type", "application/json")])

    @http.route("/smart_form/submit", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def smart_form_submit(self, **post):
        token = post.get("token")
        form = request.env["smart.form"].sudo().search([("token", "=", token), ("active", "=", True)], limit=1)
        if not form:
            return request.not_found()

        submission = request.env["smart.form.submission"].sudo().create({
            "form_id": form.id,
            "data_json": "{}",
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent"),
        })

        data = {}
        files = request.httprequest.files

        for f in form.field_ids.sudo():
            key = f.name or f"field_{f.id}"

            if f.field_type == "file":
                fs = files.get(key)
                if fs and getattr(fs, "filename", ""):
                    content = fs.read()
                    request.env["ir.attachment"].sudo().create({
                        "name": fs.filename,
                        "datas": base64.b64encode(content),
                        "res_model": "smart.form.submission",
                        "res_id": submission.id,
                        "mimetype": getattr(fs, "mimetype", None) or "application/octet-stream",
                    })
                    data[key] = fs.filename
                else:
                    data[key] = ""
                continue

            if f.field_type == "checkbox":
                data[key] = request.httprequest.form.getlist(f"{key}[]")
                continue

            data[key] = post.get(key) or ""

        submission.sudo().write({
            "data_json": json.dumps(data, ensure_ascii=False),
        })

        return request.render("smart_form_builder.smart_form_thanks", {"form": form})
