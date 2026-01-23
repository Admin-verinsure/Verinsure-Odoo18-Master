import json
import base64
from odoo import http
from odoo.http import request

class SmartFormPublic(http.Controller):

    @http.route("/smart_form/<string:token>", type="http", auth="public", website=True, sitemap=False)
    def smart_form_page(self, token, **kw):
        form = request.env["smart.form"].sudo().search([("token","=",token),("active","=",True)], limit=1)
        if not form:
            return request.not_found()
        rules = []
        for r in form.logic_rule_ids.sudo():
            rules.append({"trigger": r.trigger_field_id.id, "op": r.operator, "value": r.value_text or "", "action": r.action, "target": r.target_field_id.id})
        return request.render("smart_form_builder.smart_form_page", {"form": form, "rules_json": json.dumps(rules)})

    @http.route("/smart_form/options/<int:field_id>", type="http", auth="public", website=True, csrf=False)
    def smart_form_options(self, field_id, token=None, **kw):
        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(json.dumps({"success": False, "options": []}), [("Content-Type","application/json")])

        if token:
            form = request.env["smart.form"].sudo().search([("token","=",token)], limit=1)
            if not form or field.form_id.id != form.id:
                return request.make_response(json.dumps({"success": False, "options": []}), [("Content-Type","application/json")])

        return request.make_response(json.dumps({"success": True, "options": field.get_options()}),
                                    [("Content-Type","application/json")])

    @http.route("/smart_form/submit", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def smart_form_submit(self, **post):
        token = post.get("token")
        form = request.env["smart.form"].sudo().search([("token","=",token),("active","=",True)], limit=1)
        if not form:
            return request.not_found()

        data = {}
        files = request.httprequest.files

        # create submission first so attachments can link
        submission = request.env["smart.form.submission"].sudo().create({
            "form_id": form.id,
            "data_json": "{}",
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent"),
        })

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

            data[key] = post.get(key)

        # LDAP enrichment (optional)
ldap_payload = {}
try:
    enabled = request.env["ir.config_parameter"].sudo().get_param("sfb.ldap.enabled") in ("True", "1", True)
except Exception:
    enabled = False

if enabled:
    first_name = (data.get("first_name") or data.get("First Name") or data.get("first") or "").strip()
    last_name = (data.get("last_name") or data.get("Last Name") or data.get("last") or "").strip()
    email = (data.get("email") or data.get("Email") or "").strip()
    if first_name and last_name and email:
        try:
            server_uri = request.env["ir.config_parameter"].sudo().get_param("sfb.ldap.server_uri") or ""
            bind_dn = request.env["ir.config_parameter"].sudo().get_param("sfb.ldap.bind_dn") or ""
            bind_pw = request.env["ir.config_parameter"].sudo().get_param("sfb.ldap.bind_password") or ""
            base_dn = request.env["ir.config_parameter"].sudo().get_param("sfb.ldap.base_dn") or ""
            filt_tpl = request.env["ir.config_parameter"].sudo().get_param("sfb.ldap.filter") or ""
            if server_uri and base_dn and filt_tpl:
                try:
                    from ldap3 import Server, Connection
                    server = Server(server_uri)
                    conn = Connection(server, user=bind_dn or None, password=bind_pw or None, auto_bind=True)
                    ldap_filter = filt_tpl.format(first_name=first_name, last_name=last_name, email=email)
                    conn.search(search_base=base_dn, search_filter=ldap_filter, attributes=["*"])
                    if conn.entries:
                        e = conn.entries[0]
                        ldap_payload = json.loads(e.entry_to_json()).get("attributes", {})
                    conn.unbind()
                except Exception:
                    ldap_payload = {}
        except Exception:
            ldap_payload = {}

        submission.sudo().write({
            "data_json": json.dumps(data, ensure_ascii=False),
            "ldap_json": json.dumps(ldap_payload, ensure_ascii=False) if ldap_payload else False,
        })

        return request.render("smart_form_builder.smart_form_thanks", {"form": form})
