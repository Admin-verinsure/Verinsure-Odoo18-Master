# -*- coding: utf-8 -*-
"""
Intercepts the website form POST for the helpdesk page.

From the arch:
  data-model_name="ticket.helpdesk"
  action="/website/form/"
  data-for="contactus_form"  (email notification also sent)

We override website_form() to:
  1. Extract program_type and club_id BEFORE super() strips unknown fields
  2. Call super() — lets odoo_website_helpdesk create the ticket.helpdesk record
  3. Write program_type and club_id onto the new ticket
  4. Append them to the description so they appear in the notification email
"""
import json
import logging

from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm

_logger = logging.getLogger(__name__)


class HelpdeskFormController(WebsiteForm):

    def _resolve_club(self, club_id_raw):
        if not club_id_raw:
            return None, ''
        try:
            club_id = int(club_id_raw)
            partner = request.env['res.partner'].sudo().browse(club_id)
            if partner.exists():
                return club_id, partner.name
        except (ValueError, TypeError):
            _logger.warning("helpdesk_form: invalid club_id %r", club_id_raw)
        return None, ''

    @http.route()
    def website_form(self, model_name, **kwargs):
        program_type = request.params.get('helpdesk_program_type', '').strip()
        club_id_raw  = request.params.get('helpdesk_club_id', '').strip()

        response = super().website_form(model_name, **kwargs)

        # Only act on our helpdesk model
        if model_name != 'ticket.helpdesk':
            return response

        if not (program_type or club_id_raw):
            return response

        club_id, club_name = self._resolve_club(club_id_raw)

        # Get the ticket id from the JSON response
        try:
            resp_data = json.loads(response.data)
            ticket_id = resp_data.get('id')
        except Exception:
            _logger.warning("helpdesk_form: could not parse response for ticket id")
            return response

        if not ticket_id:
            return response

        try:
            ticket = request.env['ticket.helpdesk'].sudo().browse(ticket_id)
            if not ticket.exists():
                return response

            vals = {}
            if program_type:
                vals['program_type'] = program_type
            if club_id:
                vals['club_id'] = club_id

            # Append to description so notification email carries the values
            extra = []
            if program_type:
                extra.append(f'<b>Program Type:</b> {program_type}')
            if club_name:
                extra.append(f'<b>Club:</b> {club_name}')
            if extra:
                existing = ticket.description or ''
                sep = '<br/>' if existing else ''
                vals['description'] = (
                    existing + sep + '<br/><hr/>' + '<br/>'.join(extra)
                )

            ticket.write(vals)
            _logger.info(
                "helpdesk_form: ticket #%s — program_type=%r club_id=%r",
                ticket_id, program_type, club_id,
            )

        except Exception as exc:
            _logger.exception(
                "helpdesk_form: failed writing to ticket #%s: %s", ticket_id, exc
            )

        return response
