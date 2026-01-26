import json
import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SmartFormPublic(http.Controller):

    # ---------------------------------------------------------
    # FORM PAGE
    # ---------------------------------------------------------
    @http.route(
        "/smart_form/<string:token>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def smart_form_page(self, token, **kw):
        form = request.env["smart.form"].sudo().search(
            [("token", "=", token), ("active", "=", True)],
            limit=1,
        )
        if not form:
            return request.not_found()

        rules = []
        if hasattr(form, "logic_rule_ids"):
            for r in form.logic_rule_ids.sudo():
                rules.append(
                    {
                        "trigger": r.trigger_field_id.id,
                        "op": r.operator,
                        "value": r.value_text or "",
                        "action": r.action,
                        "target": r.target_field_id.id,
                    }
                )

        return request.render(
            "smart_form_builder.smart_form_page",
            {
                "form": form,
                "rules_json": json.dumps(rules),
            },
        )

    # ---------------------------------------------------------
    # FIELD OPTIONS
    # ---------------------------------------------------------
    @http.route(
        "/smart_form/options/<int:field_id>",
        type="json",
        auth="public",
        website=True,
        csrf=False,
    )
    def smart_form_options(self, field_id, token=None, **kw):
        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return {"success": False, "options": []}

        if token:
            form = request.env["smart.form"].sudo().search(
                [("token", "=", token)], limit=1
            )
            if not form or field.form_id.id != form.id:
                return {"success": False, "options": []}

        return {"success": True, "options": field.get_options()}

    # ---------------------------------------------------------
    # 🔥 BRANCHING (FIXED)
    # ---------------------------------------------------------
    @http.route(
        "/smart_form/branching/<string:token>",
        type="json",          # 🔥 REQUIRED
        auth="public",
        website=True,
        csrf=False,
        methods=["POST"],
    )
    def smart_form_branching(self, token, **kw):

        form = request.env["smart.form"].sudo().search(
            [("token", "=", token), ("active", "=", True)],
            limit=1,
        )
        if not form:
            return {
                "success": False,
                "next_token": None,
                "fallback_token": None,
            }

        answers = kw.get("answers") or {}

        rules = request.env["smart.form.branch.rule"].sudo().search(
            [("form_id", "=", form.id)],
            order="sequence,id",
        )

        def _vals(v):
            if isinstance(v, dict):
                out = []
                if v.get("value"):
                    out.append(str(v["value"]).strip())
                if v.get("label"):
                    out.append(str(v["label"]).strip())
                return out

            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]

            s = str(v).strip()
            return [s] if s else []

        def _match(rule, val):
            vals = [v.lower() for v in _vals(val)]
            want = (rule.value_text or "").strip().lower()

            if rule.operator in ("in", "not in"):
                wanted = [x.strip().lower() for x in want.split(",") if x.strip()]
                ok = any(v in wanted for v in vals)
                return ok if rule.operator == "in" else not ok

            if rule.operator == "contains":
                return any(want in v for v in vals)

            if rule.operator == "!=":
                return all(v != want for v in vals)

            return any(v == want for v in vals)

        matched_form = None
        fallback_form = None
        evaluated_any = False

        for r in rules:
            key = str(r.trigger_field_id.id)

            if key not in answers:
                continue

            evaluated_any = True

            if _match(r, answers.get(key)):
                matched_form = r.target_form_id
                break

            if r.fallback_form_id:
                fallback_form = r.fallback_form_id

        _logger.info(
            "SMART FORM BRANCHING → matched=%s fallback=%s evaluated=%s",
            matched_form and matched_form.token,
            fallback_form and fallback_form.token,
            evaluated_any,
        )

        return {
            "success": True,
            "next_token": matched_form.token if matched_form else None,
            "fallback_token": (
                fallback_form.token if not matched_form and evaluated_any else None
            ),
        }

    # ---------------------------------------------------------
    # FORM SUBMIT
    # ---------------------------------------------------------
    @http.route(
        "/smart_form/submit",
        type="http",
        auth="public",
        website=True,
        csrf=False,
        methods=["POST"],
    )
    def smart_form_submit(self, **post):

        token = post.get("token")
        form = request.env["smart.form"].sudo().search(
            [("token", "=", token), ("active", "=", True)],
            limit=1,
        )
        if not form:
            return request.not_found()

        submission = request.env["smart.form.submission"].sudo().create(
            {
                "form_id": form.id,
                "data_json": "{}",
                "ip": request.httprequest.remote_addr,
                "user_agent": request.httprequest.headers.get("User-Agent"),
            }
        )

        data = {}
        files = request.httprequest.files

        for f in form.field_ids.sudo():
            key = f.name or f"field_{f.id}"

            if f.field_type == "file":
                fs = files.get(key)
                if fs and getattr(fs, "filename", ""):
                    content = fs.read()
                    request.env["ir.attachment"].sudo().create(
                        {
                            "name": fs.filename,
                            "datas": base64.b64encode(content),
                            "res_model": "smart.form.submission",
                            "res_id": submission.id,
                            "mimetype": fs.mimetype
                            or "application/octet-stream",
                        }
                    )
                    data[key] = fs.filename
                else:
                    data[key] = ""
                continue

            if f.field_type == "checkbox":
                data[key] = request.httprequest.form.getlist(f"{key}[]")
                continue

            data[key] = post.get(key) or ""

        submission.sudo().write(
            {"data_json": json.dumps(data, ensure_ascii=False)}
        )

        return request.render(
            "smart_form_builder.smart_form_thanks",
            {"form": form},
        )
