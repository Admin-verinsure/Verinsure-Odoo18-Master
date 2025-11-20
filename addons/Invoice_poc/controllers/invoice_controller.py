from odoo import http
from odoo.http import request

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
          "params": { ...payload... }
        }
        """
        rec = None
        try:
            payload = request.jsonrequest.get("params") or {}
            ext = payload.get("id") or payload.get("ref")  # your cross-system key

            # Create payload row (idempotent by unique ext_id). If duplicate, fall back to existing.
            try:
                rec = request.env["invoice.poc.payload"].sudo().create({
                    "ext_id": ext,
                    "payload_json": request.make_json(payload),
                })
            except Exception as e:
                # UniqueViolation handling (idempotency)
                if UniqueViolation and isinstance(e.__cause__, UniqueViolation) or "unique" in str(e).lower():
                    rec = request.env["invoice.poc.payload"].sudo().search([("ext_id", "=", ext)], limit=1)
                    if not rec:
                        raise
                else:
                    raise

            # If already processed earlier, reuse that invoice
            move = rec.move_id
            if not move:
                move = rec.sudo().action_create_and_post_invoice()

            # --- NEW: send invoice email immediately (no cron wait) ---
            try:
                template = request.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
                if template and move.partner_id.email:
                    template.sudo().send_mail(
                        move.id,
                        force_send=True,  # send now
                        email_values={
                            'email_to': move.partner_id.email,
                            # Use a valid sender to satisfy SPF/DKIM/DMARC
                            'email_from': move.company_id.email or request.env.user.email_formatted,
                        },
                    )
                else:
                    move.message_post(body="Invoice posted; email not sent (no template or customer email).")
            except Exception as mail_e:
                # Do not fail the API call for mail errors—just log on the chatter
                move.message_post(body=f"Immediate email send failed: {mail_e}")

            # Commit so the invoice (and mail status) are immediately visible
            request.env.cr.commit()

            return {
                "ok": True,
                "ref": ext,
                "payload_id": rec.id,
                "invoice": _invoice_to_dict(move),
            }

        except Exception as e:
            # Persist error on the payload row (if any)
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
            return {
                "ok": True,
                "ref": ext,
                "payload_id": rec.id,
                "invoice": _invoice_to_dict(move),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
