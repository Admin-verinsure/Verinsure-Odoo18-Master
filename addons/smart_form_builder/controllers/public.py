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
        return request.render("smart_form_builder.smart_form_page", {"form": form})

    @http.route("/smart_form/options/<int:field_id>", type="http", auth="public", website=True, csrf=False)
    def smart_form_options(self, field_id, token=None, **kw):
        field = request.env["smart.form.field"].sudo().browse(field_id)
        if not field.exists():
            return request.make_response(json.dumps({"success": False, "options": []}), [("Content-Type","application/json")])

        # Optional token check (field belongs to that form)
        if token:
            form = request.env["smart.form"].sudo().search([("token","=",token)], limit=1)
            if not form or field.form_id.id != form.id:
                return request.make_response(json.dumps({"success": False, "options": []}), [("Content-Type","application/json")])

        opts = field.get_options()
        return request.make_response(json.dumps({"success": True, "options": opts}), [("Content-Type","application/json")])

    @http.route("/smart_form/submit", type="http", auth="public", website=True, csrf=False, methods=["POST"])
    def smart_form_submit(self, **post):
token = post.get("token")
form = request.env["smart.form"].sudo().search([("token","=",token),("active","=",True)], limit=1)
if not form:
    return request.not_found()

# Create submission first to attach files
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

    data[key] = post.get(key)

submission.sudo().write({
    "data_json": json.dumps(data, ensure_ascii=False),
})

return request.render("smart_form_builder.smart_form_thanks", {"form": form})
