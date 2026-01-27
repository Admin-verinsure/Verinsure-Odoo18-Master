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
            return request.make_response(json.dumps({"success": False, "next_token": None}), [("Content-Type","application/json")])

        payload = (request.httprequest.get_json(silent=True) or {})
        answers = payload.get("answers") or {}

        rules = request.env["smart.form.branch.rule"].sudo().search(
            [("form_id", "=", form.id)],
            order="sequence,id"
        )

        def _as_list(v):
            if v is None:
                return []
            if isinstance(v, (list, tuple, set)):
                return [str(x).strip() for x in v if str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        def _match(rule, raw_answer):
            op = (rule.operator or "=").strip()
            rule_val = (rule.value_text or "").strip()

            # Checkbox answers arrive as list; other types as string
            ans_list = _as_list(raw_answer)
            ans_scalar = ans_list[0] if ans_list else ""

            if op in ("in", "not in"):
                candidates = [x.strip() for x in rule_val.split(",") if x.strip()]
                hit = any(a in candidates for a in ans_list) if ans_list else (ans_scalar in candidates)
                return hit if op == "in" else (not hit)

            if op == "contains":
                if not rule_val:
                    return False
                # list contains
                if ans_list:
                    return any(rule_val in a for a in ans_list)
                return rule_val in (ans_scalar or "")

            # default: = or !=
            if op == "!=":
                return (ans_scalar or "") != rule_val
            return (ans_scalar or "") == rule_val

        next_form = None
        fallback_form = None

        for r in rules:
            key = str(r.trigger_field_id.id)
            if _match(r, answers.get(key)):
                # If rule matched, honor target if present; otherwise "submit"
                next_form = r.target_form_id
                break
            # capture first available fallback in priority order
            if fallback_form is None and r.fallback_form_id:
                fallback_form = r.fallback_form_id

        if not next_form and fallback_form:
            next_form = fallback_form

        return request.make_response(json.dumps({"success": True, "next_token": (next_form.token if next_form else None)}), [("Content-Type","application/json")])

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

        # Server-side branching (robust even if JS fails):
        # Evaluate rules in order; on match redirect to target form; else use fallback; else show thanks.
        rules = request.env["smart.form.branch.rule"].sudo().search([("form_id", "=", form.id)], order="sequence,id")

        def _as_list(v):
            if v is None:
                return []
            if isinstance(v, (list, tuple, set)):
                return [str(x).strip() for x in v if str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        def _match(rule, raw_answer):
            op = (rule.operator or "=").strip()
            rule_val = (rule.value_text or "").strip()
            ans_list = _as_list(raw_answer)
            ans_scalar = (ans_list[0] if ans_list else "")

            if op in (">", ">=", "<", "<="):
                try:
                    a = float(ans_scalar)
                    b = float(rule_val)
                except Exception:
                    return False
                if op == ">":
                    return a > b
                if op == ">=":
                    return a >= b
                if op == "<":
                    return a < b
                return a <= b

            if op == "contains":
                if not rule_val:
                    return False
                if ans_list:
                    return any(rule_val in a for a in ans_list)
                return rule_val in (ans_scalar or "")

            if op == "!=":
                return (ans_scalar or "") != rule_val
            return (ans_scalar or "") == rule_val

        next_form = None
        fallback_form = None
        for rule in rules:
            raw_answer = data.get(str(rule.field_id.id)) if rule.field_id else None
            if _match(rule, raw_answer):
                if rule.target_form_id:
                    next_form = rule.target_form_id
                # match but no target => submit current form (no redirect)
                break
            if not fallback_form and rule.fallback_form_id:
                fallback_form = rule.fallback_form_id

        if not next_form and fallback_form:
            next_form = fallback_form

        if next_form:
            return request.redirect(f"/smart_form/{next_form.token}")

        return request.render("smart_form_builder.smart_form_thanks", {"form": form})
