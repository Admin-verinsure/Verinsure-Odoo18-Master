# invoice_poc/controllers/invoice_controller.py
from odoo import http
from odoo.http import request
import json

class InvoicePocController(http.Controller):

    # For POC: auth='user' (must be logged in). Later you can switch to public + token.
    @http.route("/invoice_poc/create", type="json", auth="user", csrf=False)
    def invoice_poc_create(self, **kwargs):
        try:
            raw = request.httprequest.data or b"{}"
            payload = json.loads(raw.decode("utf-8"))

            rec = request.env["invoice.poc.payload"].sudo().create({
                "ext_id": payload.get("id") or payload.get("ref"),
                "payload_json": json.dumps(payload, ensure_ascii=False),
            })
            move = rec.sudo().action_create_and_post_invoice()
            return {
                "status": "ok",
                "odoo_move_id": move.id,
                "number": move.name,
                "state": move.state,
            }#----
        except Exception as e:
            if "rec" in locals():
                rec.sudo().write({"state": "error", "error_message": str(e)})
            return {"status": "error", "error": str(e)}
          
          
          
