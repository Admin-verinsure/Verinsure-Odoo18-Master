import json
import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SmartFormPublic(http.Controller):

    # ---------------------------------------------------------------
    # Public form page
    # ---------------------------------------------------------------
    @http.route("/smart_form/<string:token>", type="http", auth="public",
                website=True, sitemap=False)
    def smart_form_page(self, token, **kw):
        form = request.env["smart.form"].sudo().search(
            [("token", "=", token), ("active", "=", True)], limit=1
        )
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

    # ---------------------------------------------------------------
    # Dynamic options endpoint
    # ---------------------------------------------------------------
    @http.route("/smart_form/options/<int:field_id>", type="http", auth="public",
                website=True, csrf=False)
    def smart_form_options(self, field_id, token=None, **kw):
        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(
                json.dumps({"success": False, "options": []}),
                [("Content-Type", "application/json")],
            )

        if token:
            form = request.env["smart.form"].sudo().search(
                [("token", "=", token)], limit=1
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

    # ---------------------------------------------------------------
    # Branching evaluation (JSON RPC)
    # ---------------------------------------------------------------
    @http.route("/smart_form/branching/<string:token>", type="json", auth="public",
                website=True, csrf=False)
    def smart_form_branching(self, token, **kw):
        form = request.env["smart.form"].sudo().search(
            [("token", "=", token), ("active", "=", True)], limit=1
        )
        if not form:
            return {"success": False, "next_token": None, "reason": "not_found"}

        answers = (kw or {}).get("answers") or {}
        next_form, reason = self._eval_next_form(form, answers)
        return {
            "success": True,
            "next_token": next_form.token if next_form else None,
            "reason": reason,
        }

    # ---------------------------------------------------------------
    # Form submission
    # ---------------------------------------------------------------
    @http.route("/smart_form/submit", type="http", auth="public",
                website=True, csrf=False)
    def smart_form_submit(self, **post):
        token = post.get("token")
        form = request.env["smart.form"].sudo().search(
            [("token", "=", token), ("active", "=", True)], limit=1
        )
        if not form:
            return request.not_found()

        # Create stub submission early so attachments can reference it
        submission = request.env["smart.form.submission"].sudo().create({
            "form_id": form.id,
            "data_json": "{}",
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent", ""),
        })

        data = {}
        answers_by_id = {}
        files = request.httprequest.files

        for f in form.field_ids.sudo():
            key = f.name or ("field_%s" % f.id)

            if f.field_type == "subheading":
                continue

            if f.field_type == "file":
                fs = files.get(key)
                if fs and getattr(fs, "filename", ""):
                    content = fs.read()
                    request.env["ir.attachment"].sudo().create({
                        "name": fs.filename,
                        "datas": base64.b64encode(content),
                        "res_model": "smart.form.submission",
                        "res_id": submission.id,
                        "mimetype": getattr(fs, "mimetype", None)
                                    or "application/octet-stream",
                    })
                    data[key] = fs.filename
                    answers_by_id[str(f.id)] = {"value": fs.filename,
                                                "label": fs.filename}
                else:
                    data[key] = ""
                    answers_by_id[str(f.id)] = ""
                continue

            if f.field_type == "checkbox":
                vals = request.httprequest.form.getlist("%s[]" % key)
                data[key] = vals
                answers_by_id[str(f.id)] = vals
                continue

            val = post.get(key) or ""
            data[key] = val

            if f.field_type in ("select", "radio"):
                label = None
                try:
                    for o in (f.get_options() or []):
                        if str(o.get("value")) == str(val):
                            label = o.get("label")
                            break
                except Exception:
                    label = None
                answers_by_id[str(f.id)] = {"value": val, "label": label or val}
            else:
                answers_by_id[str(f.id)] = val

        # Optional: create / link a record in the selected target model
        target_model = None
        target_res_id = None
        try:
            if form.target_model_id and form.target_model_id.model:
                target_model = form.target_model_id.model

                # Safety deny-list for public-facing forms
                deny = {
                    "res.users", "ir.config_parameter", "ir.model",
                    "ir.model.fields", "ir.ui.view", "ir.ui.menu",
                    "ir.actions.actions", "ir.actions.server",
                    "ir.cron", "ir.rule", "ir.module.module",
                }
                if target_model not in deny:
                    try:
                        Model = request.env[target_model].sudo()
                    except Exception:
                        Model = None

                    if Model:
                        mf = Model._fields
                        vals = {}
                        for f in form.field_ids:
                            tech = (f.name or "").strip()
                            if not tech or tech not in mf:
                                continue
                            v = data.get(tech)
                            if v in (None, "", False):
                                continue
                            if isinstance(v, dict) and (
                                    "content" in v or "filename" in v):
                                continue
                            field_def = mf[tech]
                            try:
                                if field_def.type in ("char", "text", "html"):
                                    vals[tech] = str(v)
                                elif field_def.type == "boolean":
                                    vals[tech] = (
                                        v if isinstance(v, bool)
                                        else str(v).lower() in
                                        ("1", "true", "yes", "on")
                                    )
                                elif field_def.type == "integer":
                                    vals[tech] = int(v)
                                elif field_def.type in ("float", "monetary"):
                                    vals[tech] = float(v)
                                elif field_def.type in ("date", "datetime"):
                                    vals[tech] = v
                                elif field_def.type == "selection":
                                    allowed = {k for k, _ in
                                               (field_def.selection or [])}
                                    if str(v) in allowed:
                                        vals[tech] = str(v)
                                elif field_def.type == "many2one":
                                    if str(v).isdigit():
                                        vals[tech] = int(v)
                            except Exception:
                                continue

                        # Auto-fill required `name` from common identifiers
                        if "name" in mf and not vals.get("name"):
                            for k in ("email", "mobile", "phone"):
                                if vals.get(k):
                                    vals["name"] = vals[k]
                                    break

                        # Duplicate prevention
                        existing = None
                        if vals:
                            for k in ("email", "mobile", "phone", "vat", "name"):
                                if vals.get(k):
                                    try:
                                        existing = Model.search(
                                            [(k, "=", vals[k])], limit=1)
                                    except Exception:
                                        existing = None
                                    if existing:
                                        break

                        if existing:
                            target_res_id = existing.id
                        elif vals:
                            rec = Model.create(vals)
                            target_res_id = rec.id
        except Exception as e:
            _logger.exception(
                "Smart Form: target model create/link failed: %s", e)

        write_vals = {"data_json": json.dumps(data, ensure_ascii=False)}
        if target_model and target_res_id:
            write_vals["target_model"] = target_model
            write_vals["target_res_id"] = target_res_id

        submission.sudo().write(write_vals)

        # Server-side branching fallback (works even if JS fails)
        next_form, _reason = self._eval_next_form(form, answers_by_id)
        if next_form and next_form.token:
            return request.redirect("/smart_form/%s" % next_form.token)

        return request.render("smart_form_builder.smart_form_thanks",
                              {"form": form})

    # ---------------------------------------------------------------
    # Shared branching logic
    # ---------------------------------------------------------------
    def _eval_next_form(self, form, answers):
        """Evaluate branch rules and return (next_form | None, reason_str).

        reason values:
          'target'   – matched a rule that has a target form
          'submit'   – matched a rule with no target (submit here)
          'fallback' – no match, using first fallback form
          'none'     – no match and no fallback
        """
        rules = request.env["smart.form.branch.rule"].sudo().search(
            [("form_id", "=", form.id)], order="sequence,id"
        )

        def _vals(v):
            if isinstance(v, dict):
                out = []
                for k in ("value", "label"):
                    s = str(v.get(k) or "").strip()
                    if s:
                        out.append(s)
                return out
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        def _match(rule, val):
            vals_l = [v.lower() for v in _vals(val)]
            want_l = (rule.value_text or "").strip().lower()
            op = rule.operator or "="

            if op in ("in", "not in"):
                wanted = [x.strip().lower() for x in want_l.split(",") if x.strip()]
                ok = any(v in wanted for v in vals_l)
                return ok if op == "in" else not ok

            if op == "contains":
                return any(want_l in v for v in vals_l)

            if op == "!=":
                if not vals_l:
                    return want_l != ""
                return all(v != want_l for v in vals_l)

            # default "="
            if want_l == "" and not vals_l:
                return True
            return any(v == want_l for v in vals_l)

        first_fallback = None
        for r in rules:
            if not first_fallback and r.fallback_form_id:
                first_fallback = r.fallback_form_id

            val = answers.get(str(r.trigger_field_id.id), "")
            if _match(r, val):
                if r.target_form_id:
                    return r.target_form_id, "target"
                return None, "submit"

        if first_fallback:
            return first_fallback, "fallback"
        return None, "none"
