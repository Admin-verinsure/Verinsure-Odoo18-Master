import json
import base64
import logging

from odoo import http
from odoo.http import request


class SmartFormPublic(http.Controller):

    _logger = logging.getLogger(__name__)

    def _create_target_record(self, form, data):
        """Create a record in the selected target model (if configured).
        Mapping rule: SmartFormField.technical_name -> target model field name.
        Unmapped/unknown fields are ignored.
        """
        if not form.target_model_id:
            return None
        model_name = form.target_model_id.model
        # Hard safety deny-list for sensitive technical models
        deny = {
            "ir.model", "ir.model.fields", "ir.config_parameter", "res.users",
            "res.groups", "ir.rule", "ir.ui.view", "ir.ui.menu", "ir.actions.act_window",
            "ir.attachment",
        }
        if model_name in deny:
            self._logger.warning("Smart Form target model denied: %s (form %s)", model_name, form.id)
            return None

        Model = request.env[model_name].sudo()
        fields_map = Model._fields

        vals = {}
        for f in form.field_ids.sudo():
            key = f.name or f"field_{f.id}"
            if key not in data:
                continue
            if key not in fields_map:
                continue

            field = fields_map[key]
            if getattr(field, "readonly", False) or not getattr(field, "store", True):
                continue

            v = data.get(key)

            try:
                ftype = field.type
                if ftype in ("char", "text", "html"):
                    if isinstance(v, list):
                        vals[key] = ", ".join([str(x) for x in v if x not in (None, "")])
                    else:
                        vals[key] = str(v) if v is not None else False

                elif ftype == "boolean":
                    if isinstance(v, str):
                        vals[key] = v.lower() in ("1", "true", "yes", "on")
                    else:
                        vals[key] = bool(v)

                elif ftype == "integer":
                    if isinstance(v, list):
                        v = v[0] if v else False
                    vals[key] = int(v) if v not in (None, "", False) else False

                elif ftype == "float":
                    if isinstance(v, list):
                        v = v[0] if v else False
                    vals[key] = float(v) if v not in (None, "", False) else False

                elif ftype == "date":
                    if v:
                        vals[key] = v  # Odoo accepts YYYY-MM-DD string
                elif ftype == "datetime":
                    if v:
                        vals[key] = v  # Odoo accepts ISO datetime string

                elif ftype == "selection":
                    if isinstance(v, list):
                        vals[key] = v[0] if v else False
                    else:
                        vals[key] = v

                elif ftype == "many2one":
                    if isinstance(v, list):
                        v = v[0] if v else False
                    if v in (None, "", False):
                        continue
                    if isinstance(v, int):
                        vals[key] = v
                    elif isinstance(v, str) and v.isdigit():
                        vals[key] = int(v)
                    else:
                        # If not an ID, skip (safe behavior)
                        continue

                elif ftype in ("many2many", "one2many"):
                    # Accept list of ids (strings or ints)
                    if not v:
                        continue
                    if not isinstance(v, list):
                        v = [v]
                    ids = []
                    for item in v:
                        if isinstance(item, int):
                            ids.append(item)
                        elif isinstance(item, str) and item.isdigit():
                            ids.append(int(item))
                    if ids:
                        vals[key] = [(6, 0, ids)]

                else:
                    # Unknown / unsupported field types: ignore safely
                    continue
            except Exception:
                # Ignore conversion errors per-field
                continue

        if not vals:
            return None

        return Model.create(vals)

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

        submission.sudo().write({
            "data_json": json.dumps(data, ensure_ascii=False),
        })

        # Optional: create a record in a selected Odoo model (unmapped fields are ignored)
        try:
            rec = self._create_target_record(form, data)
            if rec:
                submission.sudo().write({"target_model": rec._name, "target_res_id": rec.id})
        except Exception as e:
            self._logger.exception("Smart Form: target model create failed for form %s: %s", form.id, e)


        # ✅ Server-side branching: always works even if JS fails
        next_form, reason = self._eval_next_form(form, answers_by_id)
        if next_form and next_form.token:
            return request.redirect(f"/smart_form/{next_form.token}")

        return request.render("smart_form_builder.smart_form_thanks", {"form": form})

