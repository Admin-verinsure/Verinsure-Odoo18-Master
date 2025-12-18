# -*- coding: utf-8 -*-
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


def _jsonrpc_error(msg, error_code="ERROR"):
    # type="json" responds 200; clients should check ok=false
    return {"ok": False, "error": {"code": error_code, "message": msg}}


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
        return _jsonrpc_error(
            "Server misconfiguration: missing system parameter 'invoice_poc.api_key'.",
            "SERVER_MISCONFIG"
        )
    if token != expected:
        return _jsonrpc_error("Unauthorized: missing/invalid bearer token.", "UNAUTHORIZED")

    return None


def _extract_params():
    """
    Robustly extract params for JSON routes.
    Accepts:
      {"params": {...}}
    and also nested:
      {"params": {"params": {...}}}
    """
    data = request.jsonrequest or {}
    params = data.get("params") or {}
    if isinstance(params, dict) and "params" in params and isinstance(params.get("params"), dict):
        params = params["params"]
    if not isinstance(params, dict):
        params = {}
    return params


class InvoicePocController(http.Controller):

    @http.route(
        "/invoice_poc/jsonrpc/invoices",
        type="json",
        auth="none",      # IMPORTANT: no Odoo login; we do Bearer auth ourselves
        methods=["POST"],
        csrf=False,
    )
    def create_invoice_jsonrpc(self, **kwargs):
        """
        Creates payload row → (policy+insurance if present) → creates & posts invoice → emails customer (no PDF attach).
        Requires: Authorization: Bearer <token set in invoice_poc.api_key>
        """
        err = _require_api_token()
        if err:
            return err

        rec = None
        try:
            payload = _extract_params()
            ext = payload.get("id") or payload.get("ref")
            if not ext:
                return _jsonrpc_error("Payload must include 'id' or 'ref'", "BAD_REQUEST")

            PayloadModel = request.env["invoice.poc.payload"].sudo()

            # Create payload row (idempotent)
            try:
                rec = PayloadModel.create({
                    "ext_id": ext,
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                })
            except Exception as e:
                # detect unique constraint safely
                is_unique = False
                if UniqueViolation:
                    cause = getattr(e, "__cause__", None)
                    is_unique = isinstance(cause, UniqueViolation)

                # fallback check (narrow)
                if not is_unique and "duplicate key value violates unique constraint" in str(e).lower():
                    is_unique = True

                if is_unique:
                    rec = PayloadModel.search([("ext_id", "=", ext)], limit=1)
                    if not rec:
                        raise
                else:
                    raise

            # Process payload via model (policy-first if present)
            if payload.get("policy"):
                move = rec.action_create_policy_and_invoice()
            else:
                move = rec.action_create_and_post_invoice()

            return {
                "ok": True,
                "ref": ext,
                "payload_id": rec.id,
                "invoice": _invoice_to_dict(move),
            }

        except Exception as e:
            # best-effort: store error on payload row
            if rec:
                try:
                    rec.sudo().write({"state": "error", "error_message": str(e)})
                except Exception:
                    pass
            return _jsonrpc_error(str(e), "SERVER_ERROR")

    @http.route(
        "/invoice_poc/jsonrpc/invoices/get",
        type="json",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def get_invoice_by_ref(self, **kwargs):
        err = _require_api_token()
        if err:
            return err

        params = _extract_params()
        ext = params.get("ref") or params.get("id")
        if not ext:
            return _jsonrpc_error("Missing 'ref' (or 'id') in params", "BAD_REQUEST")

        rec = request.env["invoice.poc.payload"].sudo().search([("ext_id", "=", ext)], limit=1)
        if not rec or not rec.move_id:
            return _jsonrpc_error(f"No invoice found for '{ext}'", "NOT_FOUND")

        return {
            "ok": True,
            "ref": ext,
            "payload_id": rec.id,
            "invoice": _invoice_to_dict(rec.move_id.sudo()),
        }
