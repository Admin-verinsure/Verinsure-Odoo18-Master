import json
import base64
import logging

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)


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

    def _eval_next_form(self, form, answers):
        """Return (next_form_record_or_None, reason_str). reason:
        - 'target' : matched target
        - 'submit' : matched but no target, so submit
        - 'fallback' : no match, using fallback
        - 'none' : no match and no fallback
        """
        rules = request.env["smart.form.branch.rule"].sudo().search(
            [("form_id", "=", form.id)],
            order="sequence,id"
        )

        def _vals(v):
            # Accept dict {value,label} or list or scalar -> list[str]
            if isinstance(v, dict):
                out = []
                if v.get("value") not in (None, ""):
                    out.append(str(v.get("value")).strip())
                if v.get("label") not in (None, ""):
                    out.append(str(v.get("label")).strip())
                return [x for x in out if x]
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        def _match(rule, val):
            vals = _vals(val)
            want = (rule.value_text or "").strip()

            # normalize
            vals_l = [v.lower() for v in vals]
            want_l = want.lower()

            op = rule.operator or "="

            if op in ("in", "not in"):
                wanted = [x.strip().lower() for x in want.split(",") if x.strip()]
                ok = any(v in wanted for v in vals_l)
                return ok if op == "in" else (not ok)

            if op == "contains":
                return any(want_l in v for v in vals_l)

            if op == "!=":
                # if no value selected, treat as not equal unless want is empty
                if not vals_l:
                    return want_l != ""
                return all(v != want_l for v in vals_l)

            # default '='
            if want_l == "" and not vals_l:
                return True
            return any(v == want_l for v in vals_l)

        first_fallback = None

        for r in rules:
            if not first_fallback and r.fallback_form_id:
                first_fallback = r.fallback_form_id

            key = str(r.trigger_field_id.id)

            # if missing, treat as empty string to allow rules like !=
            val = answers.get(key, "")

            if _match(r, val):
                if r.target_form_id:
                    return r.target_form_id, "target"
                return None, "submit"

        if first_fallback:
            return first_fallback, "fallback"
        return None, "none"
    @http.route("/smart_form/branching/<string:token>", type="json", auth="public", website=True, csrf=False)
    def smart_form_branching(self, token, **kw):
        form = request.env["smart.form"].sudo().search([("token", "=", token), ("active", "=", True)], limit=1)
        if not form:
            return {"success": False, "next_token": None, "reason": "not_found"}

        payload = kw or {}
        answers = payload.get("answers") or {}

        next_form, reason = self._eval_next_form(form, answers)
        return {"success": True, "next_token": next_form.token if next_form else None, "reason": reason}
    @http.route("/smart_form/submit", type="http", auth="public", website=True, csrf=False)
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
        answers_by_id = {}
        files = request.httprequest.files

        for f in form.field_ids.sudo():
            key = f.name or f"field_{f.id}"

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
                        "mimetype": getattr(fs, "mimetype", None) or "application/octet-stream",
                    })
                    data[key] = fs.filename
                    answers_by_id[str(f.id)] = {"value": fs.filename, "label": fs.filename}
                else:
                    data[key] = ""
                    answers_by_id[str(f.id)] = ""
                continue

            if f.field_type == "checkbox":
                vals = request.httprequest.form.getlist(f"{key}[]")
                data[key] = vals
                answers_by_id[str(f.id)] = vals
                continue

            val = post.get(key) or ""
            data[key] = val

            # For select/radio, also attach label for matching human text
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

                # Safety deny-list — never allow writes to sensitive system models
                deny = {
                    "res.users", "ir.config_parameter", "ir.model", "ir.model.fields",
                    "ir.ui.view", "ir.ui.menu", "ir.actions.actions", "ir.actions.server",
                    "ir.cron", "ir.rule", "ir.module.module",
                }
                Model = None
                if target_model not in deny:
                    try:
                        Model = request.env[target_model].sudo()
                    except Exception:
                        Model = None

                if Model is not None:
                    mf = Model._fields
                    vals = {}

                    for fld in form.field_ids:
                        tech = (fld.name or "").strip()
                        if not tech or tech not in mf:
                            continue

                        v = data.get(tech)

                        # Skip empty values
                        if v is None or v == "" or v is False:
                            continue
                        # Skip file upload placeholders
                        if isinstance(v, dict) and ("content" in v or "filename" in v):
                            continue

                        target_field = mf[tech]
                        try:
                            if target_field.type in ("char", "text", "html"):
                                # Lists (checkbox) -> comma-separated string
                                if isinstance(v, list):
                                    vals[tech] = ", ".join(str(x) for x in v if x != "")
                                elif isinstance(v, dict):
                                    vals[tech] = str(v.get("label") or v.get("value") or "")
                                else:
                                    vals[tech] = str(v)

                            elif target_field.type == "boolean":
                                if isinstance(v, bool):
                                    vals[tech] = v
                                else:
                                    vals[tech] = str(v).lower() in ("1", "true", "yes", "on")

                            elif target_field.type == "integer":
                                vals[tech] = int(float(str(v).replace(",", "")))

                            elif target_field.type in ("float", "monetary"):
                                vals[tech] = float(str(v).replace(",", ""))

                            elif target_field.type in ("date", "datetime"):
                                vals[tech] = str(v) if v else False

                            elif target_field.type == "selection":
                                # field.selection can be a callable in Odoo 17+/18
                                sel = target_field.selection
                                if callable(sel):
                                    try:
                                        sel = sel(Model)
                                    except Exception:
                                        sel = []
                                allowed = {k for k, _ in (sel or [])}
                                str_v = str(v)
                                if str_v in allowed:
                                    vals[tech] = str_v

                            elif target_field.type == "many2one":
                                # Accept numeric ID (from DB-sourced select) or name
                                str_v = str(v).strip()
                                if str_v.isdigit():
                                    vals[tech] = int(str_v)

                            elif target_field.type in ("many2many", "one2many"):
                                # Accept list of IDs or a single ID
                                if isinstance(v, list):
                                    ids = []
                                    for item in v:
                                        try:
                                            ids.append(int(item))
                                        except (ValueError, TypeError):
                                            pass
                                    if ids:
                                        vals[tech] = [(6, 0, ids)]
                                elif str(v).isdigit():
                                    vals[tech] = [(6, 0, [int(v)])]

                        except Exception:
                            continue

                    # Auto-fill required `name` field (e.g. res.partner) from
                    # common identifiers when not explicitly provided
                    if "name" in mf and not vals.get("name"):
                        for k in ("name", "email", "mobile", "phone"):
                            candidate = data.get(k, "")
                            if candidate and isinstance(candidate, str):
                                vals["name"] = candidate
                                break

                    if vals:
                        # Duplicate prevention — search by unique identifiers
                        existing = None
                        for k in ("email", "mobile", "phone", "vat", "name"):
                            if k in vals and vals[k]:
                                try:
                                    existing = Model.search([(k, "=", vals[k])], limit=1)
                                except Exception:
                                    existing = None
                                if existing:
                                    break

                        if existing:
                            # Update existing record with any new values
                            try:
                                existing.write(vals)
                            except Exception as e:
                                _logger.warning(
                                    "Smart Form: could not update existing %s #%s: %s",
                                    target_model, existing.id, e)
                            target_res_id = existing.id
                        else:
                            try:
                                rec = Model.create(vals)
                                target_res_id = rec.id
                            except Exception as e:
                                _logger.error(
                                    "Smart Form: could not create %s record. vals=%s error=%s",
                                    target_model, vals, e)

        except Exception as e:
            _logger.exception("Smart Form: target model create/link failed: %s", e)

        # Save record link on submission (even if not created)
        if target_model and target_res_id:
            submission.sudo().write({
                "target_model": target_model,
                "target_res_id": target_res_id,
            })

        submission.sudo().write({
            "data_json": json.dumps(data, ensure_ascii=False),
        })

        # ✅ Server-side branching: always works even if JS fails
        next_form, reason = self._eval_next_form(form, answers_by_id)
        if next_form and next_form.token:
            return request.redirect(f"/smart_form/{next_form.token}")

        return request.render("smart_form_builder.smart_form_thanks", {"form": form})

