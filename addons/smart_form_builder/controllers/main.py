import json
from odoo import http
from odoo.http import request


class SmartFormController(http.Controller):

    # --------------------------------------------------
    # FORM SUBMIT
    # --------------------------------------------------
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

        # Field mapping
        first_name = (post.get("field_24") or "").strip()
        last_name = (post.get("field_25") or "").strip()
        email = (post.get("field_13") or "").strip().lower()
        phone = (post.get("field_11") or "").strip()

        Partner = request.env["res.partner"].sudo()
        partner = False
        data_source = "form"

        if email:
            partner = Partner.search([("email", "=ilike", email)], limit=1)

        if partner:
            data_source = "partner"
        else:
            partner = Partner.create({
                "name": f"{first_name} {last_name}".strip() or email,
                "email": email,
                "phone": phone,
            })

        request.env["smart.form.submission"].sudo().create({
            "form_id": form.id,
            "partner_id": partner.id,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "data_source": data_source,
            "data_json": json.dumps(post, ensure_ascii=False),
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent"),
        })

        return request.render(
            "smart_form_builder.smart_form_thanks",
            {"form": form, "partner": partner},
        )

    # --------------------------------------------------
    # FIELD OPTIONS
    # --------------------------------------------------
    @http.route(
        "/smart_form/options/<int:field_id>",
        type="http",
        auth="public",
        website=True,
        csrf=False,
    )
    def options(self, field_id, token=None, **kw):

        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(
                json.dumps({"success": False, "options": []}),
                headers=[("Content-Type", "application/json")],
            )

        if token:
            form = request.env["smart.form"].sudo().search(
                [("token", "=", token)],
                limit=1,
            )
            if not form or field.form_id.id != form.id:
                return request.make_response(
                    json.dumps({"success": False, "options": []}),
                    headers=[("Content-Type", "application/json")],
                )

        if field.option_source != "model":
            return request.make_response(
                json.dumps({"success": True, "options": field.get_manual_options()}),
                headers=[("Content-Type", "application/json")],
            )

        opts = field.get_dynamic_options()
        return request.make_response(
            json.dumps({"success": True, "options": opts}),
            headers=[("Content-Type", "application/json")],
        )

    # --------------------------------------------------
    # BRANCHING (OPTIONAL)
    # --------------------------------------------------
    @http.route(
        "/smart_form/branch/<string:token>",
        type="http",
        auth="public",
        website=True,
        csrf=False,
        methods=["POST"],
    )
    def branch(self, token, **kw):

        form = request.env["smart.form"].sudo().search(
            [("token", "=", token)],
            limit=1,
        )
        if not form:
            return request.make_response(
                json.dumps({"success": False, "next_token": None}),
                headers=[("Content-Type", "application/json")],
            )

        payload = request.get_json_data(silent=True) or {}
        answers = payload.get("answers") or {}

        rules = request.env["smart.form.branch.rule"].sudo().search(
            [("form_id", "=", form.id)],
            order="sequence,id",
        )

        def _match(rule, val):
            v = str(val or "").strip()
            want = (rule.value_text or "").strip()

            if rule.operator in ("in", "not in"):
                wanted = [x.strip() for x in want.split(",") if x.strip()]
                ok = v in wanted
                return ok if rule.operator == "in" else not ok

            if rule.operator == "contains":
                return want in v

            if rule.operator == "!=":
                return v != want

            return v == want

        next_form = None
        for r in rules:
            key = str(r.trigger_field_id.id)
            if key in answers and _match(r, answers.get(key)):
                next_form = r.target_form_id
                break

        if not next_form and rules and rules[0].fallback_form_id:
            next_form = rules[0].fallback_form_id

        return request.make_response(
            json.dumps({
                "success": True,
                "next_token": next_form.token if next_form else None,
            }),
            headers=[("Content-Type", "application/json")],
        )
