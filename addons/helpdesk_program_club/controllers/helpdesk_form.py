# -*- coding: utf-8 -*-
"""
Intercepts /website/form/ POST for ticket.helpdesk model.
Saves the selected club_id (res.partner id) onto the ticket after creation.
"""
import json
import logging

from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm

_logger = logging.getLogger(__name__)


class HelpdeskFormController(WebsiteForm):

    @http.route()
    def website_form(self, model_name, **kwargs):
        # Grab club_id BEFORE super() — Odoo strips unrecognised fields
        club_id_raw = request.params.get('helpdesk_club_id', '').strip()

        response = super().website_form(model_name, **kwargs)

        if model_name != 'ticket.helpdesk' or not club_id_raw:
            return response

        try:
            club_id = int(club_id_raw)
        except (ValueError, TypeError):
            _logger.warning("helpdesk_form: invalid club_id %r", club_id_raw)
            return response

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
            if ticket.exists():
                ticket.write({'club_id': club_id})
                _logger.info(
                    "helpdesk_form: ticket #%s — club_id set to %s", ticket_id, club_id
                )
        except Exception as e:
            _logger.exception(
                "helpdesk_form: failed writing club_id to ticket #%s: %s", ticket_id, e
            )

        return response
