from odoo import http
from odoo.http import request

import base64, json

# optional: precise handling of unique constraint race/idempotency
try:
    from psycopg2.errors import UniqueViolation  # type: ignore
except Exception:  # pragma: no cover
    UniqueViolation = None


def _invoice_to_dict(move):
    """Serialize an account.move to a compact JSON-safe dict for API responses."""
    lines = []
    for l in move.invoice_line_ids:
        lines.append({
            "id": l.id,
            "name": l.name,
            "quantity": l.quantity,
            "price_unit": l.price_unit,
            "price_subtotal": l.price_subtotal,
            "taxes": [t.description or t.name for t in l.tax_ids],
        })
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
        "salesperson": {
            "id": move.invoice_user_id.id,
            "name": move.invoice_user_id.name,
            "login": move.invoice_user_id.login,
        } if move.invoice_user_id else None,
        "journal": {"id": move.journal_id.id, "name": move.journal_id.name},
        "tax_totals": move.tax_totals,  # already json-serializable
        "lines": lines,
        "backend_url": f"/odoo/action-account.action_move_out_invoice_type?res_id={move.id}&cids={move.company_id.id}",
    }


def _render_invoice_pdf_bytes(move):
    """
    Render the invoice PDF bytes using a robust list of likely report xmlids.
    Adjust ordering if you use a custom report.
    """
    Report = request.env['ir.actions.report'].sudo()
    candidates = [
        'account.report_invoice_with_payments',  # v16+
        'account.account_invoices',              # older
        'account.report_invoice_document',       # alt legacy
    ]
    last_err = None
    for xmlid in candidates:
        try:
            report = request.env.ref(xmlid, raise_if_not_found=False)
            if report:
                pdf_bytes, _ = Report._render_qweb_pdf(xmlid, [move.id])
                return pdf_bytes
        except Exception as e:
            last_err = e
            continue
    # fallback using report on the template used by the template id in move._get_report_base_filename?
    if last_err:
        raise last_err
    raise ValueError("No invoice report definition found to render PDF.")


def _create_pdf_attachment(move, pdf_bytes):
    """
    Create an ir.attachment for the PDF and return (attachment, pdf_url).
    """
    fname = (move.name or f"Invoice-{move.id}") + ".pdf"
    att = request.env['ir.attachment'].sudo().create({
        'name': fname,
        'res_model': 'account.move',
        'res_id': move.id,
        'type': 'binary',
        'mimetype': 'application/pdf',
        'datas': base64.b64encode(pdf_bytes),
    })
    pdf_url = f"/web/content/{att.id}?download=1&filename={att.name}"
    return att, pdf_url


class InvoicePocController(http.Controller):

    @http.route(
        "/invoice_poc/jsonrpc/invoices",
        type="json",
        auth="api_key",           # Expect: Authorization: Bearer <API_KEY>
        methods=["POST"],
        csrf=False,
    )
    def create_invoice_jsonrpc(self, **kwargs):
        """
        JSON-RPC 2.0 request expected:
        {
          "jsonrpc": "2.0",
          "method": "call",
          "id": 1,
          "params": {
             ...payload...,
             "callback_url": "https://your-dotnet/callback",     # optional
             "callback_api_key": "XYZ",                          # optional
             "return_pdf_b64": true                              # optional
          }
        }
        """
        rec = None
        try:
            payload = request.jsonrequest.get("params") or {}
            ext = payload.get("id") or payload.get("ref")  # cross-system key

            # Create payload row (idempotent by unique ext_id). If duplicate, reuse.
            try:
                rec = request.env["invoice.poc.payload"].sudo().create({
                    "ext_id": ext,
                    "payload_json": request.make_json(payload),
                })
            except Exception as e:
                if UniqueViolation and isinstance(e.__cause__, UniqueViolation) or "unique" in str(e).lower():
                    rec = request.env["invoice.poc.payload"].sudo().search([("ext_id", "=", ext)], limit=1)
                    if not rec:
                        raise
                else:
                    raise

            move = rec.move_id
            if not move:
                move = rec.sudo().action_create_and_post_invoice()

            # Render PDF, attach, and prepare response
            pdf_bytes = _render_invoice_pdf_bytes(move)
            att, pdf_url = _create_pdf_attachment(move, pdf_bytes)

            response = {
                "ok": True,
                "ref": ext,
                "payload_id": rec.id,
                "pdf_attachment_id": att.id,
                "pdf_url": pdf_url,
                "invoice": _invoice_to_dict(move),
            }
            if payload.get("return_pdf_b64"):
                response["pdf_base64"] = base64.b64encode(pdf_bytes).decode("ascii")

            # Push to callback if provided
            callback_url = (payload.get("callback_url") or "").strip()
            if callback_url:
                try:
                    import requests
                    headers = {
                        "Content-Type": "application/json",
                    }
                    cb_key = (payload.get("callback_api_key") or "").strip()
                    if cb_key:
                        headers["Authorization"] = f"Bearer {cb_key}"
                    body = {
                        "ok": True,
                        "ref": ext,
                        "invoice": response["invoice"],
                        "pdf_url": pdf_url,
                        "pdf_attachment_id": att.id,
                    }
                    if payload.get("return_pdf_b64"):
                        body["pdf_base64"] = response["pdf_base64"]
                    requests.post(callback_url, data=json.dumps(body), headers=headers, timeout=20)
                except Exception as cb_err:
                    # Don’t fail the main call; log in chatter
                    move.message_post(body=f"Callback push failed: {cb_err}")

            # Commit so the invoice/attachment are immediately available
            request.env.cr.commit()
            return response

        except Exception as e:
            if rec:
                try:
                    rec.sudo().write({"state": "error", "error_message": str(e)})
                    request.env.cr.commit()
                except Exception:
                    pass
            return {"ok": False, "error": str(e)}

    @http.route(
        "/invoice_poc/jsonrpc/invoices/get",
        type="json",
        auth="api_key",
        methods=["POST"],
        csrf=False,
    )
    def get_invoice_by_ref(self, **kwargs):
        """
        JSON-RPC 2.0 request expected:
        {
          "jsonrpc": "2.0",
          "method": "call",
          "id": 1,
          "params": {"ref": "POC-123" }   # or {"id": "POC-123"}
        }
        """
        try:
            params = request.jsonrequest.get("params") or {}
            ext = params.get("ref") or params.get("id")
            if not ext:
                return {"ok": False, "error": "Missing 'ref' (or 'id') in params."}

            rec = request.env["invoice.poc.payload"].sudo().search([("ext_id", "=", ext)], limit=1)
            if not rec or not rec.move_id:
                return {"ok": False, "error": f"No invoice found for ref '{ext}'."}

            move = rec.move_id.sudo()

            # Also return (or regenerate) a PDF URL here for convenience
            try:
                # Try to find an existing PDF attachment first
                att = request.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'account.move'),
                    ('res_id', '=', move.id),
                    ('mimetype', '=', 'application/pdf'),
                ], limit=1)
                if att:
                    pdf_url = f"/web/content/{att.id}?download=1&filename={att.name}"
                else:
                    pdf_bytes = _render_invoice_pdf_bytes(move)
                    att, pdf_url = _create_pdf_attachment(move, pdf_bytes)
            except Exception:
                pdf_url = None

            return {
                "ok": True,
                "ref": ext,
                "payload_id": rec.id,
                "invoice": _invoice_to_dict(move),
                "pdf_url": pdf_url,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
