# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo.http import request
from odoo.addons.odoo_website_helpdesk.controller.website_form import WebsiteFormInherit

_logger = logging.getLogger(__name__)


class WebsiteFormInheritClub(WebsiteFormInherit):

    def _handle_website_form(self, model_name, **kwargs):
        """
        Inject helpdesk_club_id into kwargs before the parent builds rec_val.
        The parent hardcodes its field list, so we post-process the created
        ticket and write the club field onto it immediately after creation.
        """
        # Let the parent create the ticket normally
        result = super()._handle_website_form(model_name, **kwargs)

        if model_name == 'ticket.helpdesk':
            # Parse the ticket id from the JSON result
            try:
                data = json.loads(result)
                ticket_id = data.get('id')
            except Exception:
                return result

            if not ticket_id:
                return result

            # Now write our custom field onto the ticket
            raw_club = kwargs.get('helpdesk_club_id', '')
            if isinstance(raw_club, str):
                raw_club = raw_club.strip()

            if raw_club and str(raw_club) not in ('0', 'False', 'false', ''):
                try:
                    club_id = int(raw_club)
                    ticket = request.env['ticket.helpdesk'].sudo().browse(ticket_id)
                    ticket.write({'helpdesk_club_id': club_id})
                    _logger.info(
                        "helpdesk_club: wrote club_id=%d onto ticket id=%d",
                        club_id, ticket_id
                    )
                except (ValueError, TypeError) as e:
                    _logger.warning("helpdesk_club: cannot cast club_id=%r: %s", raw_club, e)

        return result
