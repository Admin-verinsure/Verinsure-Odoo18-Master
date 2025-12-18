from odoo import http
from odoo.http import request
import json

# optional: precise handling of unique constraint race/idempotency
try:
    from psycopg2.errors import UniqueViolation  # type: ignore
except Exception:
    UniqueViolation = None


def _policy_to_dict(move):
    p = getattr(move, 'policy_id', False)
    if not p:
        return None
    return {
        "id": p.id,
        "name": p.name,
        "policy_no": getattr(p, 'policy_no', None),
        "policy_type_id": getattr(p, 'policy_type_id', False) and p.policy_type_id.id or None,
        "policy_type": getattr(p, 'policy_type_id', False) and p.policy_type_id.name or None,
        "start_date": getattr(p, 'start_date', None) and p.start_date.isoformat(),
        "end_date": getattr(p, 'end_date', None) and p.end_date.isoformat(),
        "sum_insured": getattr(p, 'sum_insured', None),
        "premium": getattr(p, 'premium', None),
        "insurer": getattr(p, 'insurer', None),
    }


def _invoice_to_dict(move):
    lines = [{
        "id": l.id,
        "name": l.name,
        "quantity": l.quantity,
        "price_unit": l.price_unit,
        "price_subtotal": l.price_subtotal,
        "taxes": [t.description or t.name for t in l.tax_ids],
    } for l in move.invoice_line_ids]

    return {
        "id": move.id,
        "number": move.name,
        "state": move.state,
        "move_type": move.move_type,
        "company": {"id": move.company_id.id, "name": move.company_id.name},
        "partner": {
            "id": move.partner_id.id,
            "name": move.partner_id.display_name,
            "email": move.partner_id.email,
        },
        "currency": move.currency_id and move.currency_id.name,
        "amount_untaxed": move.amount_untaxed,
        "amount_tax": move.amount_tax,
        "amount_total": move.amount_total,
        "invoice_date": move.invoice_date and move.invoice_date.isoformat(),
        "due_date": move.invoice_date_due and move.invoice_date_due.isoformat(),
        "payment_term": move.invoice_payment_term_id and {
            "id": move.invoice_payment_term_id.id,
            "name": move.invoice_payment_term_id.name,
        },
        "payment_reference": move.payment_reference,
        "salesperson": (
            {
                "id": move.invoice_user_id.id,
                "name": move.invoice_user_id.name,
                "login": move.invoice_user_id.login,
            } if move.invoice_user_id else None
        ),
        "journal": {"id": move.journal_id.id, "name": move.journal_id.name},
        "tax_totals": move.tax_totals,
        "lines": lines,
        "policy": _policy_to_dict(move),
        "backend_url": f"/odoo/action-account.action_move_out_invoice_type?res_id={move.id}&cids={move.company_id.id}",
    }


def _jsonrpc_error(msg, code=200):
    # type="json" always returns 200 to the client; include ok=False + error message in body
    return {"ok": False, "error": msg}


def _require_api_token():
    """
    Validate Authorization: Bearer <token> against ir.config_parameter('invoice_poc.api_key').
    Returns None if valid; json error dict if invalid.
    """
    cfg = request.env['ir.config_parameter'].sudo()
    expected = (cfg.get_param('invoice_poc.api_key') or '').strip()
    auth = (request.httprequest.headers.get('Authorization') or '').strip()
    token = ''
    if auth.lower().startswith('bearer '):
        token = auth[7:].strip()

    if not expected:
        return _jsonrpc_error("Server misconfiguration: missing system parameter 'invoice_poc.api_key'.")
    if token != expected:
        return _jsonrpc_error("Unauthorized: missing/invalid bearer token.")
    return None


class InvoicePocController(http.Controller):

    @http.route(
        "/invoice_poc/jsonrpc/invoices",
        type="json",
        auth="public",            # <- Option B: use our own Bearer token check
        methods=["POST"],
        csrf=False,
    )
    def create_invoice_jsonrpc(self, **kwargs):
        """
        Creates payload row → (policy+insurance if present) → creates & posts invoice → emails customer (no PDF attach).
        Requires: Authorization: Bearer <token set in invoice_poc.api_key>
        """
        # Header auth
        err = _require_api_token()
        if err:
            return err

        rec = None
        try:
            payload = request.jsonrequest.get("params") or {}
            ext = payload.get("id") or payload.get("ref")
            if not ext:
                return _jsonrpc_error("Payload must include 'id' or 'ref'")

            # Create payload row (idempotent)
            try:
                rec = request.env["invoice.poc.payload"].sudo().create({
                    "ext_id": ext,
                    "payload_json": json.dumps(payload),
                })
            except Exception as e:
                if UniqueViolation and isinstance(e.__cause__, UniqueViolation) or "unique" in str(e).lower():
                    rec = request.env["invoice.poc.payload"].sudo().search([("ext_id", "=", ext)], limit=1)
                    if not rec:
                        raise
                else:
                    raise

            # Process payload via model (policy-first if present)
            move = (
                rec.sudo().action_create_policy_and_invoice()
                if payload.get("policy")
                else rec.sudo().action_create_and_post_invoice()
            )

            # Commit so invoice + mail status are visible immediately
            request.env.cr.commit()

            return {
                "ok": True,
                "ref": ext,
                "payload_id": rec.id,
                "invoice": _invoice_to_dict(move),
            }

        except Exception as e:
            if rec:
                try:
                    rec.sudo().write({"state": "error", "error_message": str(e)})
                    request.env.cr.commit()
                except Exception:
                    pass
            return _jsonrpc_error(str(e))

    @http.route(
        "/invoice_poc/jsonrpc/invoices/get",
        type="json",
        auth="public",            # <- same token gate
        methods=["POST"],
        csrf=False,
    )
    def get_invoice_by_ref(self, **kwargs):
        # Header auth
        err = _require_api_token()
        if err:
            return err

        payload = request.jsonrequest.get("params") or {}
        ext = payload.get("ref") or payload.get("id")
        if not ext:
            return _jsonrpc_error("Missing 'ref' (or 'id') in params")

        rec = request.env["invoice.poc.payload"].sudo().search([("ext_id", "=", ext)], limit=1)
        if not rec or not rec.move_id:
            return _jsonrpc_error(f"No invoice found for '{ext}'")

        return {
            "ok": True,
            "ref": ext,
            "payload_id": rec.id,
            "invoice": _invoice_to_dict(rec.move_id.sudo()),
        }
