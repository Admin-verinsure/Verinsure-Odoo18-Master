# -*- coding: utf-8 -*-
"""
helpdesk_form.py
────────────────
Intercepts the Odoo website-builder form submission on your helpdesk page.

YOUR SETUP (from browser inspector):
  data-for = "contactus_form"   →  the form sends an email (not a ticket record)
  data-model may or may not be set to "helpdesk.ticket" in the website editor.

WE HANDLE BOTH CASES:

  CASE A  data-model="helpdesk.ticket"  (ticket mode)
  ────────────────────────────────────────────────────
  Odoo's WebsiteForm controller creates a helpdesk.ticket record and sends the
  confirmation email.  We let super() do that, then:
    1. Parse the ticket id from the JSON response.
    2. Write program_type (Char) and club_id (Many2one) onto the ticket.
    3. Append human-readable Program Type + Club lines to ticket.description
       so they appear in the existing notification email with zero template changes.

  CASE B  data-for="contactus_form"  (email-only mode)
  ──────────────────────────────────────────────────────
  Odoo's WebsiteForm controller sends an email but creates NO record.
  We override website_form_input_filter() to inject the two fields into the
  "description" / "body" that gets emailed, so they appear in the inbox.

  HOW TO SWITCH TO TICKET MODE IN THE WEBSITE EDITOR:
    • Open the page in Edit mode
    • Click the form block → gear icon → "Form" tab
    • Set "Action" to "Create a Task" / "Create a Ticket" and pick
      the helpdesk team  (this sets data-model="helpdesk.ticket")
    • Save – from that point CASE A applies and tickets are created in the DB.
"""
import json
import logging

from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm

_logger = logging.getLogger(__name__)


class HelpdeskFormController(WebsiteForm):

    # ── shared helper ────────────────────────────────────────────────────────

    def _resolve_club(self, club_id_raw):
        """
        Convert the raw string club id from the POST into (int_id, name).
        Returns (None, '') on any failure.
        """
        if not club_id_raw:
            return None, ''
        try:
            club_id = int(club_id_raw)
            partner = request.env['res.partner'].sudo().browse(club_id)
            if partner.exists():
                return club_id, partner.name
        except (ValueError, TypeError):
            _logger.warning(
                "helpdesk_form: invalid helpdesk_club_id value %r", club_id_raw
            )
        return None, ''

    # ── CASE A: ticket mode (data-model="helpdesk.ticket") ──────────────────

    @http.route()
    def website_form(self, model_name, **kwargs):
        """
        Intercept every website-builder POST.
        We only act when the target model is helpdesk.ticket; all other
        forms pass through untouched.
        """
        # Grab custom params BEFORE super() – Odoo strips unknown fields
        program_type = request.params.get('helpdesk_program_type', '').strip()
        club_id_raw  = request.params.get('helpdesk_club_id', '').strip()

        # Let Odoo do its normal work (create ticket, send email, return JSON)
        response = super().website_form(model_name, **kwargs)

        if model_name != 'helpdesk.ticket':
            return response          # not our form – leave untouched

        if not (program_type or club_id_raw):
            return response          # fields not submitted – nothing to do

        club_id, club_name = self._resolve_club(club_id_raw)

        # ── Find the ticket just created ─────────────────────────────────────
        try:
            resp_data = json.loads(response.data)
            ticket_id = resp_data.get('id')
        except Exception:
            _logger.warning(
                "helpdesk_form: could not parse response JSON to get ticket id"
            )
            return response

        if not ticket_id:
            return response

        try:
            ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id)
            if not ticket.exists():
                return response

            vals = {}

            # Write the two custom fields
            if program_type:
                vals['program_type'] = program_type
            if club_id:
                vals['club_id'] = club_id

            # Append to description so the default email template shows them
            extra = []
            if program_type:
                extra.append(f'<b>Program Type:</b> {program_type}')
            if club_name:
                extra.append(f'<b>Club:</b> {club_name}')

            if extra:
                existing = ticket.description or ''
                sep = '<br/>' if existing else ''
                vals['description'] = (
                    existing + sep
                    + '<br/><hr/>'
                    + '<br/>'.join(extra)
                )

            ticket.write(vals)
            _logger.info(
                "helpdesk_form: ticket #%s updated – program_type=%r club_id=%r",
                ticket_id, program_type, club_id,
            )

        except Exception as exc:
            # Never crash the response – just log
            _logger.exception(
                "helpdesk_form: failed writing custom fields to ticket #%s: %s",
                ticket_id, exc,
            )

        return response

    # ── CASE B: email-only mode (data-for="contactus_form") ─────────────────

    def website_form_input_filter(self, env, values):
        """
        Called by WebsiteForm for every field before the record is created
        or the email is composed.  For the contactus_form (email-only), this
        is where we inject Program Type and Club into the message body.

        For ticket mode (CASE A) this runs too, but the ticket write in
        website_form() takes care of the DB side; here we just enrich the body.
        """
        values = super().website_form_input_filter(env, values)

        program_type = request.params.get('helpdesk_program_type', '').strip()
        club_id_raw  = request.params.get('helpdesk_club_id', '').strip()

        if not (program_type or club_id_raw):
            return values

        _, club_name = self._resolve_club(club_id_raw)

        # Build extra lines to append to whichever body field is present
        extra_lines = []
        if program_type:
            extra_lines.append(f'Program Type: {program_type}')
        if club_name:
            extra_lines.append(f'Club: {club_name}')

        extra_text = '\n'.join(extra_lines)
        extra_html = '<br/>'.join(
            [f'<b>{ln}</b>' for ln in extra_lines]
        )

        # Odoo contactus_form uses 'description' or 'body' as the message field
        for key in ('description', 'body', 'message'):
            if key in values:
                existing = values[key] or ''
                if '<' in existing:          # HTML body
                    values[key] = existing + '<br/><hr/>' + extra_html
                else:                        # plain text
                    values[key] = existing + '\n\n---\n' + extra_text
                break
        else:
            # No body field found – add description so it at least lands
            # in the email payload
            values['description'] = extra_text

        return values
