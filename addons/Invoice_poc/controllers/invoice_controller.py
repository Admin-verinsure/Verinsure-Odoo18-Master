from odoo import http
from odoo.http import request

class InvoicePocController(http.Controller):

    @http.route(
        "/invoice_poc/jsonrpc/invoices",
        type="json",
        auth="api_key",
        methods=["POST"],
        csrf=False
    )
    def create_invoice_jsonrpc(self, **params):
        try:
            payload = request.jsonrequest.get("params") or {}
            rec = request.env["invoice.poc.payload"].sudo().create({
                "ext_id": payload.get("id") or payload.get("ref"),
                "payload_json": request.make_json(payload),
            })
            move = rec.sudo().action_create_and_post_invoice()

            # PERMANENT: commit on success so callers immediately see the record
            request.env.cr.commit()

            return {
                "ok": True,
                "invoice_id": move.id,
                "invoice_number": move.name,
                "state": move.state,
                "total": move.amount_total,
                "currency": move.currency_id.name,
                "backend_url": f"/odoo/action-account.action_move_out_invoice_type?res_id={move.id}&cids={move.company_id.id}",
            }
        except Exception as e:
            if "rec" in locals():
                rec.sudo().write({"state": "error", "error_message": str(e)})
                request.env.cr.commit()  # persist the error on the payload too
            return {"ok": False, "error": str(e)}
