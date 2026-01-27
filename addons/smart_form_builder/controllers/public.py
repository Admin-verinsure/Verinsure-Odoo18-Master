import json
import base64
from odoo import http
from odoo.http import request


class SmartFormPublic(http.Controller):

    # ==================================================
    # FORM PAGE (FIELD LOGIC + BRANCHING FLAG)
    # ==================================================
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

        # ------------------------------------
        # FIELD LOGIC RULES (SHOW / HIDE)
        # ⚠️ DO NOT TOUCH — JS USES THIS
        # ------------------------------------
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

        # ------------------------------------
        # BRANCHING PRESENT FLAG
        # ------------------------------------
        has_branching = bool(
            request.env["smart.form.branch.rule"]
            .sudo()
            .search([("form_id", "=", form.id)], limit=1)
        )

        return request.render(
            "smart_form_builder.smart_form_page",
            {
                "form": form,
                "rules_json": json.dumps(rules),  # ✅ VALID JSON ONLY
                "has_branching": has_branching,
            },
        )

    # ==================================================
    # FIELD OPTIONS (DYNAMIC)
    # ==================================================
    @http.route(
        "/smart_form/options/<int:field_id>",
        type="http",
        auth="public",
        website=True,
        csrf=False,
    )
    def smart_form_options(self, field_id, token=None, **kw):

        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(
                json.dumps({"success": False, "options": []}),
                [("Content-Type", "application/json")],
            )

        if token:
            form = request.env["smart.form"].sudo().search(
                [("token", "=", token)],
                limit=1,
            )
            if not form or field.form_id.id != form.id:
                return request.make_response(
                    json.dumps({"success": False, "options": []}),
                    [("Content-Type", "application/json")],
                )

        return request.make_response(
            json.dumps({"success": True, "options": field.get_options()}),
            [("Content-Type", "application/json")],
        )

    # ==================================================
    # BRANCHING (AUTHORITATIVE BACKEND)
    # ==================================================
    @http.route(
        "/smart_form/branching/<string:token>",
        type="http",
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
            return request.make_response(
                json.dumps({"success": True, "next_token": None}),
                [("Content-Type", "application/json")],
            )

        payload = request.get_json_data(silent=True) or {}
        answers = payload.get("answers") or {}

        rules = request.env["smart.form.branch.rule"].sudo().search(
            [("form_id", "=", form.id)],
            order="sequence,id",
        )

        # ❗ No rules → terminal form
        if not rules:
            return request.make_response(
                json.dumps({"success": True, "next_token": None}),
                [("Content-Type", "application/json")],
            )

        # ------------------------------
        # NORMALIZE ANSWERS
        # ------------------------------
        def normalize(val):
            if isinstance(val, list):
                return [str(v).strip().lower() for v in val if v]
            return [str(val or "").strip().lower()]

        # ------------------------------
        # MATCH RULE (FIXED)
        # ------------------------------
        def match(rule, val):
            vals = normalize(val)
            want = (rule.value_text or "").strip().lower()
            op = (rule.operator or "").lower()

            # ✅ CHECKBOX SEMANTIC (contains true / false)
            if isinstance(val, list):
                if op in ("contains", "ilike") and want in ("true", "yes", "1", "on"):
                    return bool(vals)
                if op in ("contains", "ilike") and want in ("false", "no", "0", "off"):
                    return not bool(vals)

            if not vals:
                return False

            # ilike / contains / like
            if op in ("ilike", "contains", "like"):
                return any(want in v for v in vals)

            # in / not in
            if op in ("in", "not in"):
                wanted = [x.strip().lower() for x in want.split(",") if x.strip()]
                ok = any(v in wanted for v in vals)
                return ok if op == "in" else not ok

            # not equal
            if op in ("!=", "not_equal"):
                return all(v != want for v in vals)

            # default =
            return any(v == want for v in vals)

        # ------------------------------
        # EVALUATE RULES
        # ------------------------------
        next_form = None
        evaluated = False

        for r in rules:
            key = str(r.trigger_field_id.id)

            if key not in answers:
                continue

            evaluated = True
            if match(r, answers.get(key)):
                next_form = r.target_form_id
                break

        # ------------------------------
        # FALLBACK
        # ------------------------------
        if not next_form and evaluated:
            for r in rules:
                if r.fallback_form_id:
                    next_form = r.fallback_form_id
                    break

        return request.make_response(
            json.dumps({
                "success": True,
                "next_token": next_form.token if next_form else None,
            }),
            [("Content-Type", "application/json")],
        )

    # ==================================================
    # FORM SUBMIT (TERMINAL ONLY)
    # ==================================================
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

        # ------------------------------
        # COLLECT DATA
        # ------------------------------
        data = {}
        files = request.httprequest.files

        for f in form.field_ids.sudo():
            key = f.name or f"field_{f.id}"

            if f.field_type == "file":
                fs = files.get(key)
                if fs and fs.filename:
                    content = fs.read()
                    request.env["ir.attachment"].sudo().create({
                        "name": fs.filename,
                        "datas": base64.b64encode(content),
                        "res_model": "smart.form.submission",
                        "res_id": 0,
                        "mimetype": getattr(fs, "mimetype", None),
                    })
                    data[key] = fs.filename
                else:
                    data[key] = ""
                continue

            if f.field_type == "checkbox":
                data[key] = request.httprequest.form.getlist(f"{key}[]")
                continue

            data[key] = post.get(key) or ""

        # ------------------------------
        # PARTNER LOGIC (UNCHANGED)
        # ------------------------------
        first_name = (data.get("field_24") or "").strip()
        last_name = (data.get("field_25") or "").strip()
        email = (data.get("field_13") or "").strip().lower()
        phone = (data.get("field_11") or "").strip()

        partner = False
        data_source = "form"

        if email:
            Partner = request.env["res.partner"].sudo()
            partner = Partner.search([("email", "=ilike", email)], limit=1)
            if not partner:
                partner = Partner.create({
                    "name": f"{first_name} {last_name}".strip() or email,
                    "email": email,
                    "phone": phone,
                })
            data_source = "partner"

        # ------------------------------
        # CREATE SUBMISSION
        # ------------------------------
        submission = request.env["smart.form.submission"].sudo().create({
            "form_id": form.id,
            "partner_id": partner.id if partner else False,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "data_source": data_source,
            "data_json": json.dumps(data, ensure_ascii=False),
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent"),
        })

        return request.render(
            "smart_form_builder.smart_form_thanks",
            {
                "form": form,
                "submission": submission,
                "partner": partner,
            },
        )
