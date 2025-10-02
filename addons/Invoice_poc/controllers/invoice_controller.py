# Controller layer: defines HTTP/JSON endpoints that external systems can call
from odoo import http
from odoo.http import request

class InvoicePocController(http.Controller):

    @http.route(
        "/invoice_poc/jsonrpc/invoices",
        type="json",      # Expect JSON-RPC request/response (not raw REST JSON)
        auth="api_key",   # Require "Authorization: Bearer <API_KEY>" header (Odoo 18)
        methods=["POST"], # Only allow POST
        csrf=False        # Disable CSRF (we use API key instead)
    )
    def create_invoice_jsonrpc(self, **params):
        """
        Expected JSON-RPC body (note the 'params' wrapper):
        {
          "jsonrpc": "2.0",
          "method": "call",
          "id": 1,
          "params": { ... your invoice payload ... }
        }
        """
        try:
            # request.jsonrequest is the already-parsed JSON-RPC request (a dict)
            # We pull the inner business payload from the "params" key.
            payload = request.jsonrequest.get("params") or {}

            # Create a payload record that stores the raw JSON for traceability.
            # - ext_id: external reference (used for idempotency if you add a unique constraint)
            # - payload_json: the exact JSON we received (serialized again by Odoo helper)
            rec = request.env["invoice.poc.payload"].sudo().create({
                "ext_id": payload.get("id") or payload.get("ref"),
                "payload_json": request.make_json(payload),
            })

            # Call your model method that maps the payload -> account.move and posts it.
            # sudo(): run with elevated rights appropriate for integration accounts.
            move = rec.sudo().action_create_and_post_invoice()

            # Return a compact success response the caller can use.
            # backend_url is a handy link to open the record in Odoo (no /web).
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
            # If we already created a payload record, persist the error on it for audit/debug.
            if "rec" in locals():
                rec.sudo().write({"state": "error", "error_message": str(e)})

            # Return a JSON-RPC-style error object (simple form).
            return {"ok": False, "error": str(e)}
