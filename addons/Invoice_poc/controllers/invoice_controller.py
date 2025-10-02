# Controller layer: defines HTTP/JSON endpoints that external systems can call
from odoo import http
from odoo.http import request

class InvoicePocController(http.Controller):

    @http.route(
        "/invoice_poc/jsonrpc/invoices",
        type="json",       # JSON-RPC request/response
        auth="api_key",    # "Authorization: Bearer <API_KEY>"
        methods=["POST"],
        csrf=False
    )
    def create_invoice_jsonrpc(self, **params):
        """
        Expected JSON-RPC body:
        {
          "jsonrpc": "2.0",
          "method": "call",
          "id": 1,
          "params": { ... invoice payload ... }
        }
        """
        try:
            u = request.env.user
            payload = request.jsonrequest.get("params") or {}

            # Store raw payload (for traceability)
            rec = request.env["invoice.poc.payload"].sudo().create({
                "ext_id": payload.get("id") or payload.get("ref"),
                "payload_json": request.make_json(payload),
            })

            # Create & post invoice under sudo BUT with the caller's company in context
            move = rec.sudo().with_context(
                allowed_company_ids=[u.company_id.id],
            ).action_create_and_post_invoice()

            # IMPORTANT: Reassign to the caller so it shows under "My Invoices" and right company
            move.sudo().write({
                "invoice_user_id": u.id,
                "company_id": u.company_id.id,
            })

            return {
                "ok": True,
                "invoice_id": move.id,
                "invoice_number": move.name,
                "state": move.state,
                "total": move.amount_total,
                "currency": move.currency_id.name,
                # open in backend without /web
                "backend_url": f"/odoo/action-account.action_move_out_invoice_type?res_id={move.id}&cids={u.company_id.id}",
            }

        except Exception as e:
            if "rec" in locals():
                rec.sudo().write({"state": "error", "error_message": str(e)})
            return {"ok": False, "error": str(e)}
